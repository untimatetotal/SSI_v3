# ============================================================
# app_flask.py — CVScreener Flask Web App (with Login)
# ============================================================
# ติดตั้ง: pip install flask groq pymupdf flask-bcrypt
# รัน:     python app_flask.py
# เปิด:    http://localhost:5000
# ============================================================

import os, json, tempfile, gc, uuid
from pathlib import Path
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_bcrypt import Bcrypt
import sys
sys.path.append(".")
from models import Config, ResumeScreener
from database import init_db, save_history, get_history_list, get_history_by_id, delete_history
from auth import auth

app = Flask(__name__)
app.secret_key = "ssi-cvscreener-secret-key-2024"   # เปลี่ยนก่อน deploy จริง
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

bcrypt = Bcrypt(app)
app.register_blueprint(auth)

with app.app_context():
    init_db()

TOKEN_LIMIT_PER_MIN = 6000

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

    try:
        import fitz

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
                try: os.unlink(jd_tmp_path)
                except: pass
                jd_tmp_path = None
            else:
                jd_text = jd_file.read().decode("utf-8", errors="ignore").lower()
        elif request.form.get("jd_text"):
            jd_text = request.form["jd_text"].lower()
            jd_label = (request.form["jd_text"].strip().splitlines() or ["Job Description"])[0][:60]

        if not jd_text.strip():
            return jsonify({"error": "กรุณาใส่ Job Description"}), 400

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
        ai_mode  = request.form.get("ai_mode", "tfidf")
        groq_key = request.form.get("groq_key", "")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as jd_tmp:
            jd_tmp.write(jd_text)
            jd_txt_path = jd_tmp.name

        config = Config(
            required_keywords=req_kws,
            edu_keywords=edu_kws,
            bonus_keywords=bon_kws,
            pass_threshold=pass_thr,
            review_threshold=rev_thr,
        )
        screener = ResumeScreener(config=config)
        results  = screener.screen(
            jd_path=jd_txt_path,
            resume_paths=[p for _, p in resume_tmp],
        )

        path_to_original = {p: orig for orig, p in resume_tmp}
        for r in results:
            matched = path_to_original.get(r.file)
            if not matched:
                for orig, p in resume_tmp:
                    if Path(p).name == Path(r.file).name:
                        matched = orig
                        break
            if matched:
                r.file = matched

        ai_insights = {}
        total_input_tokens  = 0
        total_output_tokens = 0
        total_tokens_used   = 0

        if ai_mode == "hybrid" and groq_key:
            from groq import Groq
            client = Groq(api_key=groq_key)

            for r in results:
                if r.score < 30:
                    continue
                tmp_path = next((p for orig, p in resume_tmp if orig == r.file), None)
                if not tmp_path:
                    continue

                doc = fitz.open(tmp_path)
                resume_text = " ".join(page.get_text() for page in doc)[:1500]
                doc.close()
                doc = None

                try:
                    resp = client.chat.completions.create(
                        model="llama-3.1-8b-instant",
                        messages=[
                            {"role":"system","content":"Respond only with valid JSON."},
                            {"role":"user","content":(
                                f"Analyze resume vs JD. JSON only.\n"
                                f"JD: {jd_text[:600]}\n"
                                f"Resume: {resume_text}\n"
                                f'Return: {{"ai_score":<0-100>,'
                                f'"matched_skills":[],'
                                f'"missing_skills":[],'
                                f'"summary":"Thai 1-sentence summary"}}'
                            )}
                        ],
                        temperature=0.1,
                        max_tokens=300,
                    )

                    usage = getattr(resp, "usage", None)
                    if usage:
                        in_tok  = getattr(usage, "prompt_tokens", 0) or 0
                        out_tok = getattr(usage, "completion_tokens", 0) or 0
                        tot_tok = getattr(usage, "total_tokens", in_tok + out_tok)
                    else:
                        in_tok = out_tok = tot_tok = 0

                    total_input_tokens  += in_tok
                    total_output_tokens += out_tok
                    total_tokens_used   += tot_tok

                    raw  = resp.choices[0].message.content.strip()
                    raw  = raw.replace("```json","").replace("```","")
                    data = json.loads(raw)

                    combined = round(r.score * 0.4 + data["ai_score"] * 0.6, 1)
                    ai_insights[r.file] = {
                        **data,
                        "combined": combined,
                        "tokens_used": tot_tok,
                        "tokens_input": in_tok,
                        "tokens_output": out_tok,
                    }
                    r.score = combined

                    if combined >= pass_thr:
                        r.recommendation = "ผ่าน"
                    elif combined >= rev_thr:
                        r.recommendation = "พิจารณาเพิ่มเติม"
                    else:
                        r.recommendation = "ไม่ผ่าน"

                except Exception as e:
                    ai_insights[r.file] = {"error": str(e)}

            results.sort(key=lambda r: r.score, reverse=True)

        output = []
        for rank, r in enumerate(results, 1):
            d = r.to_dict()
            d["rank"]    = rank
            d["insight"] = ai_insights.get(r.file, None)
            output.append(d)

        tokens_remaining = max(0, TOKEN_LIMIT_PER_MIN - total_tokens_used)

        summary = {
            "total":   len(output),
            "passed":  sum(1 for r in results if r.recommendation == "ผ่าน"),
            "review":  sum(1 for r in results if r.recommendation == "พิจารณาเพิ่มเติม"),
            "failed":  sum(1 for r in results if r.recommendation == "ไม่ผ่าน"),
            "ai_used": len(ai_insights),
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


if __name__ == "__main__":
    app.run(debug=True, port=5000)