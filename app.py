# ============================================================
# app.py — CVScreener Web App ด้วย Streamlit + Groq AI
# ============================================================
# ติดตั้ง: pip install streamlit groq
# รัน:     streamlit run app.py
# เปิด:    http://localhost:8501
# ============================================================

import streamlit as st
import sys, os, tempfile, json
from pathlib import Path

sys.path.append(".")
from models import Config, ResumeScreener

# ── Page config ─────────────────────────────────────────────
st.set_page_config(
    page_title="CVScreener — SSI v3",
    page_icon="📋",
    layout="wide",
)

# ── CSS ─────────────────────────────────────────────────────
st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }
    .result-pass   { color: #1db954; font-weight: bold; }
    .result-review { color: #fac775; font-weight: bold; }
    .result-fail   { color: #f09595; font-weight: bold; }
    .stButton > button {
        width: 100%;
        background: #378add;
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.6rem;
        font-size: 15px;
        font-weight: 500;
    }
    .stButton > button:hover { background: #185fa5; }
    .ai-insight {
        background: #1a1a30;
        border-left: 3px solid #378add;
        padding: 10px 14px;
        border-radius: 0 8px 8px 0;
        margin-top: 8px;
        font-size: 14px;
    }
</style>
""", unsafe_allow_html=True)

# ── Header ───────────────────────────────────────────────────
st.title("📋 CVScreener — SSI v3")
st.caption("TF-IDF + Rule-Based · ฟรี 100% · รองรับ Groq AI")
st.divider()

# ── Layout ───────────────────────────────────────────────────
col_left, col_right = st.columns([1, 2])

# ════════════════════════════════════════════════════════════
# LEFT — ตั้งค่า
# ════════════════════════════════════════════════════════════
with col_left:
    st.subheader("⚙️ ตั้งค่า")

    # ── โหมด AI ─────────────────────────────────────────────
    st.markdown("**โหมดการวิเคราะห์**")
    ai_mode = st.radio(
        "โหมด",
        ["TF-IDF เท่านั้น (ฟรี 100%)", "Hybrid: TF-IDF + Groq AI"],
        label_visibility="collapsed"
    )

    groq_api_key = ""
    ai_threshold = 30

    if ai_mode == "Hybrid: TF-IDF + Groq AI":
        groq_api_key = st.text_input(
            "Groq API Key",
            type="password",
            placeholder="gsk_...",
        )
        ai_threshold = st.slider(
            "ส่ง AI เฉพาะคะแนน TF-IDF >=",
            0, 100, 30,
            help="resume ที่ TF-IDF ต่ำกว่านี้จะถูกตัดออกโดย Rule-Based ประหยัด API"
        )
        if groq_api_key:
            st.success("✓ API Key พร้อมใช้งาน")
        else:
            st.warning("กรุณาใส่ Groq API Key")

    st.divider()

    # ── JD ──────────────────────────────────────────────────
    st.markdown("**Job Description**")
    jd_option = st.radio(
        "วิธีใส่ JD",
        ["อัปโหลดไฟล์ (.txt หรือ .pdf)", "พิมพ์ตรงนี้เลย"],
        label_visibility="collapsed"
    )

    jd_text_final = ""

    if jd_option == "อัปโหลดไฟล์ (.txt หรือ .pdf)":
        jd_file = st.file_uploader("อัปโหลด JD", type=["txt", "pdf"],
                                    label_visibility="collapsed")
        if jd_file:
            if jd_file.name.endswith(".pdf"):
                import fitz
                data = jd_file.read()
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
                    f.write(data)
                    _jd_tmp = f.name
                doc = fitz.open(_jd_tmp)
                jd_text_final = " ".join(p.get_text() for p in doc).lower()
                doc.close()
                os.unlink(_jd_tmp)
            else:
                jd_text_final = jd_file.read().decode("utf-8", errors="ignore").lower()
            st.success(f"✓ {jd_file.name}")
    else:
        jd_typed = st.text_area(
            "พิมพ์ JD ตรงนี้", height=150,
            placeholder="Position: Marketing Officer\nSkills: ...",
        )
        jd_text_final = jd_typed.lower()

    st.divider()

    # ── Resume ──────────────────────────────────────────────
    st.markdown("**Resume PDF**")
    resume_files = st.file_uploader(
        "อัปโหลด Resume", type=["pdf"],
        accept_multiple_files=True,
        label_visibility="collapsed"
    )
    if resume_files:
        for rf in resume_files:
            st.caption(f"📄 {rf.name}")

    st.divider()

    # ── Required Keywords ────────────────────────────────────
    st.markdown("**Required Keywords**")
    req_input = st.text_input(
        "keyword บังคับ (คั่นด้วยช่องว่าง)",
        placeholder="เช่น python data"
    )
    required_keywords = [k.lower() for k in req_input.split() if k]

    edu_choice = st.selectbox(
        "วุฒิการศึกษาขั้นต่ำ",
        ["ไม่กำหนด", "ปวส./อนุปริญญา", "ปริญญาตรี", "ปริญญาโท"]
    )
    edu_map = {
        "ปวส./อนุปริญญา": [
            "diploma","ปวส","associate","อนุปริญญา",
            "bachelor","bachalor","ปริญญาตรี","บัณฑิต",
            "master","ปริญญาโท","graduate","มหาบัณฑิต",
        ],
        "ปริญญาตรี": [
            "bachelor","bachalor","ปริญญาตรี","บัณฑิต","วศ.บ","บธ.บ","วท.บ",
            "master","ปริญญาโท","graduate","มหาบัณฑิต",
        ],
        "ปริญญาโท": [
            "master","ปริญญาโท","graduate","มหาบัณฑิต","วศ.ม","วท.ม",
        ],
    }
    edu_keywords = edu_map.get(edu_choice, [])

    st.divider()

    # ── Bonus Keywords ───────────────────────────────────────
    st.markdown("**Bonus Keywords**")
    bon_input = st.text_input(
        "keyword โบนัส (คั่นด้วยช่องว่าง)",
        placeholder="เช่น react tailwind jest"
    )
    bonus_keywords = [k.lower() for k in bon_input.split() if k]

    st.divider()

    # ── Thresholds ───────────────────────────────────────────
    st.markdown("**เกณฑ์คะแนน**")
    pass_threshold   = st.slider("ผ่าน ≥",    0, 100, 60)
    review_threshold = st.slider("พิจารณา ≥", 0, 100, 40)

    st.divider()
    run_btn = st.button("▶  วิเคราะห์ Resume")


# ════════════════════════════════════════════════════════════
# RIGHT — ผลลัพธ์
# ════════════════════════════════════════════════════════════
with col_right:
    st.subheader("📊 ผลการคัดกรอง")

    if not run_btn:
        st.info("กรอกข้อมูลด้านซ้ายแล้วกด **วิเคราะห์ Resume**")
        st.stop()

    # ── Validate ─────────────────────────────────────────────
    if not jd_text_final.strip():
        st.error("กรุณาใส่ Job Description ก่อนครับ")
        st.stop()
    if not resume_files:
        st.error("กรุณาอัปโหลด Resume อย่างน้อย 1 ไฟล์ครับ")
        st.stop()
    if ai_mode == "Hybrid: TF-IDF + Groq AI" and not groq_api_key:
        st.error("กรุณาใส่ Groq API Key ครับ")
        st.stop()

    # ── Save JD temp ──────────────────────────────────────────
    jd_tmp = tempfile.NamedTemporaryFile(
        delete=False, suffix=".txt", mode="w", encoding="utf-8"
    )
    jd_tmp.write(jd_text_final)
    jd_tmp.close()

    # ── Save resume temps ─────────────────────────────────────
    resume_tmp_paths = []
    for rf in resume_files:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp.write(rf.read())
        tmp.close()
        resume_tmp_paths.append((rf.name, tmp.name))

    # ── Run ───────────────────────────────────────────────────
    config = Config(
        required_keywords=required_keywords,
        edu_keywords=edu_keywords,
        bonus_keywords=bonus_keywords,
        pass_threshold=pass_threshold,
        review_threshold=review_threshold,
    )

    results_raw = []
    ai_insights = {}  # filename → insight dict จาก Groq

    with st.spinner("กำลังวิเคราะห์..."):
        try:
            # ── ด่านที่ 1: TF-IDF ────────────────────────────
            screener = ResumeScreener(config=config)
            results_raw = screener.screen(
                jd_path=jd_tmp.name,
                resume_paths=[p for _, p in resume_tmp_paths],
            )

            # ── ด่านที่ 2: Groq AI (ถ้าเลือก Hybrid) ────────
            if ai_mode == "Hybrid: TF-IDF + Groq AI" and groq_api_key:
                from groq import Groq
                client = Groq(api_key=groq_api_key)

                for r in results_raw:
                    if r.score < ai_threshold:
                        continue  # ข้ามถ้าคะแนนต่ำเกินไป

                    # หา resume text
                    tmp_path = next(
                        (p for _, p in resume_tmp_paths
                         if Path(p).name == r.file or r.file in p),
                        None
                    )
                    if not tmp_path:
                        continue

                    import fitz
                    doc = fitz.open(tmp_path)
                    resume_text = " ".join(
                        page.get_text() for page in doc
                    )[:1500]
                    doc.close()

                    prompt = f"""Analyze this resume vs job description. 
Respond ONLY with valid JSON, no markdown.

JD: {jd_text_final[:600]}

Resume: {resume_text}

JSON format:
{{
  "ai_score": <0-100>,
  "matched_skills": ["skill1","skill2"],
  "missing_skills": ["skill1"],
  "strengths": ["strength1"],
  "summary": "1 sentence summary in Thai"
}}"""

                    try:
                        resp = client.chat.completions.create(
                            model="llama-3.1-8b-instant",
                            messages=[
                                {"role":"system","content":"Respond only with valid JSON."},
                                {"role":"user","content":prompt}
                            ],
                            temperature=0.1,
                            max_tokens=400,
                        )
                        raw = resp.choices[0].message.content.strip()
                        raw = raw.replace("```json","").replace("```","")
                        data = json.loads(raw)

                        # รวมคะแนน TF-IDF 40% + AI 60%
                        combined = round(
                            r.score * 0.40 + data["ai_score"] * 0.60, 1
                        )
                        ai_insights[r.file] = {
                            "ai_score":      data.get("ai_score", 0),
                            "combined":      combined,
                            "matched":       data.get("matched_skills", []),
                            "missing":       data.get("missing_skills", []),
                            "strengths":     data.get("strengths", []),
                            "summary":       data.get("summary", ""),
                        }
                        # อัปเดตคะแนนใน result
                        r.score = combined
                        if combined >= pass_threshold:
                            r.recommendation = "ผ่าน"
                        elif combined >= review_threshold:
                            r.recommendation = "พิจารณาเพิ่มเติม"
                        else:
                            r.recommendation = "ไม่ผ่าน"

                    except Exception as e:
                        ai_insights[r.file] = {"error": str(e)}

                # เรียงใหม่หลัง AI ปรับคะแนน
                results_raw.sort(key=lambda r: r.score, reverse=True)

        except Exception as e:
            st.error(f"Error: {e}")
            st.stop()

    # ── Summary metrics ───────────────────────────────────────
    passed = sum(1 for r in results_raw if r.recommendation == "ผ่าน")
    review = sum(1 for r in results_raw if r.recommendation == "พิจารณาเพิ่มเติม")
    failed = sum(1 for r in results_raw if r.recommendation == "ไม่ผ่าน")
    ai_count = len(ai_insights)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("ทั้งหมด",   len(results_raw))
    m2.metric("✓ ผ่าน",    passed)
    m3.metric("~ พิจารณา", review)
    m4.metric("✗ ไม่ผ่าน", failed)
    m5.metric("🤖 AI ใช้",  ai_count)

    if ai_mode == "Hybrid: TF-IDF + Groq AI":
        st.caption(
            f"🤖 Groq วิเคราะห์ {ai_count}/{len(results_raw)} ไฟล์  "
            f"· ประหยัด {len(results_raw)-ai_count} ไฟล์  "
            f"· ค่าใช้จ่าย AI ≈ 0 บาท (Free tier)"
        )
    else:
        st.caption("💡 ค่าใช้จ่าย AI: 0 บาท")

    st.divider()

    # ── Result cards ──────────────────────────────────────────
    for rank, r in enumerate(results_raw, 1):
        rec    = r.recommendation
        color  = ("result-pass"   if rec == "ผ่าน"
                  else "result-review" if rec == "พิจารณาเพิ่มเติม"
                  else "result-fail")
        symbol = ("✓ ผ่าน" if rec == "ผ่าน"
                  else "~ พิจารณา" if rec == "พิจารณาเพิ่มเติม"
                  else "✗ ไม่ผ่าน")
        ai_tag = " 🤖" if r.file in ai_insights and "error" not in ai_insights[r.file] else ""

        with st.expander(
            f"#{rank}  {r.name}  —  {r.score}/100  [{symbol}]{ai_tag}",
            expanded=(rank <= 3)
        ):
            c1, c2 = st.columns([2, 1])

            with c1:
                st.caption("TF-IDF")
                st.progress(min(int(r.tfidf), 100),
                            text=f"{r.tfidf:.1f} × {config.weight_tfidf} = {r.tfidf*config.weight_tfidf:.1f}")
                st.caption("Keyword")
                st.progress(min(int(r.keyword), 100),
                            text=f"{r.keyword:.1f} × {config.weight_keyword} = {r.keyword*config.weight_keyword:.1f}")
                st.caption("Structure")
                st.progress(min(int(r.struct), 100),
                            text=f"{r.struct:.1f} × {config.weight_struct} = {r.struct*config.weight_struct:.1f}")

                # AI Insights
                insight = ai_insights.get(r.file)
                if insight and "error" not in insight:
                    st.markdown("---")
                    st.markdown("**🤖 Groq AI Insights**")
                    st.caption(f"AI Score: {insight['ai_score']}  →  Combined: {insight['combined']}")
                    if insight.get("summary"):
                        st.markdown(
                            f'<div class="ai-insight">💬 {insight["summary"]}</div>',
                            unsafe_allow_html=True
                        )
                    if insight.get("matched"):
                        st.caption("✓ ตรงกับ JD: " + ", ".join(insight["matched"][:6]))
                    if insight.get("missing"):
                        st.caption("✗ ขาด: " + ", ".join(insight["missing"][:4]))
                    if insight.get("strengths"):
                        st.caption("⭐ จุดแข็ง: " + ", ".join(insight["strengths"][:3]))
                elif insight and "error" in insight:
                    st.caption(f"⚠️ AI Error: {insight['error']}")

            with c2:
                st.metric("คะแนนรวม", f"{r.score}/100")
                st.markdown(
                    f'<span class="{color}">{symbol}</span>',
                    unsafe_allow_html=True
                )
                st.caption(f"ประสบการณ์: {r.experience}")
                if r.error:
                    st.warning(f"หมายเหตุ: {r.error}")

            if r.struct_checks:
                st.caption("โครงสร้าง:")
                cols = st.columns(2)
                for idx, (k, v) in enumerate(r.struct_checks.items()):
                    cols[idx % 2].caption(f"{'✓' if v else '✗'}  {k}")

    st.divider()

    # ── Export JSON ───────────────────────────────────────────
    export = []
    for r in results_raw:
        d = r.to_dict()
        if r.file in ai_insights:
            d["ai_insights"] = ai_insights[r.file]
        export.append(d)

    st.download_button(
        "⬇️  ดาวน์โหลด JSON",
        data=json.dumps(export, ensure_ascii=False, indent=2),
        file_name="results.json",
        mime="application/json",
    )

    # ── Cleanup ───────────────────────────────────────────────
    try:
        os.unlink(jd_tmp.name)
        for _, p in resume_tmp_paths:
            os.unlink(p)
    except Exception:
        pass