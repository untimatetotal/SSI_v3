# ============================================================
# app_flask.py — CVScreener Flask Web App
# ============================================================
# ติดตั้ง: pip install flask groq pymupdf
# รัน:     python app_flask.py
# เปิด:    http://localhost:5000
# ============================================================

import os, json, tempfile, gc, uuid
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import sys
sys.path.append(".")
from models import Config, ResumeScreener

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max

# ── History storage ──────────────────────────────────────────
HISTORY_DIR = Path("history")
HISTORY_DIR.mkdir(exist_ok=True)

# Groq llama-3.1-8b-instant rate limit (tokens per minute, free tier)
TOKEN_LIMIT_PER_MIN = 6000

EDU_MAP = {
    "1": ["diploma","ปวส","associate","อนุปริญญา",
          "bachelor","bachalor","ปริญญาตรี","บัณฑิต",
          "master","ปริญญาโท","graduate","มหาบัณฑิต"],
    "2": ["bachelor","bachalor","ปริญญาตรี","บัณฑิต","วศ.บ","บธ.บ","วท.บ",
          "master","ปริญญาโท","graduate","มหาบัณฑิต"],
    "3": ["master","ปริญญาโท","graduate","มหาบัณฑิต","วศ.ม","วท.ม"],
}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    jd_tmp_path = None
    resume_tmp  = []

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

        # ── รับ Resume ────────────────────────────────────
        resume_files = request.files.getlist("resumes")
        if not resume_files or not resume_files[0].filename:
            return jsonify({"error": "กรุณาอัปโหลด Resume"}), 400

        for rf in resume_files:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp_path = tmp.name
            rf.save(tmp_path)
            resume_tmp.append((rf.filename, tmp_path))

        # ── รับ Config ────────────────────────────────────
        req_kws  = [k.lower() for k in request.form.get("required","").split() if k]
        bon_kws  = [k.lower() for k in request.form.get("bonus","").split() if k]
        edu_kws  = EDU_MAP.get(request.form.get("edu",""), [])
        pass_thr = int(request.form.get("pass_threshold", 60))
        rev_thr  = int(request.form.get("review_threshold", 40))
        ai_mode  = request.form.get("ai_mode", "tfidf")
        groq_key = request.form.get("groq_key", "")

        # ── Save JD temp (txt) ────────────────────────────
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".txt", mode="w", encoding="utf-8"
        ) as jd_tmp:
            jd_tmp.write(jd_text)
            jd_txt_path = jd_tmp.name

        # ── Run TF-IDF ────────────────────────────────────
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

        # ── Run Groq AI (optional) ────────────────────────
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

                tmp_path = next(
                    (p for _, p in resume_tmp
                     if r.file == Path(p).name or r.file in p),
                    None
                )
                if not tmp_path:
                    continue

                doc = fitz.open(tmp_path)
                resume_text = " ".join(
                    page.get_text() for page in doc
                )[:1500]
                doc.close()
                doc = None

                try:
                    resp = client.chat.completions.create(
                        model="llama-3.1-8b-instant",
                        messages=[
                            {"role":"system",
                             "content":"Respond only with valid JSON."},
                            {"role":"user",
                             "content":(
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

                    # ── เก็บ token usage จาก Groq ────────────
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

        # ── Build response ────────────────────────────────
        output = []
        for rank, r in enumerate(results, 1):
            d = r.to_dict()
            d["rank"]    = rank
            d["insight"] = ai_insights.get(r.file, {})
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

        # ── บันทึกประวัติ ──────────────────────────────────
        history_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
        history_entry = {
            "id": history_id,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "jd_label": jd_label,
            "resume_count": len(resume_tmp),
            "summary": summary,
            "results": output,
        }
        try:
            with open(HISTORY_DIR / f"{history_id}.json", "w", encoding="utf-8") as hf:
                json.dump(history_entry, hf, ensure_ascii=False, indent=2)
        except Exception:
            pass  # ไม่ให้การบันทึก history ทำให้ request ล้มเหลว

        return jsonify({"results": output, "summary": summary, "history_id": history_id})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        gc.collect()
        if jd_tmp_path:
            try: os.unlink(jd_tmp_path)
            except: pass
        try: os.unlink(jd_txt_path)
        except: pass
        for _, p in resume_tmp:
            try: os.unlink(p)
            except: pass

@app.route("/history", methods=["GET"])
def history_list():
    """รายการประวัติทั้งหมด เรียงล่าสุดก่อน (ไม่รวม results เต็ม)"""
    items = []
    for f in HISTORY_DIR.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as hf:
                data = json.load(hf)
            items.append({
                "id":            data.get("id", f.stem),
                "timestamp":     data.get("timestamp", ""),
                "jd_label":      data.get("jd_label", "Job Description"),
                "resume_count":  data.get("resume_count", 0),
                "summary":       data.get("summary", {}),
            })
        except Exception:
            continue
    items.sort(key=lambda x: x["timestamp"], reverse=True)
    return jsonify({"history": items})


@app.route("/history/<history_id>", methods=["GET"])
def history_get(history_id):
    """โหลดผลลัพธ์เต็มของรายการประวัติหนึ่งรายการ"""
    # ป้องกัน path traversal
    safe_id = "".join(c for c in history_id if c.isalnum() or c in "_-")
    path = HISTORY_DIR / f"{safe_id}.json"
    if not path.exists():
        return jsonify({"error": "ไม่พบประวัตินี้"}), 404
    try:
        with open(path, "r", encoding="utf-8") as hf:
            data = json.load(hf)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/history/<history_id>", methods=["DELETE"])
def history_delete(history_id):
    """ลบรายการประวัติ"""
    safe_id = "".join(c for c in history_id if c.isalnum() or c in "_-")
    path = HISTORY_DIR / f"{safe_id}.json"
    if not path.exists():
        return jsonify({"error": "ไม่พบประวัตินี้"}), 404
    try:
        path.unlink()
        return jsonify({"deleted": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)