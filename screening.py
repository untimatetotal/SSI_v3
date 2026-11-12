# ============================================================
# screening.py — ให้คะแนนผู้สมัครจากข้อมูลที่ resume_parser สกัดไว้
#   Keyword 60 (เฉพาะหมวดที่ตั้งเงื่อนไข) + AI 25 + ความครบถ้วนของข้อมูล 15 (+ พิเศษ 15)
#   ทุกหมวดเก็บหลักฐานจากใบสมัคร และแยกเหตุผล "ไม่ผ่าน" กับ "ต้องตรวจสอบ"
# ============================================================

import math
from pathlib import Path

from lexicon import expand_term, LEVEL_LABEL
from thai_text import MatchText


def fmt_months(months):
    if months is None:
        return "ไม่ระบุ"
    years, rem = divmod(int(months), 12)
    if years and rem:
        return f"{years} ปี {rem} เดือน"
    if years:
        return f"{years} ปี"
    return f"{rem} เดือน"


class Matcher:
    def __init__(self, parsed: dict):
        p = parsed.get("profile") or {}
        extra = []
        for key in ("skills", "certifications", "job_titles", "desired_positions", "fields_of_study"):
            extra.extend(str(x) for x in (p.get(key) or []))
        for j in p.get("jobs") or []:
            if isinstance(j, dict):
                extra.append(f"{j.get('title', '')} {j.get('summary', '')}")
        for e in p.get("education") or []:
            if isinstance(e, dict):
                extra.append(f"{e.get('degree', '')} {e.get('field_of_study', '')} {e.get('institution', '')}")
        self.doc = MatchText((parsed.get("text") or "") + "\n" + "\n".join(extra))

    def find(self, term: str):
        """คืน (คำที่ตรง, หลักฐาน) โดยลองคำพ้องด้วย — "ไทย / English" นับเป็นข้อกำหนดเดียว"""
        for alt in [a.strip() for a in str(term).split(" / ") if a.strip()]:
            for t in expand_term(alt):
                snippet = self.doc.find(t)
                if snippet:
                    return t, snippet
        return None, None

    def coverage(self, terms):
        hits = []
        for term in terms:
            t, snippet = self.find(term)
            if snippet:
                hits.append((term, t, snippet))
        return hits


AI_WEIGHTS = {"positions": 4, "duties": 8, "skills": 9, "fields_of_study": 4}
AI_ANY_HIT = ("positions", "fields_of_study")


def ai_requirement_score(matcher, master):
    """คะแนน AI 25: ตำแหน่ง/สาขาตรง 1 ข้อได้เต็มหมวด, หน้าที่/ทักษะตรงครึ่งหนึ่งของรายการได้เต็มหมวด"""
    if not master:
        return 0.0, []
    groups = master if isinstance(master, dict) else {"skills": list(master)}
    earned = total = 0.0
    names = []
    for key, terms in groups.items():
        terms = [t for t in terms or [] if str(t).strip()]
        if not terms:
            continue
        weight = AI_WEIGHTS.get(key, 5)
        hits = matcher.coverage(terms)
        need = 1 if key in AI_ANY_HIT else max(1, math.ceil(len(terms) * 0.5))
        earned += weight * min(1.0, len(hits) / need)
        total += weight
        names.extend(h[1] for h in hits)
    return (round(earned / total * 25, 1) if total else 0.0), names


def related_experience_months(profile: dict, positions) -> "int | None":
    """เดือนประสบการณ์ที่ตำแหน่งงานตรงกับตำแหน่งที่ค้นหา (ไม่นับฝึกงาน) — None ถ้าไม่มีชื่อตำแหน่งให้เทียบ"""
    jobs = [j for j in (profile.get("jobs") or []) if isinstance(j, dict) and j.get("title")]
    if not positions or not jobs:
        return None
    from thai_text import merge_month_spans
    spans = []
    for j in jobs:
        if j.get("internship") or not j.get("months") or not j.get("start") or not j.get("end"):
            continue
        doc = MatchText(f"{j.get('title', '')}\n{j.get('summary', '')}")
        if any(doc.find(t) for term in positions for t in expand_term(term)):
            spans.append((tuple(j["start"]), tuple(j["end"])))
    return merge_month_spans(spans) if spans else 0


def score_candidate(parsed: dict, config, file_name: str) -> dict:
    p = parsed.get("profile") or {}
    meta = parsed.get("meta") or {}
    stem = Path(file_name).stem
    base = {
        "name": p.get("name") or stem, "file": file_name, "score": 0.0, "recommendation": "ไม่ผ่าน",
        "keyword_score": 0.0, "ai_score": 0.0, "struct_score": 0.0, "special_score": 0.0,
        "experience": "ไม่ระบุ", "experience_months": None, "related_experience_months": None,
        "gpa": None, "age": None, "gender": None, "salary_expectation": None,
        "vehicle_status": {}, "language_scores": {}, "keyword_breakdown": {}, "missing_keywords": [],
        "reject_reasons": [], "review_reasons": [], "evidence": {}, "struct_checks": {},
        "degree_label": None, "read_method": meta.get("method"), "ai_summary": None, "error": None,
    }
    if not (parsed.get("text") or "").strip():
        base["error"] = "อ่านข้อความจากไฟล์ไม่ได้ (อาจเป็นภาพสแกนที่ OCR อ่านไม่สำเร็จ)"
        base["reject_reasons"] = ["อ่านไฟล์ไม่ได้ ต้องตรวจสอบด้วยตนเอง"]
        return base

    c = config
    m = Matcher(parsed)
    breakdown, missing, evidence = {}, [], {}
    earned = active_max = 0.0

    def record(label, points, fraction, ev=None):
        nonlocal earned, active_max
        active_max += points
        got = round(points * max(0.0, min(1.0, fraction)), 2)
        earned += got
        breakdown[label] = got
        if fraction < 1:
            missing.append(label)
        if ev:
            evidence[label] = ev

    if c.position_keywords:
        hits = m.coverage(c.position_keywords)
        record("ตำแหน่งงาน", 10, 1.0 if hits else 0.0, hits and f"{hits[0][1]}: {hits[0][2]}")
    for label, terms, points in (("ลักษณะงาน", c.duties_keywords, 10), ("ทักษะ", c.skill_keywords, 8),
                                 ("คำค้นอื่น", c.general_keywords, 5)):
        if terms:
            hits = m.coverage(terms)
            record(label, points, len(hits) / len(terms),
                   "; ".join(f"{h[1]}: {h[2]}" for h in hits[:3]) if hits else None)

    total_months = p.get("experience_months")
    related = related_experience_months(p, c.position_keywords)
    exp_for_rule = related if related is not None else total_months
    if c.min_experience_years is not None:
        ok = exp_for_rule is not None and exp_for_rule >= c.min_experience_years * 12
        label_txt = "ประสบการณ์ตรงสาย" if related is not None else "ประสบการณ์"
        record("ประสบการณ์", 6, 1.0 if ok else 0.0, f"{label_txt} {fmt_months(exp_for_rule)}" if exp_for_rule is not None else None)

    if c.field_of_study_keywords:
        hits = m.coverage(c.field_of_study_keywords)
        record("สาขาวิชา", 8, 1.0 if hits else 0.0, hits and f"{hits[0][1]}: {hits[0][2]}")

    gpa = p.get("gpa")
    if c.min_gpa is not None:
        record("GPA", 6, 1.0 if gpa is not None and gpa >= c.min_gpa else 0.0, p.get("gpa_evidence"))

    level = p.get("highest_degree_level")
    if getattr(c, "min_edu_level", None) is not None:
        ok = level is not None and level >= c.min_edu_level
        record("วุฒิการศึกษา", 2, 1.0 if ok else 0.0, LEVEL_LABEL.get(level))

    age = p.get("age")
    if c.age_range is not None:
        lo, hi = c.age_range
        record("อายุ", 2, 1.0 if age is not None and lo <= age <= hi else 0.0, f"อายุ {age} ปี" if age else None)
    if c.gender is not None:
        record("เพศ", 2, 1.0 if p.get("gender") == c.gender else 0.0)
    salary = p.get("salary_expectation")
    if c.salary_range is not None:
        lo, hi = c.salary_range
        record("เงินเดือน", 2, 1.0 if salary is not None and lo <= salary <= hi else 0.0,
               f"คาดหวัง {salary:,.0f} บาท" if salary else None)

    keyword_score = round(earned / active_max * 60, 2) if active_max else 0.0
    if p.get("hr_fields"):
        evidence["ข้อมูลจาก HR"] = ", ".join(p["hr_fields"])

    ai_score, ai_hits = ai_requirement_score(m, c.ai_keyword_masterlist)
    if ai_hits:
        evidence["AI: ข้อกำหนดจาก JD"] = ", ".join(ai_hits[:8])

    checks = {
        "พบข้อมูลการศึกษา": bool(p.get("education")) or level is not None,
        "พบประวัติการทำงาน": bool(p.get("jobs")) or total_months is not None,
        "พบทักษะ": bool(p.get("skills")) or "ทักษะ" in parsed.get("text", "") or "skill" in parsed.get("text", "").lower(),
        "พบ GPA": gpa is not None,
        "พบชื่อผู้สมัคร": bool(p.get("name")),
        "อ่านข้อความได้ชัดเจน": meta.get("method") == "text" and (meta.get("quality") or 0) >= 0.85,
    }
    weights = {"พบข้อมูลการศึกษา": 3, "พบประวัติการทำงาน": 3, "พบทักษะ": 3,
               "พบ GPA": 2, "พบชื่อผู้สมัคร": 2, "อ่านข้อความได้ชัดเจน": 2}
    struct_score = float(sum(weights[k] for k, v in checks.items() if v))

    special = 0.0
    vehicle = p.get("vehicle") or {}
    langs = p.get("languages") or {}
    if c.enable_special_score:
        if (not c.require_vehicle or vehicle.get("has_vehicle")) and (not c.require_license or vehicle.get("has_license")):
            special += 5
        if c.min_toeic_score is None or (langs.get("TOEIC") is not None and langs["TOEIC"] >= c.min_toeic_score):
            special += 10

    reject, review = [], []
    if c.min_gpa is not None:
        if gpa is None:
            review.append(f"ไม่พบ GPA ในใบสมัคร ต้องตรวจสอบ (เกณฑ์ {c.min_gpa:.2f})")
        elif gpa < c.min_gpa:
            reject.append(f"GPA {gpa:.2f} ต่ำกว่าเกณฑ์ขั้นต่ำ {c.min_gpa:.2f}")
    if c.min_experience_years is not None:
        need = c.min_experience_years * 12
        if exp_for_rule is None:
            review.append(f"ไม่พบระยะเวลาประสบการณ์ ต้องตรวจสอบ (เกณฑ์ {c.min_experience_years:g} ปี)")
        elif exp_for_rule < need:
            kind = "ประสบการณ์ตรงสาย" if related is not None else "ประสบการณ์"
            extra = f" (ประสบการณ์รวม {fmt_months(total_months)})" if related is not None and total_months and total_months != related else ""
            reject.append(f"{kind} {fmt_months(exp_for_rule)} ต่ำกว่าเกณฑ์ขั้นต่ำ {c.min_experience_years:g} ปี{extra}")
    if c.age_range is not None:
        lo, hi = c.age_range
        if age is None:
            review.append(f"ไม่พบอายุในใบสมัคร ต้องตรวจสอบ (เกณฑ์ {lo}-{hi} ปี)")
        elif not lo <= age <= hi:
            reject.append(f"อายุ {age} ปี อยู่นอกช่วงที่กำหนด {lo}-{hi} ปี")
    if meta.get("method") == "ocr":
        review.append("ไฟล์เป็นภาพสแกน ข้อมูลที่อ่านได้อาจคลาดเคลื่อน")

    total = round(keyword_score + ai_score + struct_score + special, 1)
    if reject:
        rec = "ไม่ผ่าน"
    elif total >= c.pass_threshold:
        rec = "พิจารณาเพิ่มเติม" if review else "ผ่าน"
    elif total >= c.review_threshold:
        rec = "พิจารณาเพิ่มเติม"
    else:
        rec = "ไม่ผ่าน"

    base.update({
        "score": total, "recommendation": rec,
        "keyword_score": round(keyword_score, 1), "ai_score": ai_score,
        "struct_score": struct_score, "special_score": special,
        "experience": fmt_months(total_months) if total_months is not None else "ไม่ระบุ",
        "experience_months": total_months, "related_experience_months": related,
        "gpa": gpa, "age": age, "gender": p.get("gender"), "salary_expectation": salary,
        "vehicle_status": vehicle, "language_scores": langs,
        "keyword_breakdown": breakdown, "missing_keywords": missing,
        "reject_reasons": reject, "review_reasons": review, "evidence": evidence,
        "struct_checks": checks, "degree_label": LEVEL_LABEL.get(level),
    })
    return base


def sort_results(results):
    return sorted(results, key=lambda r: (bool(r.get("reject_reasons")), -float(r.get("score") or 0)))


SUMMARY_SYSTEM = (
    "You help an HR officer at a Thai steel company review shortlisted candidates. For each candidate you get "
    "structured resume data and the job requirements. Respond ONLY with JSON: "
    '{"candidates": [{"file": string, "strengths": [string], "concerns": [string], "interview_questions": [string]}]}. '
    "Write in Thai, at most 3 short items per list, based only on the data given. Do not mention gender, age, "
    "religion or appearance."
)


def ai_summaries(llm, results, parsed_by_file, requirements_text, top_n=5):
    """ให้ AI สรุปจุดเด่น/ข้อกังวล/คำถามสัมภาษณ์ เฉพาะผู้ที่ไม่ถูกตัดตก อันดับต้น ๆ"""
    shortlist = [r for r in results if not r.get("reject_reasons") and not r.get("error")][:top_n]
    if not shortlist:
        return
    rows = []
    for r in shortlist:
        p = (parsed_by_file.get(r["file"]) or {}).get("profile") or {}
        rows.append({
            "file": r["file"], "score": r["score"], "degree": r.get("degree_label"), "gpa": r.get("gpa"),
            "experience": r.get("experience"), "related_experience": fmt_months(r.get("related_experience_months")),
            "job_titles": (p.get("job_titles") or [])[:6], "skills": (p.get("skills") or [])[:20],
            "fields_of_study": p.get("fields_of_study") or [], "missing": r.get("missing_keywords"),
        })
    import json
    user = f"Job requirements:\n{requirements_text[:2500]}\n\nCandidates:\n{json.dumps(rows, ensure_ascii=False)}"
    data = llm.chat_json(SUMMARY_SYSTEM, user, max_tokens=2500)
    by_file = {c.get("file"): c for c in (data.get("candidates") or []) if isinstance(c, dict)}
    for r in shortlist:
        s = by_file.get(r["file"])
        if s:
            r["ai_summary"] = {k: [str(x) for x in (s.get(k) or [])][:3]
                               for k in ("strengths", "concerns", "interview_questions")}
