# ============================================================
# app_flask.py — CVScreener Flask Web App (with Login)
# ============================================================
# ติดตั้ง: pip install flask groq pymupdf flask-bcrypt openpyxl
# รัน:     python app_flask.py
# เปิด:    http://localhost:5050
# ============================================================
# ⚠️ สถานะปัจจุบัน:
#   - import ยังชี้ไปที่ `database` (SQLite) ชั่วคราว เพราะ Postgres
#     บน Railway ยัง offline อยู่ (billing) — สลับกลับเป็น
#     `database_postgres` เมื่อแก้ billing เสร็จแล้ว
#   - @login_required ถูก comment ออกชั่วคราวเพื่อทดสอบโดยไม่ต้อง login
#     ต้องเอากลับคืนก่อน deploy จริง (ดูจุดที่มี "TODO คืนค่า" กำกับ)
# ============================================================

import os, json, tempfile, gc, uuid, shutil, hashlib, re
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlparse
import traceback
from functools import wraps
from flask.json.provider import DefaultJSONProvider
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from flask_bcrypt import Bcrypt
import sys
sys.path.append(".")

from models import (Config, ResumeScreener, extract_jd_profile_via_ai, PDFReader,
                    extract_gpa, extract_experience_years, extract_age,
                    extract_gender, extract_salary_expectation)

# TODO: สลับเป็น database_postgres เมื่อ Postgres กลับมาใช้ได้
from database_postgres import (
    init_db, save_history, get_history_list, get_history_by_id,
    delete_history, get_user_groq_key, search_candidates,
    library_index, library_apply, library_search,
)

from auth import auth

try:
    from openpyxl import Workbook
except ImportError:
    raise ImportError("please install : pip install openpyxl")

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)
app.json.default = lambda o: float(o) if isinstance(o, Decimal) else DefaultJSONProvider.default(o)


@app.before_request
def verify_request_origin():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        source = request.headers.get("Origin") or request.headers.get("Referer")
        if source and urlparse(source).netloc != request.host:
            return jsonify({"error": "คำขอไม่ผ่านการตรวจสอบต้นทาง"}), 403

bcrypt = Bcrypt(app)
app.register_blueprint(auth)

with app.app_context():
    init_db()

TOKEN_LIMIT_PER_MIN = int(os.environ.get("GROQ_TPM_LIMIT", "8000"))
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

RESULT_ROOT = Path("ResultFile")


def user_dirs(user_id):
    root = RESULT_ROOT / f"user_{int(user_id)}"
    return root / "Qualified", root / "TalentPool", root / "Uploaded"


def clean_folder(name):
    return "".join(c for c in (name or "") if c.isalnum() or c in " _-").strip()


def clean_filename(name):
    base = (name or "").replace("\\", "/").split("/")[-1].strip()
    base = "".join(c for c in base if c.isprintable())
    return "" if base in ("", ".", "..") or base.startswith(".") else base

EDU_MAP = {
    "1": ["diploma","ปวส","associate","อนุปริญญา",
          "bachelor","bachalor","ปริญญาตรี","บัณฑิต",
          "master","ปริญญาโท","graduate","มหาบัณฑิต"],
    "2": ["bachelor","bachalor","ปริญญาตรี","บัณฑิต","วศ.บ","บธ.บ","วท.บ",
          "master","ปริญญาโท","graduate","มหาบัณฑิต"],
    "3": ["master","ปริญญาโท","graduate","มหาบัณฑิต","วศ.ม","วท.ม"],
}


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            if _wants_html():
                return redirect(url_for("auth.login"))
            return jsonify({"error": "หมดเวลาการใช้งาน กรุณาเข้าสู่ระบบใหม่", "login_required": True}), 401
        return f(*args, **kwargs)
    return decorated


def _wants_html():
    return request.accept_mimetypes.best == "text/html"


@app.errorhandler(500)
def handle_server_error(e):
    traceback.print_exc()
    if _wants_html():
        return "เกิดข้อผิดพลาดภายในระบบ", 500
    return jsonify({"error": "เกิดข้อผิดพลาดภายในระบบ ลองใหม่อีกครั้ง หากยังเป็นอยู่ให้แจ้งผู้ดูแล"}), 500


def sort_resume_file(orig_name, tmp_path, recommendation, jd_label, user_id):
    """FR-5.3 (ผ่าน→Qualified Candidates) / FR-5.4 (ไม่ผ่าน→Talent Pool) — แยกตาม user"""
    qualified_dir, talent_pool_dir, _ = user_dirs(user_id)
    safe_position = clean_folder(jd_label or "unknown")[:50] or "unknown"
    date_str = datetime.now().strftime("%Y-%m-%d")
    file_name = clean_filename(orig_name) or "resume.pdf"

    if recommendation == "ผ่าน":
        dest_dir = qualified_dir / f"{safe_position}_{date_str}"
    else:
        dest_dir = talent_pool_dir / safe_position

    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy(tmp_path, dest_dir / file_name)
    except Exception as e:
        print(f"[warn] sort_resume_file failed: {e}")


@app.route("/")
@login_required 
def index():
    return render_template("index.html", username=session.get("username"))


@app.route("/analyze", methods=["POST"])
@login_required
def analyze():
    jd_tmp_path = None
    jd_txt_path = None
    resume_tmp  = []
    translated_tmp_paths = {}

    try:
        import fitz

        # ── รับ JD ────────────────────────────────────────
        jd_text  = ""
        jd_label = "Job Description"
        if "jd_file" in request.files and request.files["jd_file"].filename:
            jd_file = request.files["jd_file"]
            jd_label = jd_file.filename
            if jd_file.filename.lower().endswith(".pdf"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
                    jd_file.save(f.name)
                    jd_tmp_path = f.name
                doc = fitz.open(jd_tmp_path)
                jd_text = " ".join(p.get_text() for p in doc).lower()
                doc.close()
                doc = None
                if not jd_text.strip():
                    try:
                        import pytesseract
                        from PIL import Image as PILImage
                        import io, platform
                        if platform.system() == 'Windows':
                            pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
                        doc = fitz.open(jd_tmp_path)
                        ocr_texts = []
                        for page in doc:
                            pix = page.get_pixmap(dpi=200)
                            img = PILImage.open(io.BytesIO(pix.tobytes('png')))
                            ocr_texts.append(pytesseract.image_to_string(img, lang='tha+eng'))
                        doc.close()
                        jd_text = " ".join(ocr_texts).lower()
                    except Exception as e:
                        print(f"[DEBUG JD] OCR error: {e}")
                try: os.unlink(jd_tmp_path)
                except: pass
                jd_tmp_path = None
            else:
                jd_text = jd_file.read().decode("utf-8", errors="ignore").lower()
        elif request.form.get("jd_text"):
            jd_text = request.form["jd_text"].lower()
            jd_label = (request.form["jd_text"].strip().splitlines() or ["Job Description"])[0][:60]

        # ── รับ JS ────────────────────────────────────────
        js_text  = ""
        js_tmp_path = None
        if "js_file" in request.files and request.files["js_file"].filename:
            js_file = request.files["js_file"]
            if js_file.filename.lower().endswith(".pdf"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
                    js_file.save(f.name)
                    js_tmp_path = f.name
                doc = fitz.open(js_tmp_path)
                js_text = " ".join(p.get_text() for p in doc).lower()
                doc.close()
                doc = None
                if not js_text.strip():
                    try:
                        import pytesseract
                        from PIL import Image as PILImage
                        import io, platform
                        if platform.system() == 'Windows':
                            pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
                        doc = fitz.open(js_tmp_path)
                        ocr_texts = []
                        for page in doc:
                            pix = page.get_pixmap(dpi=200)
                            img = PILImage.open(io.BytesIO(pix.tobytes('png')))
                            ocr_texts.append(pytesseract.image_to_string(img, lang='tha+eng'))
                        doc.close()
                        js_text = " ".join(ocr_texts).lower()
                    except Exception as e:
                        print(f"[DEBUG JS] OCR error: {e}")
                try: os.unlink(js_tmp_path)
                except: pass
                js_tmp_path = None
            else:
                js_text = js_file.read().decode("utf-8", errors="ignore").lower()

        jd_text = f"{jd_text} {js_text}".strip()

        jd_from_criteria = False
        if not jd_text:
            has_jd_file = any(request.files.get(k) and request.files[k].filename for k in ("jd_file", "js_file"))
            if has_jd_file:
                return jsonify({"error": "อ่านข้อความจากไฟล์ Job Description / Job Specification ไม่ได้ ไฟล์อาจเป็นภาพสแกนและระบบอ่านภาพ (OCR) ไม่สำเร็จ ลองใช้ไฟล์ PDF ที่เลือกข้อความได้ บันทึกเป็น .txt หรือนำไฟล์ออกแล้วคัดกรองตามเงื่อนไขอย่างเดียว"}), 400
            criteria_text = " ".join(
                request.form.get(k, "").strip()
                for k in ("required", "duties", "bonus", "field_of_study", "general")
                if request.form.get(k, "").strip()
            )
            numeric_given = any(
                request.form.get(k, "").strip()
                for k in ("min_gpa", "min_experience", "age_min", "age_max", "salary_min", "salary_max", "gender")
            )
            if not criteria_text and not numeric_given:
                return jsonify({"error": "กรุณาเลือกไฟล์ Job Description / Job Specification หรือกรอกเงื่อนไขการคัดกรองอย่างน้อยหนึ่งข้อ"}), 400
            jd_text = criteria_text.lower()
            jd_from_criteria = True
            titles = request.form.get("required", "").strip()
            jd_label = (f"เงื่อนไข {titles}" if titles else "คัดกรองตามเงื่อนไข")[:60]

        resume_files = request.files.getlist("resumes")
        if not resume_files or not resume_files[0].filename:
            return jsonify({"error": "กรุณาอัปโหลด Resume"}), 400

        for rf in resume_files:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp_path = tmp.name
            rf.save(tmp_path)
            resume_tmp.append((rf.filename, tmp_path))

        req_kws     = [k.lower() for k in request.form.get("required","").split() if k]
        bon_kws     = [k.lower() for k in request.form.get("bonus","").split() if k]
        duties_kws  = [k.lower() for k in request.form.get("duties","").split() if k]
        field_kws   = [k.lower() for k in request.form.get("field_of_study","").split() if k]
        general_kws = [k.lower() for k in request.form.get("general","").split() if k]
        edu_kws     = EDU_MAP.get(request.form.get("edu",""), [])
        try:
            pass_thr = int(request.form.get("pass_threshold") or 60)
            rev_thr  = int(request.form.get("review_threshold") or 40)
        except ValueError:
            return jsonify({"error": "เกณฑ์ผ่าน/เกณฑ์พิจารณาต้องเป็นตัวเลขจำนวนเต็ม"}), 400
        ai_mode      = request.form.get("ai_mode", "tfidf")

        groq_key = session.get("groq_api_key", "") or get_user_groq_key(session["user_id"])

        min_gpa_raw = request.form.get("min_gpa", "").strip()
        min_gpa = float(min_gpa_raw) if min_gpa_raw else None

        # ── FR-3: อ่านค่า filter ใหม่จากฟอร์ม ─────────────────
        age_min = request.form.get("age_min", type=int)
        age_max = request.form.get("age_max", type=int)
        age_range = (age_min, age_max) if age_min and age_max else None

        gender = request.form.get("gender") or None

        salary_min = request.form.get("salary_min", type=float)
        salary_max = request.form.get("salary_max", type=float)
        salary_range = (salary_min, salary_max) if salary_min and salary_max else None

        enable_special  = request.form.get("enable_special") == "on"
        require_vehicle = request.form.get("require_vehicle") == "on"
        require_license = request.form.get("require_license") == "on"
        min_toeic       = request.form.get("min_toeic", type=float)
        min_experience  = request.form.get("min_experience", type=float)

        ai_usage = {"in": 0, "out": 0}

        def has_thai(text: str) -> bool:
            return any('\u0e00' <= c <= '\u0e7f' for c in text)

        def translate_to_english(text: str, client) -> str:
            try:
                resp = client.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=[
                        {"role": "system", "content": (
                            "You are a professional translator. "
                            "Translate the Thai text to English accurately. "
                            "Keep proper nouns, company names, and technical terms as-is. "
                            "Return ONLY the translated text, no explanations."
                        )},
                        {"role": "user", "content": text[:2000]},
                    ],
                    temperature=0.1,
                    max_tokens=2000,
                    extra_body={"reasoning_effort": "low"},
                )
                usage = getattr(resp, "usage", None)
                ai_usage["in"]  += getattr(usage, "prompt_tokens", 0) or 0
                ai_usage["out"] += getattr(usage, "completion_tokens", 0) or 0
                return resp.choices[0].message.content.strip()
            except Exception as e:
                print(f"[warn] translate_to_english failed: {e}")
                return text

        translate_key = groq_key
        if translate_key:
            from groq import Groq as GroqClient
            _trans_client = GroqClient(api_key=translate_key)
            if has_thai(jd_text):
                jd_text = translate_to_english(jd_text, _trans_client)
            if has_thai(js_text):
                js_text = translate_to_english(js_text, _trans_client)

        combined_jd = f"{jd_text} {js_text}".strip()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as jd_tmp:
            jd_tmp.write(combined_jd)
            jd_txt_path = jd_tmp.name

        translated_tmp_paths = {}

        if translate_key:
            if '_trans_client' not in dir():
                from groq import Groq as GroqClient
                _trans_client = GroqClient(api_key=translate_key)

            thai_resumes = []
            for orig_name, tmp_path in resume_tmp:
                try:
                    doc = fitz.open(tmp_path)
                    text = " ".join(page.get_text() for page in doc)
                    doc.close()
                    if has_thai(text):
                        thai_resumes.append((orig_name, tmp_path, text))
                except Exception:
                    pass

            BATCH_SIZE = 5
            for i in range(0, len(thai_resumes), BATCH_SIZE):
                batch = thai_resumes[i:i + BATCH_SIZE]
                for orig_name, tmp_path, thai_text in batch:
                    translated = translate_to_english(thai_text, _trans_client)
                    with tempfile.NamedTemporaryFile(
                        delete=False, suffix=".txt", mode="w", encoding="utf-8"
                    ) as tf:
                        tf.write(translated)
                        translated_tmp_paths[orig_name] = tf.name

        effective_paths = []
        for orig_name, tmp_path in resume_tmp:
            if orig_name in translated_tmp_paths:
                effective_paths.append(translated_tmp_paths[orig_name])
            else:
                effective_paths.append(tmp_path)

        # ── FR-4.6: สกัด keyword master list จาก JD/JS ด้วย AI (ครั้งเดียว) ──
        ai_masterlist = []
        auto_filled = []
        if ai_mode == "hybrid" and groq_key and combined_jd:
            from groq import Groq as GroqClient
            _kw_client = GroqClient(api_key=groq_key)
            jd_profile = extract_jd_profile_via_ai(combined_jd, _kw_client)
            ai_masterlist = jd_profile["all"]
            ai_usage["in"]  += jd_profile.get("usage", {}).get("in", 0)
            ai_usage["out"] += jd_profile.get("usage", {}).get("out", 0)
            print(f"[FR-4.6] AI master list: {ai_masterlist}")
            if not req_kws and jd_profile["position"]:
                req_kws = jd_profile["position"]
                auto_filled.append("ตำแหน่งงาน")
            if not duties_kws and jd_profile["duties"]:
                duties_kws = jd_profile["duties"]
                auto_filled.append("ลักษณะงาน")
            if not bon_kws and jd_profile["skills"]:
                bon_kws = jd_profile["skills"]
                auto_filled.append("ทักษะ")

        config = Config(
            position_keywords=req_kws,
            duties_keywords=duties_kws,
            skill_keywords=bon_kws,
            field_of_study_keywords=field_kws,
            general_keywords=general_kws,
            edu_level_keywords=edu_kws,
            min_gpa=min_gpa,
            min_experience_years=min_experience,
            age_range=age_range,
            gender=gender,
            salary_range=salary_range,
            enable_special_score=enable_special,
            require_vehicle=require_vehicle,
            require_license=require_license,
            min_toeic_score=min_toeic,
            ai_keyword_masterlist=ai_masterlist,
            pass_threshold=pass_thr,
            review_threshold=rev_thr,
        )
        screener = ResumeScreener(config=config)
        results  = screener.screen(
            jd_path=jd_txt_path,
            resume_paths=effective_paths,
        )

        path_to_original = {p: orig for orig, p in resume_tmp}
        for orig_name, trans_path in translated_tmp_paths.items():
            path_to_original[trans_path] = orig_name
            path_to_original[Path(trans_path).name] = orig_name

        for r in results:
            matched = path_to_original.get(r.file)
            if not matched:
                for orig, p in resume_tmp:
                    if Path(p).name == Path(r.file).name:
                        matched = orig
                        break
            if matched:
                if r.name == Path(r.file).name or r.name == r.file:
                    r.name = Path(matched).stem
                r.file = matched

        ai_insights = {}  # เก็บไว้เผื่อ frontend เดิมอ้างถึง (ไม่ใช้จริงแล้ว — AI คำนวณใน models.py แล้ว)
        total_input_tokens  = ai_usage["in"]
        total_output_tokens = ai_usage["out"]
        total_tokens_used   = total_input_tokens + total_output_tokens

        output = []
        for r in results:
            if r.error and not r.recommendation:
                r.recommendation = "ไม่ผ่าน"

        for rank, r in enumerate(results, 1):
            d = r.to_dict()
            d["rank"]    = rank
            d["insight"] = ai_insights.get(r.file, None)
            output.append(d)

            # FR-5.3/5.4: sort resume ลงโฟลเดอร์
            tmp_path = next((p for orig, p in resume_tmp if orig == r.file), None)
            if tmp_path:
                sort_resume_file(r.file, tmp_path, r.recommendation, jd_label, session["user_id"])

        tokens_remaining = max(0, TOKEN_LIMIT_PER_MIN - total_tokens_used)

        summary = {
            "total":   len(output),
            "passed":  sum(1 for r in results if r.recommendation == "ผ่าน"),
            "review":  sum(1 for r in results if r.recommendation == "พิจารณาเพิ่มเติม"),
            "failed":  sum(1 for r in results if r.recommendation == "ไม่ผ่าน"),
            "ai_used": len(output) if ai_masterlist else 0,
            "ai_warning": ("AI ไม่ทำงาน (ไม่มี Groq key หรือเรียก Groq ไม่สำเร็จ) — คะแนน AI เป็น 0"
                           if ai_mode == "hybrid" and not ai_masterlist else None),
            "max_possible_score": 100 if ai_masterlist else 75,
            "auto_filled": auto_filled,
            "auto_filled_source": "ตำแหน่งและเงื่อนไขที่กรอก" if jd_from_criteria else "Job Description",
            "keyword_warning": (None if config.has_keyword_criteria() else
                                "ยังไม่ได้ตั้งเงื่อนไข Keyword — คะแนนส่วน Keyword เป็น 0 (เปิดโหมด AI เพื่อให้เติมจาก JD อัตโนมัติ)"),
            "tokens_input":     total_input_tokens,
            "tokens_output":    total_output_tokens,
            "tokens_used":      total_tokens_used,
            "tokens_limit":     TOKEN_LIMIT_PER_MIN,
            "tokens_remaining": tokens_remaining,
        }

        history_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
        try:
            save_history(
                history_id   = history_id,
                user_id      = session["user_id"],
                timestamp    = datetime.now().astimezone().isoformat(timespec="seconds"),
                jd_label     = jd_label,
                resume_count = len(resume_tmp),
                summary      = summary,
                results      = output,
                ai_mode      = ai_mode,
            )
        except Exception:
            traceback.print_exc()

        _last_sync.pop(session["user_id"], None)
        return jsonify({"results": output, "summary": summary, "history_id": history_id})

    except Exception:
        traceback.print_exc()
        return jsonify({"error": "เกิดข้อผิดพลาดภายในระบบ ลองใหม่อีกครั้ง หากยังเป็นอยู่ให้แจ้งผู้ดูแล"}), 500

    finally:
        gc.collect()
        if jd_tmp_path:
            try: os.unlink(jd_tmp_path)
            except: pass
        if jd_txt_path:
            try: os.unlink(jd_txt_path)
            except: pass
        for _, p in resume_tmp:
            try: os.unlink(p)
            except: pass
        for p in (translated_tmp_paths or {}).values():
            try: os.unlink(p)
            except: pass


@app.route("/history", methods=["GET"])
@login_required
def history_list_route():
    items = get_history_list(user_id=session["user_id"])
    return jsonify({"history": items})


@app.route("/history/<history_id>", methods=["GET"])
@login_required
def history_get(history_id):
    safe_id = "".join(c for c in history_id if c.isalnum() or c in "_-")
    data = get_history_by_id(safe_id, user_id=session["user_id"])
    if not data:
        return jsonify({"error": "ไม่พบประวัตินี้"}), 404
    return jsonify(data)


@app.route("/history/<history_id>", methods=["DELETE"])
@login_required
def history_delete_route(history_id):
    safe_id = "".join(c for c in history_id if c.isalnum() or c in "_-")
    deleted = delete_history(safe_id, user_id=session["user_id"])
    if not deleted:
        return jsonify({"error": "ไม่พบประวัตินี้หรือไม่มีสิทธิ์ลบ"}), 404
    return jsonify({"deleted": True})


@app.route("/export/excel/<history_id>", methods=["GET"])
@login_required
def export_excel(history_id):
    """FR-5.5 — Export ผลการคัดกรองเป็นไฟล์ Excel"""
    safe_id = "".join(c for c in history_id if c.isalnum() or c in "_-")
    data = get_history_by_id(safe_id, user_id=session["user_id"])
    if not data:
        return jsonify({"error": "ไม่พบประวัตินี้"}), 404

    wb = Workbook()
    ws = wb.active
    ws.title = "ผลการคัดกรอง"
    ws.append(["Rank", "ชื่อไฟล์", "คะแนนรวม", "สถานะ",
               "Keyword Score", "AI Score", "Structure Score",
               "GPA", "ประสบการณ์", "ขาดคุณสมบัติ", "เหตุผลที่ไม่ผ่าน"])

    for r in data.get("results", []):
        ws.append([
            r.get("rank"), r.get("file"), r.get("score"), r.get("recommendation"),
            r.get("keyword_score"), r.get("ai_score"), r.get("struct_score"),
            r.get("gpa"), r.get("experience"),
            ", ".join(r.get("missing_keywords", [])),
            "; ".join(r.get("reject_reasons") or []),
        ])

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    wb.save(tmp.name)
    wb.close()
    return send_file(tmp.name, as_attachment=True,
                      download_name=f"cvscreener_{safe_id}.xlsx")


_hash_cache = {}


def _file_sha1(path):
    st = path.stat()
    key = (str(path), st.st_mtime, st.st_size)
    digest = _hash_cache.get(key)
    if digest is None:
        digest = hashlib.sha1(path.read_bytes()).hexdigest()
        _hash_cache[key] = digest
    return digest, st.st_mtime


def _user_pdf_files(user_id):
    qualified_dir, talent_pool_dir, uploaded_dir = user_dirs(user_id)
    files = []
    for base in (qualified_dir, talent_pool_dir):
        if base.exists():
            for sub in base.iterdir():
                if sub.is_dir():
                    files.extend((sub.name, f) for f in sub.iterdir() if f.suffix.lower() == ".pdf")
    if uploaded_dir.exists():
        files.extend(("Uploaded", f) for f in uploaded_dir.iterdir() if f.suffix.lower() == ".pdf")
    return files


_last_sync = {}
SYNC_INTERVAL_SECONDS = 30


def sync_library(user_id, force=False):
    """อ่านไฟล์ใบสมัครในคลังของ user เข้าตาราง resume_library (เฉพาะไฟล์ใหม่/ย้ายที่/ถูกลบ)"""
    now = datetime.now().timestamp()
    if not force and now - _last_sync.get(user_id, 0) < SYNC_INTERVAL_SECONDS:
        return
    _last_sync[user_id] = now
    current = {}
    for folder, f in _user_pdf_files(user_id):
        try:
            digest, mtime = _file_sha1(f)
        except OSError:
            continue
        if digest not in current or mtime > current[digest][2]:
            current[digest] = (folder, f, mtime)

    existing = library_index(user_id)
    reader = PDFReader()
    inserts, updates = [], []
    for digest, (folder, f, mtime) in current.items():
        row = existing.get(digest)
        if row is None:
            text = reader.read(str(f))
            inserts.append({
                "sha1": digest, "folder": folder, "file_name": f.name, "file_mtime": mtime,
                "text": text, "gpa": extract_gpa(text) if text else None,
                "experience_years": extract_experience_years(text) if text else None,
                "age": extract_age(text) if text else None,
                "gender": extract_gender(text) if text else None,
                "salary_expectation": extract_salary_expectation(text) if text else None,
            })
        elif row["folder"] != folder or row["file_name"] != f.name:
            updates.append((row["id"], folder, f.name, mtime))
    deletes = [row["id"] for digest, row in existing.items() if digest not in current]
    if inserts or updates or deletes:
        library_apply(user_id, inserts, updates, deletes)


def match_position_terms(text, terms):
    """คืน (คะแนนความเกี่ยวข้อง, คำที่ตรง) — วลีตรงทั้งก้อนได้น้ำหนักมากกว่าตรงทีละคำ"""
    text = re.sub(r"\s+", " ", (text or "").lower())
    relevance, matched = 0.0, []
    for term in terms:
        if term in text:
            relevance += 3 + min(text.count(term), 5) * 0.2
            matched.append(term)
        else:
            words = [w for w in term.split() if len(w) > 1]
            if len(words) > 1 and all(w in text for w in words):
                relevance += 1
                matched.append(term)
    return relevance, matched


def _number_arg(name, low, high):
    raw = request.args.get(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} ต้องเป็นตัวเลข")
    if not (low <= value <= high):
        raise ValueError(f"{name} ต้องอยู่ระหว่าง {low:g} ถึง {high:g}")
    return value


@app.route("/api/candidates/search", methods=["GET"])
@login_required
def api_search_candidates():
    """'ค้นหาจากคลัง' — จับคู่ตำแหน่งงานกับเนื้อหาใบสมัครทุกไฟล์ในคลังของ user"""
    try:
        gender = request.args.get("gender", "").strip() or None
        if gender not in (None, "male", "female"):
            print(f"[warn] search: unexpected gender value {gender!r} — ignored")
            gender = None
        filters = dict(
            min_gpa=_number_arg("min_gpa", 0, 4),
            min_experience=_number_arg("min_experience", 0, 60),
            age_min=_number_arg("age_min", 15, 100),
            age_max=_number_arg("age_max", 15, 100),
            gender=gender,
            salary_min=_number_arg("salary_min", 0, 10_000_000),
            salary_max=_number_arg("salary_max", 0, 10_000_000),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    user_id = session["user_id"]
    try:
        sync_library(user_id)
    except Exception:
        traceback.print_exc()

    terms = [t.strip().lower() for t in
             request.args.getlist("position") + request.args.getlist("jd_label_contains") if t.strip()]
    results = []
    for row in library_search(user_id, **filters):
        relevance, matched = match_position_terms(row.pop("text", ""), terms)
        if terms and not matched:
            continue
        row["matched_terms"] = matched
        row["relevance"] = relevance
        results.append(row)
    results.sort(key=lambda r: (-r["relevance"], -(r["score"] if r["score"] is not None else -1)))
    return jsonify({"candidates": results[:200]})


@app.route("/repository", methods=["GET"])
@login_required
def repository_list():
    """หน้า 'คลัง Resume' — list ไฟล์ของ user ที่ล็อกอินอยู่เท่านั้น"""
    qualified_dir, talent_pool_dir, uploaded_dir = user_dirs(session["user_id"])
    items = []
    for base_dir, folder_type in [(qualified_dir, "qualified"), (talent_pool_dir, "pool")]:
        if not base_dir.exists():
            continue
        for subfolder in base_dir.iterdir():
            if not subfolder.is_dir():
                continue
            for f in subfolder.iterdir():
                if f.suffix.lower() == ".pdf":
                    items.append({
                        "filename": f.name,
                        "folder": subfolder.name,
                        "type": folder_type,
                        "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    })

    if uploaded_dir.exists():
        for f in uploaded_dir.iterdir():
            if f.suffix.lower() == ".pdf":
                items.append({
                    "filename": f.name, "folder": "Uploaded", "type": "unsorted",
                    "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                })

    items.sort(key=lambda x: x["modified"], reverse=True)
    return jsonify({
        "items": items,
        "stats": {
            "total": len(items),
            "qualified": sum(1 for i in items if i["type"] == "qualified"),
            "pool": sum(1 for i in items if i["type"] == "pool"),
        }
    })


def _find_user_file(user_id, folder, filename):
    qualified_dir, talent_pool_dir, uploaded_dir = user_dirs(user_id)
    safe_folder = clean_folder(folder)
    safe_name = clean_filename(filename)
    if not safe_name:
        return None
    if safe_folder == "Uploaded":
        candidates = [uploaded_dir / safe_name]
    elif safe_folder:
        candidates = [qualified_dir / safe_folder / safe_name, talent_pool_dir / safe_folder / safe_name]
    else:
        candidates = []
    return next((c for c in candidates if c.is_file()), None)


@app.route("/repository/download/<folder>/<filename>")
@login_required
def repository_download(folder, filename):
    path = _find_user_file(session["user_id"], folder, filename)
    if path:
        return send_file(path.resolve(), as_attachment=True)
    return jsonify({"error": "ไม่พบไฟล์"}), 404


@app.route("/repository/upload", methods=["POST"])
@login_required
def repository_upload():
    """อัปโหลด Resume เข้าคลังตรงๆ โดยไม่ต้องวิเคราะห์ก่อน"""
    files = request.files.getlist("resumes")
    if not files or not files[0].filename:
        return jsonify({"error": "กรุณาเลือกไฟล์"}), 400

    _, _, uploaded_dir = user_dirs(session["user_id"])
    uploaded_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        safe_name = clean_filename(f.filename)
        if not safe_name or not safe_name.lower().endswith(".pdf"):
            continue
        f.save(uploaded_dir / safe_name)
        saved.append(safe_name)

    try:
        sync_library(session["user_id"], force=True)
    except Exception:
        traceback.print_exc()

    return jsonify({"saved": saved, "count": len(saved)})


@app.route("/repository/delete/<folder>/<filename>", methods=["DELETE"])
@login_required
def repository_delete(folder, filename):
    """ลบไฟล์จากคลัง Resume ของ user ที่ล็อกอินอยู่"""
    path = _find_user_file(session["user_id"], folder, filename)
    if path:
        path.unlink()
        _last_sync.pop(session["user_id"], None)
        return jsonify({"deleted": True})
    return jsonify({"error": "ไม่พบไฟล์"}), 404


if __name__ == "__main__":
    app.run(debug=False, port=5050)