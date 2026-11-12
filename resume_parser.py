# ============================================================
# resume_parser.py — อ่านไฟล์ใบสมัครเป็นข้อมูลมีโครงสร้าง
#   1) อ่านข้อความตามคอลัมน์ + ปรับข้อความไทย + OCR เมื่อจำเป็น
#   2) ดึงข้อมูลด้วยกฎ (ใช้ได้เสมอ แม้ไม่มี AI)
#   3) ถ้ามี AI ให้สกัดเป็น JSON แล้วตรวจค่าด้วยโค้ดอีกชั้น
# ============================================================

import io
import platform
import re
from datetime import date

import fitz

from lexicon import degree_level, LEVEL_LABEL
from llm import LLMError, mask_pii
from thai_text import (normalize_text, fix_ocr_thai, text_quality, find_date_ranges, merge_month_spans,
                       months_between, parse_birthdate, age_on, to_ce_year, has_thai)

PARSER_VERSION = 6
MIN_TEXT_CHARS = 80
MIN_QUALITY = 0.85


# ── 1. อ่านข้อความ ────────────────────────────────────────────

def _page_text_by_columns(page) -> str:
    blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
    if len(blocks) < 4:
        return "\n".join(b[4] for b in sorted(blocks, key=lambda b: (b[1], b[0])))
    width = page.rect.width
    best_x, best_cross = None, None
    for x in range(int(width * 0.25), int(width * 0.75), 4):
        cross = sum(1 for b in blocks if b[0] < x < b[2])
        left = sum(1 for b in blocks if b[2] <= x)
        right = sum(1 for b in blocks if b[0] >= x)
        if left >= 2 and right >= 2 and (best_cross is None or cross < best_cross):
            best_x, best_cross = x, cross
    if best_x is None or best_cross > max(1, len(blocks) * 0.15):
        return "\n".join(b[4] for b in sorted(blocks, key=lambda b: (b[1], b[0])))
    full = [b for b in blocks if b[0] < best_x < b[2]]
    left = sorted((b for b in blocks if b[2] <= best_x), key=lambda b: b[1])
    right = sorted((b for b in blocks if b[0] >= best_x), key=lambda b: b[1])
    column_top = min(b[1] for b in left + right)
    head = sorted((b for b in full if b[1] < column_top), key=lambda b: b[1])
    tail = sorted((b for b in full if b[1] >= column_top), key=lambda b: b[1])
    return "\n".join(b[4] for b in head + left + right + tail)


def _largest_text(page):
    """ข้อความที่ฟอนต์ใหญ่ที่สุดบนหน้าแรก (มักเป็นชื่อ) — คืน None ถ้าไม่ใหญ่กว่าตัวอื่นชัดเจน"""
    sizes, spans = [], []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(sp["text"] for sp in line.get("spans", [])).strip()
            if text:
                size = max(sp["size"] for sp in line["spans"])
                sizes.append(size)
                spans.append((size, line["bbox"][1], text))
    if len(sizes) < 3:
        return None
    sizes.sort()
    median = sizes[len(sizes) // 2]
    top = max(spans, key=lambda x: (x[0], -x[1]))
    return normalize_text(top[2]) if top[0] >= median * 1.4 else None


def _ocr(path: str) -> str:
    try:
        import pytesseract
        from PIL import Image, ImageOps
        if platform.system() == "Windows":
            pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        doc = fitz.open(path)
        texts = []
        for page in doc:
            pix = page.get_pixmap(dpi=300)
            img = ImageOps.autocontrast(Image.open(io.BytesIO(pix.tobytes("png"))).convert("L"))
            texts.append(pytesseract.image_to_string(img, lang="tha+eng", config="--psm 3"))
        doc.close()
        return "\n".join(texts)
    except Exception as e:
        print(f"[warn] OCR failed for {path}: {e}")
        return ""


def extract_text(path: str):
    """คืน (ข้อความที่ปรับแล้ว, meta) — meta บอกวิธีอ่านและคุณภาพ"""
    raw = ""
    if str(path).lower().endswith(".txt"):
        with open(path, encoding="utf-8", errors="ignore") as f:
            raw = f.read()
        return normalize_text(raw), {"method": "text", "quality": 1.0}
    title_line = None
    try:
        doc = fitz.open(path)
        raw = "\n".join(_page_text_by_columns(p) for p in doc)
        if len(doc):
            title_line = _largest_text(doc[0])
        doc.close()
    except Exception as e:
        print(f"[warn] open PDF failed for {path}: {e}")
        return "", {"method": "error", "quality": 0.0}
    quality = text_quality(raw)
    text = normalize_text(raw)
    meta = {"method": "text", "quality": round(quality, 3), "title_line": title_line}
    if len(text) < MIN_TEXT_CHARS or quality < MIN_QUALITY:
        ocr_raw = _ocr(path)
        ocr_text = fix_ocr_thai(normalize_text(ocr_raw))
        if len(ocr_text) > len(text) * 0.6 and len(ocr_text) >= MIN_TEXT_CHARS:
            return ocr_text, {"method": "ocr", "quality": round(text_quality(ocr_raw), 3),
                              "text_quality_before_ocr": round(quality, 3)}
    return text, meta


# ── 2. ดึงข้อมูลด้วยกฎ ────────────────────────────────────────

SECTION_PATTERNS = {
    "experience": r"work experience|experience|employment|internship|work history|ประวัติการทำงาน|ประสบการณ์การทำงาน|ประสบการณ์ทำงาน|ประสบการณ์|การฝึกงาน|ฝึกงาน",
    "education": r"education|educational background|academic|ประวัติการศึกษา|การศึกษา|วุฒิการศึกษา",
    "skills": r"skills?|technical skills|ทักษะ|ความสามารถ|ความสามารถพิเศษ",
    "other": r"projects?|certifications?|training|languages?|achievements?|awards?|activities|references?|personal (?:details|profile|information)|profile|summary|contact|objective|about me|โครงการ|โครงงาน|ใบรับรอง|การอบรม|ภาษา|กิจกรรม|ผลงาน|บุคคลอ้างอิง|ข้อมูลส่วนตัว|ประวัติส่วนตัว|เกี่ยวกับฉัน|ช่องทางการติดต่อ|ติดต่อ|จุดมุ่งหมาย",
}
_HEADING = [(name, re.compile(rf"^\W*(?:{p})(?:[\W_].{{0,28}})?$", re.IGNORECASE)) for name, p in SECTION_PATTERNS.items()]


def split_sections(text: str) -> dict:
    sections = {"_top": []}
    current = "_top"
    for line in text.split("\n"):
        stripped = line.strip()
        if 0 < len(stripped) <= 45 and not re.search(r"\d", stripped):
            for name, rx in _HEADING:
                if rx.match(stripped):
                    current = name
                    sections.setdefault(current, [])
                    break
            else:
                sections.setdefault(current, []).append(stripped)
                continue
            continue
        sections.setdefault(current, []).append(stripped)
    return {k: "\n".join(v) for k, v in sections.items()}


GPA_RE = re.compile(
    r"(?:gpax|cum(?:ulative)?\.?\s*gpa|gpa|g\.p\.a\.?|เกรดเฉลี่ยสะสม|เกรดเฉลี่ย|คะแนนเฉลี่ยสะสม|เกรด)"
    r"[^\d\n]{0,25}?([0-4][.,]\d{1,2})"
    r"|([0-4][.,]\d{2})\s*/\s*4(?:[.,]0{1,2})?",
    re.IGNORECASE,
)


def find_gpa(text: str):
    """GPA ของวุฒิสูงสุด — เลือกจากบริบทรอบตัวเลข แล้วคืน (gpa, ระดับวุฒิ, หลักฐาน)"""
    best = None
    for m in GPA_RE.finditer(text):
        value = float((m.group(1) or m.group(2)).replace(",", "."))
        if not 0 < value <= 4:
            continue
        before = text[max(0, m.start() - 220):m.start()]
        after = text[m.end():m.end() + 40]
        level = _nearest_degree(before, after)
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        evidence = text[line_start:line_end if line_end > 0 else len(text)].strip()[:140]
        key = (level if level is not None else 1.5)
        if best is None or key > best[0]:
            best = (key, value, level, evidence)
    if not best:
        return None, None, None
    return best[1], best[2], best[3]


def _nearest_degree(before: str, after: str):
    same_line_after = after.split("\n", 1)[0]
    lines = [ln for ln in before.split("\n") if ln.strip()][-4:]
    if lines:
        lines[-1] = lines[-1] + " " + same_line_after
    else:
        lines = [same_line_after]
    for ln in reversed(lines):
        level = degree_level(ln)
        if level is not None:
            return level
    return None


INTERN_RE = re.compile(r"intern|ฝึกงาน|สหกิจ|trainee|co-?op", re.IGNORECASE)
YEARS_RE = re.compile(
    r"(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?|ปี)\s*(?:of\s*)?(?:work(?:ing)?\s*)?(?:experience|ประสบการณ์)"
    r"|(?:experience|ประสบการณ์(?:การทำงาน)?)\s*[:\-]?\s*(\d{1,2}(?:\.\d)?)\s*(?:years?|yrs?|ปี)",
    re.IGNORECASE,
)


def find_experience(sections: dict, full_text: str, today=None):
    """คืน dict: months (งานจริง), internship_months, jobs (ช่วงที่พบ), source"""
    exp_text = sections.get("experience", "")
    jobs, spans, intern_spans = [], [], []
    if exp_text:
        for start, end, matched, pos in find_date_ranges(exp_text, today):
            line_end = exp_text.find("\n", pos + len(matched))
            before_lines = exp_text[:pos].split("\n")[-3:]
            context = "\n".join(before_lines) + exp_text[pos:line_end if line_end > 0 else len(exp_text)]
            is_intern = bool(INTERN_RE.search(context))
            months = months_between(start, end)
            jobs.append({"start": start, "end": end, "months": months, "internship": is_intern, "text": matched})
            (intern_spans if is_intern else spans).append((start, end))
    if jobs:
        return {"months": merge_month_spans(spans), "internship_months": merge_month_spans(intern_spans),
                "jobs": jobs, "source": "date_ranges"}
    m = YEARS_RE.search(full_text)
    if m:
        years = float(m.group(1) or m.group(2))
        return {"months": int(round(years * 12)), "internship_months": 0, "jobs": [], "source": "stated_years"}
    return {"months": None, "internship_months": None, "jobs": [], "source": None}


AGE_RE = re.compile(r"(?:อายุ|age)\s*[:：]?\s*(\d{2})\s*(?:ปี|years?|yrs?)?", re.IGNORECASE)


def find_age(text: str, today=None):
    m = AGE_RE.search(text)
    if m and 15 <= int(m.group(1)) <= 75:
        return int(m.group(1)), "stated"
    birth = parse_birthdate(text)
    if birth:
        age = age_on(birth, today)
        if age:
            return age, "birthdate"
    return None, None


def find_gender(text: str):
    t = text.lower()
    if re.search(r"เพศ\s*[:：]?\s*หญิง|gender\s*[:：]?\s*female|sex\s*[:：]?\s*female", t):
        return "female"
    if re.search(r"เพศ\s*[:：]?\s*ชาย|gender\s*[:：]?\s*male|sex\s*[:：]?\s*male", t):
        return "male"
    head = t[:300]
    if re.search(r"นางสาว|\bmiss\b|\bms\.|\bmrs\.", head):
        return "female"
    if re.search(r"(?:^|\s)นาย|\bmr\.", head):
        return "male"
    return None


SALARY_RE = re.compile(
    r"(?:expected\s+salary|salary\s+expectation|desired\s+salary|เงินเดือนที่ต้องการ|เงินเดือนที่คาดหวัง|เงินเดือน|salary)"
    r"\s*[:：]?\s*(?:฿|thb|บาท)?\s*([\d,]{4,7})",
    re.IGNORECASE,
)


def find_salary(text: str):
    m = SALARY_RE.search(text)
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return value if 5000 <= value <= 1_000_000 else None


def find_languages(text: str) -> dict:
    scores = {}
    for name, pattern in [("TOEIC", r"toeic\D{0,15}(\d{3})"),
                          ("IELTS", r"ielts\D{0,15}(\d(?:\.\d)?)"),
                          ("TOEFL", r"toefl\D{0,15}(\d{2,3})")]:
        m = re.search(pattern, text, re.IGNORECASE)
        scores[name] = float(m.group(1)) if m else None
    return scores


def find_vehicle(text: str) -> dict:
    t = text.lower()
    return {
        "has_vehicle": any(k in t for k in ["มีรถยนต์ส่วนตัว", "รถยนต์ส่วนตัว", "own car", "own vehicle", "มีรถยนต์"]),
        "has_license": any(k in t for k in ["ใบขับขี่", "driving license", "driver's license", "driving licence", "driver license"]),
    }


NAME_PREFIX = re.compile(r"^(?:นาย|นางสาว|นาง|mr\.?|ms\.?|mrs\.?|miss)\s*\S", re.IGNORECASE)


def _looks_like_name(s: str) -> bool:
    if not 4 <= len(s) <= 40 or re.search(r"[\d@:/|•]", s):
        return False
    if any(rx.match(s) for _, rx in _HEADING):
        return False
    if re.search(r"resume|curriculum|vitae|ประวัติ|engineer|วิศวกร|officer|manager|พนักงาน", s, re.IGNORECASE):
        return False
    words = s.split()
    return 2 <= len(words) <= 4 or (has_thai(s) and len(words) <= 3 and len(s) >= 6)


def find_name(text: str, hint: str = None):
    """ชื่อผู้สมัคร: คำนำหน้าชื่อ > ข้อความตัวใหญ่สุดบนหน้าแรก > บรรทัดแรก ๆ ที่หน้าตาเหมือนชื่อ (ไม่แน่ใจคืน None)"""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    for s in lines[:15]:
        if NAME_PREFIX.match(s) and len(s) <= 45 and not re.search(r"[\d@:]", s):
            return s
    if hint and _looks_like_name(hint):
        return hint
    for s in lines[:3]:
        if _looks_like_name(s):
            return s
    return None


def rule_profile(text: str, today=None, name_hint=None) -> dict:
    sections = split_sections(text)
    gpa, gpa_level, gpa_evidence = find_gpa(text)
    exp = find_experience(sections, text, today)
    age, age_source = find_age(text, today)
    edu_text = sections.get("education") or text
    return {
        "name": find_name(text, name_hint),
        "gpa": gpa, "gpa_degree_level": gpa_level, "gpa_evidence": gpa_evidence,
        "highest_degree_level": degree_level(edu_text) if degree_level(edu_text) is not None else degree_level(text),
        "experience_months": exp["months"], "internship_months": exp["internship_months"],
        "experience_source": exp["source"], "jobs": exp["jobs"],
        "age": age, "age_source": age_source,
        "gender": find_gender(text),
        "salary_expectation": find_salary(text),
        "languages": find_languages(text),
        "vehicle": find_vehicle(text),
        "education": [], "skills": [], "job_titles": [], "fields_of_study": [],
        "source": "rules",
    }


# ── 3. AI สกัดเป็น JSON ──────────────────────────────────────

AI_SYSTEM = (
    "You extract structured data from a job applicant's resume. The resume may be Thai, English or mixed, "
    "and may contain OCR errors. Respond ONLY with one JSON object with these keys:\n"
    '{"name": string|null, '
    '"education": [{"level": "high_school"|"vocational"|"bachelor"|"master"|"doctorate", "degree": string, '
    '"field_of_study": string, "institution": string, "gpa": number|null, "end_year": number|null}], '
    '"experience": [{"title": string, "company": string, "start": "YYYY-MM"|null, "end": "YYYY-MM"|"present"|null, '
    '"internship": boolean, "summary": string}], '
    '"skills": [string], "certifications": [string], '
    '"languages": {"TOEIC": number|null, "IELTS": number|null, "TOEFL": number|null}, '
    '"desired_positions": [string], "age": number|null, "birth_date": "YYYY-MM-DD"|null, '
    '"expected_salary": number|null}\n'
    "Rules: convert Buddhist Era years to Common Era by subtracting 543. Convert Thai numerals to Arabic. "
    "Use null when a value is not written in the resume; never guess. GPA is on a 4.00 scale. "
    "Write skills and titles as they appear (keep Thai if written in Thai) and add the English equivalent in parentheses when obvious. "
    "Do NOT output religion, ethnicity, nationality, health, marital status, height, weight or photos."
)
LEVEL_MAP = {"high_school": 0, "vocational": 1, "bachelor": 2, "master": 3, "doctorate": 4}


def _ym_from_str(value, today):
    if not value:
        return None
    s = str(value).strip().lower()
    if s in ("present", "current", "now", "ปัจจุบัน"):
        return (today.year, today.month)
    m = re.match(r"((?:19|20|25)\d{2})(?:-(\d{1,2}))?", s)
    if not m:
        return None
    year = to_ce_year(int(m.group(1)))
    month = int(m.group(2)) if m.group(2) and 1 <= int(m.group(2)) <= 12 else None
    if not 1970 <= year <= today.year + 1:
        return None
    return (year, month)


def ai_profile(text: str, llm, today=None) -> dict:
    today = today or date.today()
    data = llm.chat_json(AI_SYSTEM, mask_pii(text)[:7000], max_tokens=2500)
    if not isinstance(data, dict):
        raise LLMError("AI response is not an object")

    education = []
    for e in data.get("education") or []:
        if not isinstance(e, dict):
            continue
        gpa = e.get("gpa")
        try:
            gpa = float(gpa) if gpa is not None else None
        except (TypeError, ValueError):
            gpa = None
        if gpa is not None and not 0 < gpa <= 4:
            gpa = None
        education.append({
            "level": LEVEL_MAP.get(str(e.get("level", "")).lower()),
            "degree": e.get("degree") or "", "field_of_study": e.get("field_of_study") or "",
            "institution": e.get("institution") or "", "gpa": gpa, "end_year": e.get("end_year"),
        })

    jobs, spans, intern_spans = [], [], []
    for j in data.get("experience") or []:
        if not isinstance(j, dict):
            continue
        start, end = _ym_from_str(j.get("start"), today), _ym_from_str(j.get("end"), today)
        months = months_between(start, end) if start and end and (start <= end) else None
        intern = bool(j.get("internship")) or bool(INTERN_RE.search(f"{j.get('title', '')} {j.get('summary', '')}"))
        jobs.append({"title": j.get("title") or "", "company": j.get("company") or "",
                     "start": start, "end": end, "months": months, "internship": intern,
                     "summary": (j.get("summary") or "")[:300]})
        if months:
            (intern_spans if intern else spans).append((start, end))

    def num(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    age = num(data.get("age"))
    birth = data.get("birth_date")
    if age is None and birth:
        m = re.match(r"((?:19|20|25)\d{2})-(\d{1,2})-(\d{1,2})", str(birth))
        if m:
            try:
                age = age_on(date(to_ce_year(int(m.group(1))), int(m.group(2)), int(m.group(3))), today)
            except ValueError:
                age = None
    if age is not None and not 15 <= age <= 75:
        age = None

    langs = data.get("languages") if isinstance(data.get("languages"), dict) else {}
    return {
        "name": data.get("name"),
        "education": education,
        "jobs": jobs,
        "experience_months": merge_month_spans(spans) if spans else (0 if jobs else None),
        "internship_months": merge_month_spans(intern_spans) if intern_spans else (0 if jobs else None),
        "skills": [str(s) for s in (data.get("skills") or []) if s][:60],
        "certifications": [str(s) for s in (data.get("certifications") or []) if s][:30],
        "languages": {k: num(langs.get(k)) for k in ("TOEIC", "IELTS", "TOEFL")},
        "desired_positions": [str(s) for s in (data.get("desired_positions") or []) if s][:10],
        "age": int(age) if age is not None else None,
        "salary_expectation": num(data.get("expected_salary")),
    }


def merge_profiles(rules: dict, ai: dict) -> dict:
    """ใช้ค่าจาก AI เมื่อผ่านการตรวจ ส่วนที่ AI ไม่มีใช้ค่าจากกฎ"""
    p = dict(rules)
    p["source"] = "ai"
    p["education"] = ai["education"]
    edus = [e for e in ai["education"] if e.get("level") is not None]
    if edus:
        top = max(edus, key=lambda e: e["level"])
        p["highest_degree_level"] = top["level"]
        top_gpa = next((e["gpa"] for e in sorted(edus, key=lambda e: -e["level"]) if e.get("gpa") is not None), None)
        if top_gpa is not None:
            p["gpa"], p["gpa_degree_level"] = top_gpa, top["level"] if top.get("gpa") is not None else p.get("gpa_degree_level")
            p["gpa_evidence"] = rules.get("gpa_evidence") if rules.get("gpa") == top_gpa else f"AI: GPA {top_gpa:.2f}"
    p["fields_of_study"] = [e["field_of_study"] for e in ai["education"] if e.get("field_of_study")]
    if ai["jobs"]:
        p["jobs"] = ai["jobs"]
        p["experience_months"] = ai["experience_months"]
        p["internship_months"] = ai["internship_months"]
        p["experience_source"] = "ai_date_ranges"
    for key in ("skills", "certifications", "desired_positions"):
        p[key] = ai.get(key) or p.get(key) or []
    p["job_titles"] = [j["title"] for j in ai["jobs"] if j.get("title")]
    for key in ("name", "age", "salary_expectation"):
        if ai.get(key) is not None:
            p[key] = ai[key]
            if key == "age":
                p["age_source"] = "ai"
    for k, v in (ai.get("languages") or {}).items():
        if v is not None:
            p["languages"][k] = v
    return p


def parse_resume(path: str, llm=None, today=None) -> dict:
    """อ่านไฟล์ → {text, meta, profile} (profile ใช้กฎเสมอ และเสริมด้วย AI เมื่อมี llm)"""
    text, meta = extract_text(path)
    profile = rule_profile(text or "", today, meta.get("title_line"))
    meta["ai_error"] = None
    if llm is not None and text:
        try:
            profile = merge_profiles(profile, ai_profile(text, llm, today))
        except Exception as e:
            meta["ai_error"] = str(e)[:200]
            print(f"[warn] AI resume extraction failed: {e}")
    profile["parser_version"] = PARSER_VERSION
    profile["degree_label"] = LEVEL_LABEL.get(profile.get("highest_degree_level"))
    return {"text": text, "meta": meta, "profile": profile}
