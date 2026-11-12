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

from analysis_service import start_job, get_job, get_parsed, has_criteria
from hr_data import clean_hr_data
from lexicon import expand_term
from llm import LLM
from requirements_ai import extract_requirements
from resume_parser import PARSER_VERSION, extract_text
from screening import Matcher, fmt_months
from storage import (user_dirs, clean_folder, clean_filename, file_sha1, user_pdf_files)

# TODO: สลับเป็น database_postgres เมื่อ Postgres กลับมาใช้ได้
from database_postgres import (
    init_db, save_history, get_history_list, get_history_by_id,
    delete_history, get_user_groq_key, search_candidates,
    library_index, library_apply, library_search,
    get_notes, owns_resume, save_note,
)

from auth import auth

try:
    from openpyxl import Workbook
except ImportError:
    raise ImportError("please install : pip install openpyxl")

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024
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
    if request.headers.get("Sec-Fetch-Mode") == "navigate":
        return True
    return "text/html" in request.headers.get("Accept", "")


@app.errorhandler(500)
def handle_server_error(e):
    traceback.print_exc()
    if _wants_html():
        return "เกิดข้อผิดพลาดภายในระบบ", 500
    return jsonify({"error": "เกิดข้อผิดพลาดภายในระบบ ลองใหม่อีกครั้ง หากยังเป็นอยู่ให้แจ้งผู้ดูแล"}), 500


@app.route("/")
@login_required 
def index():
    return render_template("index.html", username=session.get("username"))


def _split_terms(value):
    out, seen = [], set()
    for part in re.split(r"[,\n;|、]+", value or ""):
        t = part.strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def _form_number(form, name, low, high, label):
    raw = (form.get(name) or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{label} ต้องเป็นตัวเลข")
    if not low <= value <= high:
        raise ValueError(f"{label} ต้องอยู่ระหว่าง {low:g} ถึง {high:g}")
    return value


def _read_analysis_params(form):
    try:
        positions = json.loads(form.get("positions") or "[]")
        positions = [str(p).strip() for p in positions if str(p).strip()] if isinstance(positions, list) else []
    except ValueError:
        positions = []
    if not positions:
        positions = _split_terms(form.get("required", ""))

    age_min = _form_number(form, "age_min", 15, 100, "อายุตั้งแต่")
    age_max = _form_number(form, "age_max", 15, 100, "อายุไม่เกิน")
    sal_min = _form_number(form, "salary_min", 0, 10_000_000, "เงินเดือนตั้งแต่")
    sal_max = _form_number(form, "salary_max", 0, 10_000_000, "เงินเดือนไม่เกิน")
    pass_thr = _form_number(form, "pass_threshold", 0, 100, "คะแนนผ่าน")
    rev_thr = _form_number(form, "review_threshold", 0, 100, "คะแนนพิจารณาเพิ่มเติม")
    pass_thr = 60 if pass_thr is None else pass_thr
    rev_thr = 40 if rev_thr is None else rev_thr
    if rev_thr > pass_thr:
        raise ValueError("คะแนนพิจารณาเพิ่มเติมต้องไม่มากกว่าคะแนนผ่าน")
    edu = (form.get("edu") or "").strip()
    gender = form.get("gender") if form.get("gender") in ("male", "female") else None

    return {
        "positions": positions,
        "duties": _split_terms(form.get("duties")),
        "skills": _split_terms(form.get("bonus")),
        "fields": _split_terms(form.get("field_of_study")),
        "general": _split_terms(form.get("general")),
        "min_gpa": _form_number(form, "min_gpa", 0, 4, "GPA ขั้นต่ำ"),
        "min_experience": _form_number(form, "min_experience", 0, 60, "ประสบการณ์ขั้นต่ำ"),
        "min_edu_level": int(edu) if edu in ("1", "2", "3", "4") else None,
        "age_range": (int(age_min or 15), int(age_max or 100)) if (age_min or age_max) else None,
        "salary_range": (sal_min or 0, sal_max or 10_000_000) if (sal_min or sal_max) else None,
        "gender": gender,
        "enable_special": form.get("enable_special") == "on",
        "require_vehicle": form.get("require_vehicle") == "on",
        "require_license": form.get("require_license") == "on",
        "min_toeic": _form_number(form, "min_toeic", 0, 990, "TOEIC ขั้นต่ำ"),
        "pass_threshold": pass_thr, "review_threshold": rev_thr,
        "ai": form.get("ai_mode") == "hybrid",
    }


@app.route("/analyze", methods=["POST"])
@login_required
def analyze():
    """เริ่มงานวิเคราะห์เบื้องหลัง — คืน job_id ให้หน้าเว็บถามความคืบหน้าที่ /analyze/status/<job_id>"""
    user_id = session["user_id"]
    try:
        params = _read_analysis_params(request.form)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    resume_files = [f for f in request.files.getlist("resumes") if f and f.filename]
    if not resume_files:
        return jsonify({"error": "กรุณาเลือกไฟล์ใบสมัครอย่างน้อยหนึ่งไฟล์"}), 400
    jd_files = [request.files[k] for k in ("jd_file", "js_file") if k in request.files and request.files[k].filename]
    if not jd_files and not has_criteria(params):
        return jsonify({"error": "กรุณาเลือกไฟล์ Job Description / Job Specification หรือกรอกเงื่อนไขการคัดกรองอย่างน้อยหนึ่งข้อ"}), 400

    work_dir = Path(tempfile.mkdtemp(prefix="cvs_"))
    jd_paths = []
    for i, f in enumerate(jd_files):
        name = clean_filename(f.filename) or f"jd{i}.txt"
        path = work_dir / f"jd{i}__{name}"
        f.save(path)
        jd_paths.append(path)
    if jd_files:
        params["jd_label"] = clean_filename(jd_files[0].filename)
    resumes = []
    for i, f in enumerate(resume_files):
        name = clean_filename(f.filename) or f"resume_{i}.pdf"
        path = work_dir / f"r{i}.pdf"
        f.save(path)
        resumes.append((name, path))

    groq_key = ""
    if params["ai"]:
        try:
            groq_key = get_user_groq_key(user_id)
        except Exception:
            traceback.print_exc()
    job_id = start_job(user_id, work_dir, jd_paths, resumes, params, groq_key)
    _last_sync.pop(user_id, None)
    return jsonify({"job_id": job_id, "total": len(resumes)}), 202


@app.route("/analyze/status/<job_id>", methods=["GET"])
@login_required
def analyze_status(job_id):
    job = get_job(job_id, session["user_id"])
    if not job:
        return jsonify({"error": "ไม่พบงานวิเคราะห์นี้ อาจหมดอายุหรือเซิร์ฟเวอร์ถูกรีสตาร์ท"}), 404
    if job["status"] == "done":
        _last_sync.pop(session["user_id"], None)
    return jsonify(job)


@app.route("/api/notes/<sha1>", methods=["GET", "POST"])
@login_required
def api_candidate_notes(sha1):
    """ข้อมูลที่ HR กรอกเองต่อใบสมัคร (เงินเดือนที่ต้องการ อายุ ฯลฯ) — ใช้แทนค่าที่อ่านจากไฟล์"""
    user_id = session["user_id"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha1 or "") or not owns_resume(user_id, sha1):
        return jsonify({"error": "ไม่พบใบสมัครนี้ในคลังของคุณ"}), 404
    if request.method == "GET":
        return jsonify({"data": get_notes(user_id, [sha1]).get(sha1, {})})
    try:
        data = clean_hr_data(request.get_json(silent=True) or {})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    save_note(user_id, sha1, data)
    return jsonify({"data": data, "saved": True})


@app.route("/api/jd/extract", methods=["POST"])
@login_required
def api_extract_requirements():
    """ให้ AI อ่าน JD/JS แล้วเสนอเงื่อนไขการคัดกรอง ให้ HR ตรวจและแก้ก่อนวิเคราะห์"""
    files = [request.files[k] for k in ("jd_file", "js_file") if k in request.files and request.files[k].filename]
    if not files:
        return jsonify({"error": "กรุณาเลือกไฟล์ Job Description หรือ Job Specification ก่อน"}), 400
    groq_key = get_user_groq_key(session["user_id"])
    if not groq_key:
        return jsonify({"error": "บัญชีนี้ยังไม่มี Groq API Key จึงใช้ AI ดึงเงื่อนไขไม่ได้"}), 400
    work_dir = Path(tempfile.mkdtemp(prefix="cvs_jd_"))
    try:
        texts = []
        for i, f in enumerate(files):
            path = work_dir / f"jd{i}__{clean_filename(f.filename) or 'jd.txt'}"
            f.save(path)
            texts.append(extract_text(str(path))[0])
        text = "\n".join(texts).strip()
        if not text:
            return jsonify({"error": "อ่านข้อความจากไฟล์ไม่ได้ ไฟล์อาจเป็นภาพสแกนที่ OCR อ่านไม่สำเร็จ"}), 400
        llm = LLM(groq_key)
        req = extract_requirements(llm, text)
        req["tokens_used"] = llm.usage["in"] + llm.usage["out"]
        return jsonify(req)
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "AI ดึงเงื่อนไขไม่สำเร็จ ลองใหม่อีกครั้ง หรือกรอกเงื่อนไขเอง"}), 502
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


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
               "GPA", "วุฒิสูงสุด", "ประสบการณ์", "ประสบการณ์ตรงสาย", "ขาดคุณสมบัติ",
               "เหตุผลที่ไม่ผ่าน", "ต้องตรวจสอบ"])

    for r in data.get("results", []):
        ws.append([
            r.get("rank"), r.get("file"), r.get("score"), r.get("recommendation"),
            r.get("keyword_score"), r.get("ai_score"), r.get("struct_score"),
            r.get("gpa"), r.get("degree_label"), r.get("experience"),
            fmt_months(r["related_experience_months"]) if r.get("related_experience_months") is not None else "",
            ", ".join(r.get("missing_keywords", [])),
            "; ".join(r.get("reject_reasons") or []),
            "; ".join(r.get("review_reasons") or []),
        ])

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    wb.save(tmp.name)
    wb.close()
    return send_file(tmp.name, as_attachment=True,
                      download_name=f"cvscreener_{safe_id}.xlsx")


_last_sync = {}
SYNC_INTERVAL_SECONDS = 30


def sync_library(user_id, force=False):
    """อ่านใบสมัครในคลังของ user เข้าตาราง resume_library (เฉพาะไฟล์ใหม่/ย้ายที่/ถูกลบ/อ่านด้วยเวอร์ชันเก่า)"""
    now = datetime.now().timestamp()
    if not force and now - _last_sync.get(user_id, 0) < SYNC_INTERVAL_SECONDS:
        return
    _last_sync[user_id] = now

    current = {}
    for folder, f in user_pdf_files(user_id):
        try:
            digest, mtime = file_sha1(f)
        except OSError:
            continue
        if digest not in current or mtime > current[digest][2]:
            current[digest] = (folder, f, mtime)

    existing = library_index(user_id)
    inserts, updates = [], []
    for digest, (folder, f, mtime) in current.items():
        row = existing.get(digest)
        stale = row is not None and str(row.get("parser_version") or "") != str(PARSER_VERSION)
        if row is None or stale:
            parsed, _ = get_parsed(user_id, f, None, sha1=digest)
            prof = parsed["profile"]
            months = prof.get("experience_months")
            inserts.append({
                "sha1": digest, "folder": folder, "file_name": f.name, "file_mtime": mtime,
                "text": parsed["text"], "gpa": prof.get("gpa"),
                "experience_years": round(months / 12, 1) if months is not None else None,
                "age": prof.get("age"), "gender": prof.get("gender"),
                "salary_expectation": prof.get("salary_expectation"),
                "profile": prof,
            })
        elif row["folder"] != folder or row["file_name"] != f.name:
            updates.append((row["id"], folder, f.name, mtime))
    deletes = [row["id"] for digest, row in existing.items() if digest not in current]
    if inserts or updates or deletes:
        library_apply(user_id, inserts, updates, deletes)


def match_position_terms(row, terms):
    """คืน (คะแนนความเกี่ยวข้อง, คำที่ตรง) — รองรับคำพ้องไทย/อังกฤษ และให้น้ำหนักชื่อตำแหน่งงานในประวัติมากกว่า"""
    if not terms:
        return 0.0, []
    prof = row.get("profile") or {}
    matcher = Matcher({"text": row.get("text") or "", "profile": prof})
    titles = Matcher({"text": "\n".join(str(t) for t in (prof.get("job_titles") or []) + (prof.get("desired_positions") or [])),
                      "profile": {}})
    relevance, matched = 0.0, []
    for term in terms:
        hit, _ = matcher.find(term)
        if not hit:
            continue
        relevance += 3
        if titles.find(term)[0]:
            relevance += 1
        matched.append(term if hit == term.lower() else f"{term} ({hit})")
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
    keywords = [t for raw in request.args.getlist("keyword") for t in _split_terms(raw)]
    results = []
    for row in library_search(user_id, **filters):
        relevance, matched = match_position_terms(row, terms)
        kw_relevance, kw_matched = match_position_terms(row, keywords)
        if keywords and not kw_matched:
            continue
        relevance += kw_relevance
        row["matched_keywords"] = kw_matched
        prof = row.pop("profile", None) or {}
        row.pop("text", None)
        row["degree_label"] = prof.get("degree_label")
        if prof.get("experience_months") is not None and "experience_years" not in (row.get("hr_data") or {}):
            row["experience"] = fmt_months(prof["experience_months"])
        if terms and not matched:
            continue
        unknown = [label for label, key, active in (
            ("GPA", "gpa", filters["min_gpa"] is not None),
            ("ประสบการณ์", "experience_years", filters["min_experience"] is not None),
            ("อายุ", "age", filters["age_min"] is not None or filters["age_max"] is not None),
            ("เพศ", "gender", filters["gender"] is not None),
            ("เงินเดือนที่คาดหวัง", "salary_expectation", filters["salary_min"] is not None or filters["salary_max"] is not None),
        ) if active and row.get(key) is None]
        row["review_reasons"] = [f"ใบสมัครไม่ระบุ{label} ต้องตรวจสอบ" for label in unknown]
        row["matched_terms"] = matched
        row["relevance"] = relevance
        results.append(row)
    results.sort(key=lambda r: (-r["relevance"], len(r["review_reasons"]),
                                -(r["score"] if r["score"] is not None else -1)))
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