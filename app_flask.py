# ============================================================
# app_flask.py — CVScreener Flask Web App (with Login)
# ============================================================
# ติดตั้ง: pip install flask groq pymupdf flask-bcrypt openpyxl
# รัน:     python app_flask.py
# เปิด:    http://localhost:5050
# ============================================================
# ⚠️ สถานะปัจจุบัน (ตามที่คุยกันไว้ในบทสนทนา):
#   - import ยังชี้ไปที่ `database` (SQLite) ชั่วคราว เพราะ Postgres
#     บน Railway ยัง offline อยู่ (billing) — สลับกลับเป็น
#     `database_postgres` เมื่อแก้ billing เสร็จแล้ว
#   - @login_required ถูก comment ออกชั่วคราวเพื่อทดสอบโดยไม่ต้อง login
#     ต้องเอากลับคืนก่อน deploy จริง (ดูจุดที่มี "TODO คืนค่า" กำกับ)
# ============================================================

import os, json, tempfile, gc, uuid, shutil
from pathlib import Path
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from flask_bcrypt import Bcrypt
import sys
sys.path.append(".")

from models import Config, ResumeScreener, extract_keywords_via_ai

# TODO: สลับเป็น database_postgres เมื่อ Postgres กลับมาใช้ได้
from database import init_db, save_history, get_history_list, get_history_by_id, delete_history, get_user_groq_key

from auth import auth

try:
    from openpyxl import Workbook
except ImportError:
    raise ImportError("please install : pip install openpyxl")

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

bcrypt = Bcrypt(app)
app.register_blueprint(auth)

with app.app_context():
    init_db()

TOKEN_LIMIT_PER_MIN = 6000

QUALIFIED_DIR   = Path("ResultFile/Qualified")
TALENT_POOL_DIR = Path("ResultFile/TalentPool")

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
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def sort_resume_file(orig_name, tmp_path, recommendation, jd_label):
    """FR-5.3 (ผ่าน→Qualified Candidates) / FR-5.4 (ไม่ผ่าน→Talent Pool)"""
    safe_position = "".join(c for c in (jd_label or "unknown") if c.isalnum() or c in " _-")[:50] or "unknown"
    date_str = datetime.now().strftime("%Y-%m-%d")

    if recommendation == "ผ่าน":
        dest_dir = QUALIFIED_DIR / f"{safe_position}_{date_str}"
    else:
        dest_dir = TALENT_POOL_DIR / safe_position

    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy(tmp_path, dest_dir / orig_name)
    except Exception as e:
        print(f"[warn] sort_resume_file failed: {e}")


@app.route("/")
# TODO คืนค่า: ใส่ @login_required กลับก่อน deploy จริง
def index():
    # TODO คืนค่า: ลบ 2 บรรทัดนี้ทิ้งเมื่อเอา @login_required กลับมา
    if not session.get("user_id"):
        session["user_id"] = 1
        session["username"] = "test"
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
                print(f"[DEBUG JD] fitz length={len(jd_text)}")
                if not jd_text.strip():
                    print("[DEBUG JD] fitz อ่านไม่ออก → ลอง OCR")
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
                        print(f"[DEBUG JD] OCR length={len(jd_text)} preview={repr(jd_text[:100])}")
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
                print(f"[DEBUG JS] fitz length={len(js_text)}")
                if not js_text.strip():
                    print("[DEBUG JS] fitz อ่านไม่ออก → ลอง OCR")
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
                        print(f"[DEBUG JS] OCR length={len(js_text)} preview={repr(js_text[:100])}")
                    except Exception as e:
                        print(f"[DEBUG JS] OCR error: {e}")
                try: os.unlink(js_tmp_path)
                except: pass
                js_tmp_path = None
            else:
                js_text = js_file.read().decode("utf-8", errors="ignore").lower()

        jd_text = f"{jd_text} {js_text}".strip()

        if not jd_text:
            return jsonify({"error": "อ่านไฟล์ไม่ออก — PDF อาจเป็นไฟล์สแกน ลองใช้แท็บ 'พิมพ์เอง' แทน หรือแปลงเป็น .txt ก่อน"}), 400

        resume_files = request.files.getlist("resumes")
        if not resume_files or not resume_files[0].filename:
            return jsonify({"error": "กรุณาอัปโหลด Resume"}), 400

        for rf in resume_files:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp_path = tmp.name
            rf.save(tmp_path)
            resume_tmp.append((rf.filename, tmp_path))

        req_kws  = [k.lower() for k in request.form.get("required","").split() if k]
        bon_kws  = [k.lower() for k in request.form.get("bonus","").split() if k]
        edu_kws  = EDU_MAP.get(request.form.get("edu",""), [])
        pass_thr = int(request.form.get("pass_threshold", 60))
        rev_thr  = int(request.form.get("review_threshold", 40))
        ai_mode      = request.form.get("ai_mode", "tfidf")
        ai_threshold = int(request.form.get("ai_threshold", 0))

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

        def has_thai(text: str) -> bool:
            return any('\u0e00' <= c <= '\u0e7f' for c in text)

        def translate_to_english(text: str, client) -> str:
            try:
                resp = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
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
                    max_tokens=1000,
                )
                return resp.choices[0].message.content.strip()
            except Exception:
                return text

        translate_key = groq_key
        if translate_key:
            from groq import Groq as GroqClient
            _trans_client = GroqClient(api_key=translate_key)
            if has_thai(jd_text):
                print(f"[TRANSLATE] JD มีภาษาไทย — กำลังแปล...")
                jd_text = translate_to_english(jd_text, _trans_client)
                print(f"[TRANSLATE] JD แปลเสร็จ: {jd_text[:100]}")
            if has_thai(js_text):
                print(f"[TRANSLATE] JS มีภาษาไทย — กำลังแปล...")
                js_text = translate_to_english(js_text, _trans_client)
                print(f"[TRANSLATE] JS แปลเสร็จ: {js_text[:100]}")

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
        if ai_mode == "hybrid" and groq_key:
            from groq import Groq as GroqClient
            _kw_client = GroqClient(api_key=groq_key)
            ai_masterlist = extract_keywords_via_ai(combined_jd, _kw_client)
            print(f"[FR-4.6] AI master list: {ai_masterlist}")

        config = Config(
            position_keywords=req_kws,
            skill_keywords=bon_kws,
            edu_level_keywords=edu_kws,
            min_gpa=min_gpa,
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
                r.file = matched

        ai_insights = {}  # เก็บไว้เผื่อ frontend เดิมอ้างถึง (ไม่ใช้จริงแล้ว — AI คำนวณใน models.py แล้ว)
        total_input_tokens  = 0
        total_output_tokens = 0
        total_tokens_used   = 0

        output = []
        for rank, r in enumerate(results, 1):
            d = r.to_dict()
            d["rank"]    = rank
            d["insight"] = ai_insights.get(r.file, None)
            output.append(d)

            # FR-5.3/5.4: sort resume ลงโฟลเดอร์
            tmp_path = next((p for orig, p in resume_tmp if orig == r.file), None)
            if tmp_path:
                sort_resume_file(r.file, tmp_path, r.recommendation, jd_label)

        tokens_remaining = max(0, TOKEN_LIMIT_PER_MIN - total_tokens_used)

        summary = {
            "total":   len(output),
            "passed":  sum(1 for r in results if r.recommendation == "ผ่าน"),
            "review":  sum(1 for r in results if r.recommendation == "พิจารณาเพิ่มเติม"),
            "failed":  sum(1 for r in results if r.recommendation == "ไม่ผ่าน"),
            "ai_used": len(output) if ai_masterlist else 0,
            "max_possible_score": 100 if ai_masterlist else 75,
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
                timestamp    = datetime.now().isoformat(timespec="seconds"),
                jd_label     = jd_label,
                resume_count = len(resume_tmp),
                summary      = summary,
                results      = output,
            )
        except Exception:
            pass

        return jsonify({"results": output, "summary": summary, "history_id": history_id})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
               "GPA", "ประสบการณ์", "ขาดคุณสมบัติ"])

    for r in data.get("results", []):
        ws.append([
            r.get("rank"), r.get("file"), r.get("score"), r.get("recommendation"),
            r.get("keyword_score"), r.get("ai_score"), r.get("struct_score"),
            r.get("gpa"), r.get("experience"),
            ", ".join(r.get("missing_keywords", [])),
        ])

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    wb.save(tmp.name)
    wb.close()
    return send_file(tmp.name, as_attachment=True,
                      download_name=f"cvscreener_{safe_id}.xlsx")


if __name__ == "__main__":
    app.run(debug=True, port=5050)