# ============================================================
# requirements_ai.py — แปลง JD/JS หรือเงื่อนไขที่กรอก เป็นข้อกำหนดตำแหน่ง (ให้ HR ตรวจก่อนใช้)
# ============================================================

from llm import mask_pii

JD_SYSTEM = (
    "You turn a job description (Thai, English or mixed) into screening requirements for a Thai company. "
    "Respond ONLY with JSON: "
    '{"positions": [string], "duties": [string], "skills": [string], "fields_of_study": [string], '
    '"min_experience_years": number|null, "min_degree": "vocational"|"bachelor"|"master"|"doctorate"|null, '
    '"min_gpa": number|null, "summary": string}. '
    "positions: up to 5 job titles. duties: up to 8 main responsibilities. skills: up to 12 required skills, tools "
    "or certifications. fields_of_study: up to 5. Each item is a short keyword of 1-3 words that would appear in a "
    "resume. When the source is Thai, or the term has a common Thai equivalent used in Thai resumes, give the Thai "
    "and the English form as two separate items. Use null when not stated; never invent requirements. "
    "summary: one Thai sentence describing the role. Never include age, gender, religion or appearance requirements."
)
DEGREE_LEVEL = {"vocational": 1, "bachelor": 2, "master": 3, "doctorate": 4}


def _clean(values, limit):
    out, seen = [], set()
    for v in values or []:
        s = str(v).strip()
        if s and s.lower() not in seen and len(s) <= 60:
            seen.add(s.lower())
            out.append(s)
    return out[:limit]


def extract_requirements(llm, text: str) -> dict:
    data = llm.chat_json(JD_SYSTEM, mask_pii(text)[:6000], max_tokens=1800)
    if not isinstance(data, dict):
        data = {}

    def num(v, lo, hi):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return v if lo <= v <= hi else None

    req = {
        "positions": _clean(data.get("positions"), 10),
        "duties": _clean(data.get("duties"), 16),
        "skills": _clean(data.get("skills"), 24),
        "fields_of_study": _clean(data.get("fields_of_study"), 10),
        "min_experience_years": num(data.get("min_experience_years"), 0, 40),
        "min_degree_level": DEGREE_LEVEL.get(str(data.get("min_degree") or "").lower()),
        "min_gpa": num(data.get("min_gpa"), 0, 4),
        "summary": str(data.get("summary") or "")[:300],
    }
    req["all_terms"] = _clean(req["positions"] + req["duties"] + req["skills"] + req["fields_of_study"], 40)
    return req
