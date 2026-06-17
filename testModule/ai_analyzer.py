# ============================================================
# ai_analyzer.py — วิเคราะห์ resume ด้วย Groq AI
# ============================================================
# ใช้ร่วมกับ models.py เดิม ไม่ต้องแก้ไฟล์เดิมเลย
#
# รัน: python main_oop.py (เลือกโหมด 2 ใน terminal)
# ============================================================

import json
from pathlib import Path
from groq import Groq
from models import Config, PDFReader, ResumeResult, ResumeScreener


# ============================================================
#  class GroqAnalyzer — วิเคราะห์ resume ด้วย Groq AI
# ============================================================

class GroqAnalyzer:
    """
    วิเคราะห์ resume ด้วย LLaMA 3 ผ่าน Groq API
    ฟรี 14,400 requests/วัน
    """

    def __init__(self, api_key: str,
                 model: str = "llama-3.1-8b-instant"):
        # llama-3.1-8b-instant = เร็วที่สุด ฟรี
        # llama-3.1-70b-versatile = แม่นยำกว่า แต่ช้ากว่า
        self.client = Groq(api_key=api_key)
        self.model  = model
        self.reader = PDFReader()

    def analyze(self, jd_text: str, resume_path: str) -> ResumeResult:
        """ส่ง JD และ Resume ให้ Groq วิเคราะห์ คืน ResumeResult"""
        filename = Path(resume_path).name

        # อ่าน PDF
        text = self.reader.read(resume_path)
        if not text:
            return ResumeResult(
                name=filename, file=filename,
                error="อ่าน PDF ไม่ได้"
            )

        # สร้าง prompt
        prompt = f"""Analyze this resume against the job description.
Respond ONLY with valid JSON, no markdown, no explanation.

Job Description:
{jd_text[:800]}

Resume:
{text[:1500]}

Respond with this exact JSON:
{{
  "name": "applicant full name",
  "score": <integer 0-100>,
  "recommendation": "<Pass|Consider|Reject>",
  "matched_skills": ["skill1", "skill2"],
  "missing_skills": ["skill1", "skill2"],
  "experience_years": <integer or null>,
  "strengths": ["strength1", "strength2"],
  "weaknesses": ["weakness1"],
  "summary": "one sentence summary in Thai"
}}"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert HR recruiter. Respond only with valid JSON."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.1,   # ต่ำ = ตอบสม่ำเสมอ ไม่สุ่ม
                max_tokens=500,
            )

            raw  = response.choices[0].message.content.strip()
            raw  = raw.replace("```json", "").replace("```", "").strip()
            data = json.loads(raw)

            # แปลง recommendation เป็นภาษาไทย
            rec_map = {
                "Pass":    "ผ่าน",
                "Consider":"พิจารณาเพิ่มเติม",
                "Reject":  "ไม่ผ่าน",
            }
            rec = rec_map.get(data.get("recommendation", "Reject"), "ไม่ผ่าน")

            return ResumeResult(
                name=data.get("name", filename),
                file=filename,
                score=float(data.get("score", 0)),
                recommendation=rec,
                experience=f"{data.get('experience_years', '?')} ปี",
                error=None,
                struct_checks={
                    "matched_skills": data.get("matched_skills", []),
                    "missing_skills": data.get("missing_skills", []),
                    "strengths":      data.get("strengths", []),
                    "weaknesses":     data.get("weaknesses", []),
                    "summary":        data.get("summary", ""),
                }
            )

        except json.JSONDecodeError as e:
            return ResumeResult(
                name=filename, file=filename,
                error=f"JSON parse error: {e}", score=0
            )
        except Exception as e:
            return ResumeResult(
                name=filename, file=filename,
                error=f"Groq Error: {e}", score=0
            )


# ============================================================
#  class HybridScreener — TF-IDF กรองก่อน → Groq วิเคราะห์
# ============================================================

class HybridScreener:
    """
    Hybrid = TF-IDF กรองด่านแรก (ฟรี) → Groq AI วิเคราะห์ละเอียด
    ประหยัด API 50-70% โดยให้ TF-IDF ตัด resume ที่คะแนนต่ำออกก่อน
    """

    def __init__(self, config: Config, api_key: str,
                 model: str = "llama-3.1-8b-instant"):
        self.rule_screener = ResumeScreener(config=config)
        self.ai_analyzer   = GroqAnalyzer(api_key=api_key, model=model)
        self.config        = config

    def screen(self, jd_path: str, resume_paths: list,
               ai_threshold: int = 35) -> list:
        """
        วิเคราะห์ resume ทั้งหมด

        ai_threshold: ส่ง AI เฉพาะ resume ที่ TF-IDF >= N
                      ต่ำกว่านี้ตัดออกโดย Rule-Based (ประหยัด API)
        """
        jd_file = Path(jd_path)
        if not jd_file.exists():
            raise FileNotFoundError(f"ไม่พบไฟล์ JD: {jd_path}")
        jd_text = jd_file.read_text(encoding="utf-8").lower()

        print(f"\nJob Description : {jd_path}")
        print(f"Resume ทั้งหมด  : {len(resume_paths)} ไฟล์")
        print(f"AI threshold    : TF-IDF >= {ai_threshold}")
        print(f"AI model        : {self.ai_analyzer.model}")
        print("=" * 55)

        results  = []
        ai_count = 0

        for path in resume_paths:
            if not Path(path).exists():
                print(f"[skip] ไม่พบ: {path}")
                continue

            print(f"กำลังวิเคราะห์: {path} ...", end=" ", flush=True)

            # ── ด่านที่ 1: TF-IDF (ฟรี) ──────────────────────
            rule_result = self.rule_screener.analyzer.analyze(jd_text, path)

            # อ่านไฟล์ไม่ได้
            if rule_result.error and not rule_result.recommendation:
                print(f"Error ({rule_result.error})")
                results.append(rule_result)
                continue

            # คะแนนต่ำเกินไป ไม่ส่ง AI
            if rule_result.score < ai_threshold:
                print(f"ตัดออก (TF-IDF: {rule_result.score})")
                results.append(rule_result)
                continue

            # ── ด่านที่ 2: Groq AI ───────────────────────────
            print(f"TF-IDF: {rule_result.score} → AI...", end=" ", flush=True)
            ai_result = self.ai_analyzer.analyze(jd_text, path)
            ai_count += 1

            if not ai_result.error:
                # รวมคะแนน: TF-IDF 40% + AI 60%
                combined = round(
                    rule_result.score * 0.40 +
                    ai_result.score   * 0.60, 1
                )
                ai_result.score = combined

                # ตัดสิน recommendation ใหม่จากคะแนนรวม
                c = self.config
                if combined >= c.pass_threshold:
                    ai_result.recommendation = "ผ่าน"
                elif combined >= c.review_threshold:
                    ai_result.recommendation = "พิจารณาเพิ่มเติม"
                else:
                    ai_result.recommendation = "ไม่ผ่าน"

                print(f"AI: {ai_result.score}")
                results.append(ai_result)
            else:
                # AI error → ใช้ผล TF-IDF แทน
                print(f"AI Error → ใช้ TF-IDF ({rule_result.score})")
                results.append(rule_result)

        # เรียงตามคะแนน
        results.sort(key=lambda r: r.score, reverse=True)

        # สรุปการใช้ AI
        saved = len(resume_paths) - ai_count
        print(f"\n  ใช้ Groq AI  : {ai_count} ไฟล์")
        print(f"  TF-IDF กรอง : {saved} ไฟล์ (ประหยัด API)")
        return results

    def print_results(self, results: list):
        """แสดงผลลัพธ์ พร้อมข้อมูลเพิ่มเติมจาก AI"""
        self.rule_screener.print_results(results)

        # แสดง AI insights
        print(f"\n{'='*55}")
        print("  AI Insights (จาก Groq)")
        print(f"{'='*55}")
        for r in results:
            if r.struct_checks and r.struct_checks.get("summary"):
                print(f"\n{r.name}:")
                print(f"  สรุป     : {r.struct_checks['summary']}")
                if r.struct_checks.get("matched_skills"):
                    print(f"  ตรงกับ JD: {', '.join(r.struct_checks['matched_skills'][:5])}")
                if r.struct_checks.get("missing_skills"):
                    print(f"  ขาด      : {', '.join(r.struct_checks['missing_skills'][:3])}")

    def save_json(self, results: list, output: str = "results_hybrid.json"):
        self.rule_screener.save_json(results, output)


# ============================================================
#  รันทดสอบโดยตรง: python ai_analyzer.py
# ============================================================

if __name__ == "__main__":
    import os, sys
    sys.path.append(".")

    print("=" * 55)
    print("  ทดสอบ Groq AI Analyzer")
    print("=" * 55)

    API_KEY = input("  Groq API Key (gsk_...): ").strip()
    if not API_KEY.startswith("gsk_"):
        print("  ✗ key ต้องขึ้นต้นด้วย gsk_")
        sys.exit(1)

    JD_FILE      = input("  ไฟล์ JD [job_description_frontend.txt]: ").strip() \
                   or "job_description_frontend.txt"
    RESUME_FILES = input(
        "  ไฟล์ Resume (คั่นช่องว่าง): "
    ).strip().split()

    if not RESUME_FILES:
        print("  ✗ กรุณาใส่ไฟล์อย่างน้อย 1 ไฟล์")
        sys.exit(1)

    config   = Config(pass_threshold=55, review_threshold=35)
    screener = HybridScreener(
        config=config,
        api_key=API_KEY,
        model="llama-3.1-8b-instant",
    )

    results = screener.screen(
        jd_path=JD_FILE,
        resume_paths=RESUME_FILES,
        ai_threshold=30,
    )

    screener.print_results(results)
    screener.save_json(results, output="results_hybrid.json")