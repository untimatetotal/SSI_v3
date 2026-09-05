# ============================================================
# models.py — CVScreener scoring engine (CVS-REQ-001)
# ============================================================
# v2: เพิ่ม extraction สำหรับ FR-3.6 (อายุ), FR-3.10 (เพศ),
#     FR-3.11 (เงินเดือน), FR-3.13 (ยานพาหนะ/ใบขับขี่),
#     FR-3.14 (ภาษา) — เติมจุดที่เคย TODO ไว้ในเวอร์ชันก่อน
# ============================================================

import re
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

try:
    import fitz
except ImportError:
    raise ImportError("please install : python -m pip install pymupdf")


# ============================================================
# Extraction functions (FR-3.x)
# ============================================================

def extract_gpa(text: str) -> Optional[float]:
    """FR-3.12"""
    patterns = [
        r'gpa\s*[:\s]\s*(\d+\.\d+)',
        r'เกรดเฉลี่ย\s*[:\s]\s*(\d+\.\d+)',
        r'เกรด\s*[:\s]\s*(\d+\.\d+)',
        r'(\d+\.\d+)\s*/\s*4\.0',
        r'cumulative\s+gpa\s*[:\s]\s*(\d+\.\d+)',
    ]
    text_lower = text.lower()
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            gpa = float(match.group(1))
            if 0.0 <= gpa <= 4.0:
                return gpa
    return None


def extract_experience_years(text: str) -> Optional[float]:
    """FR-3.7"""
    for p in [r'(\d+)\s*\+?\s*years?\s*(?:of\s*)?experience',
              r'experience\s*:?\s*(\d+)\s*years?',
              r'(\d+)\s*ปี']:
        m = re.search(p, text)
        if m:
            return float(m.group(1))
    return None


def extract_age(text: str) -> Optional[int]:
    """
    FR-3.6 — ดึงอายุจาก resume
    รองรับ 2 รูปแบบ: (1) ระบุอายุตรงๆ "อายุ 25 ปี" / "age: 25"
                     (2) คำนวณจากปีเกิด "เกิด พ.ศ. 2541" / "born 1998"
    ⚠️ ความแม่นยำจำกัด — resume จำนวนมากไม่ระบุอายุตรงๆ ตามกฎหมายคุ้มครอง
    ข้อมูลส่วนบุคคล ให้ผล None บ่อยเป็นเรื่องปกติ ไม่ใช่ bug
    """
    # แบบที่ 1: ระบุอายุตรงๆ
    patterns_direct = [
        r'อายุ\s*[:\s]?\s*(\d{1,2})\s*ปี',
        r'age\s*[:\s]\s*(\d{1,2})\b',
    ]
    for p in patterns_direct:
        m = re.search(p, text)
        if m:
            age = int(m.group(1))
            if 15 <= age <= 70:  # กรองค่าที่ไม่สมเหตุสมผล (กันไปจับเลขอื่น)
                return age

    # แบบที่ 2: คำนวณจากปีเกิด (พ.ศ. หรือ ค.ศ.)
    from datetime import date
    current_year_ad = date.today().year
    m = re.search(r'เกิด(?:วันที่)?.{0,15}?(\d{4})', text)
    if m:
        year = int(m.group(1))
        if year > 2400:  # เป็น พ.ศ. แปลงเป็น ค.ศ.
            year -= 543
        age = current_year_ad - year
        if 15 <= age <= 70:
            return age

    m = re.search(r'born\s*[:\s]?\s*(\d{4})', text)
    if m:
        age = current_year_ad - int(m.group(1))
        if 15 <= age <= 70:
            return age

    return None


def extract_gender(text: str) -> Optional[str]:
    """
    FR-3.10 — ดึงเพศจาก resume คืนค่า "male" / "female" / None
    ใช้คำนำหน้าชื่อและคำระบุเพศตรงๆ เป็นหลัก
    ⚠️ เป็นการเดาจากข้อความ ไม่ใช่ข้อมูลที่ยืนยันแล้ว ควรใช้ระมัดระวัง
    และเปิดให้ HR ตรวจสอบซ้ำเสมอ ไม่ควรใช้ตัดสิทธิ์อัตโนมัติ 100%
    """
    female_markers = ['เพศหญิง', 'นางสาว', 'นาง ', 'miss ', 'mrs.', 'ms.', 'female']
    male_markers   = ['เพศชาย', 'นาย ', 'mr.', 'male']

    for m in female_markers:
        if m in text:
            return "female"
    for m in male_markers:
        if m in text:
            return "male"
    return None


def extract_salary_expectation(text: str) -> Optional[float]:
    """
    FR-3.11 — ดึงเงินเดือนที่คาดหวังจาก resume (ถ้าระบุไว้)
    ⚠️ resume ส่วนใหญ่ไม่ระบุเงินเดือนคาดหวัง มักอยู่ใน cover letter
    หรือฟอร์มสมัครแยกต่างหาก — ให้ None บ่อยเป็นเรื่องปกติ
    """
    patterns = [
        r'(?:เงินเดือน|salary)(?:ที่คาดหวัง|expected|expectation)?\s*[:\s]\s*([\d,]+)',
        r'expected\s+salary\s*[:\s]\s*([\d,]+)',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            value = m.group(1).replace(",", "")
            try:
                return float(value)
            except ValueError:
                continue
    return None


def extract_vehicle_status(text: str) -> dict:
    """FR-3.13 — เช็คว่ามีรถยนต์ส่วนตัว / ใบขับขี่ ไหม (เจอคำ = True)"""
    has_vehicle = any(kw in text for kw in
        ["มีรถยนต์ส่วนตัว", "รถยนต์ส่วนตัว", "own car", "own vehicle", "มีรถ"])
    has_license = any(kw in text for kw in
        ["ใบขับขี่", "driving license", "driver's license", "driving licence"])
    return {"has_vehicle": has_vehicle, "has_license": has_license}


def extract_language_scores(text: str) -> dict:
    """
    FR-3.14 — ดึงคะแนนภาษาอังกฤษ (TOEIC/IELTS/TOEFL) ถ้าระบุไว้
    คืน dict เช่น {"TOEIC": 750, "IELTS": None, "TOEFL": None}
    """
    scores = {}
    for test_name, pattern in [
        ("TOEIC", r'toeic\s*[:\s]\s*(\d{2,4})'),
        ("IELTS", r'ielts\s*[:\s]\s*(\d(?:\.\d)?)'),
        ("TOEFL", r'toefl\s*[:\s]\s*(\d{2,4})'),
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        scores[test_name] = float(m.group(1)) if m else None
    return scores


# ============================================================
#  1. ResumeResult
# ============================================================

@dataclass
class ResumeResult:
    name: str
    file: str
    score: float = 0.0
    recommendation: str = ""
    keyword_score: float = 0.0
    ai_score: float = 0.0
    struct_score: float = 0.0
    special_score: float = 0.0   # FR-4.9 — คะแนนพิเศษ 15 คะแนน (เฉพาะบางตำแหน่ง)
    experience: str = "ไม่ระบุ"
    gpa: Optional[float] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    salary_expectation: Optional[float] = None
    vehicle_status: dict = field(default_factory=dict)
    language_scores: dict = field(default_factory=dict)
    error: Optional[str] = None
    struct_checks: dict = field(default_factory=dict)
    keyword_breakdown: dict = field(default_factory=dict)
    missing_keywords: list = field(default_factory=list)  # FR-5.5 4.2 — สื่อสารว่าขาดอะไร

    def to_dict(self) -> dict:
        return {
            "name": self.name, "file": self.file, "score": self.score,
            "recommendation": self.recommendation,
            "keyword_score": self.keyword_score, "ai_score": self.ai_score,
            "struct_score": self.struct_score, "special_score": self.special_score,
            "experience": self.experience, "gpa": self.gpa,
            "age": self.age, "gender": self.gender,
            "salary_expectation": self.salary_expectation,
            "vehicle_status": self.vehicle_status,
            "language_scores": self.language_scores,
            "error": self.error, "struct_checks": self.struct_checks,
            "keyword_breakdown": self.keyword_breakdown,
            "missing_keywords": self.missing_keywords,
        }

    def passed(self) -> bool:
        return self.recommendation == "ผ่าน"


# ============================================================
#  2. Config
# ============================================================

class Config:
    def __init__(
        self,
        # กลุ่ม 1: ประสบการณ์ & ทักษะหลัก (34 คะแนน)
        position_keywords=None, duties_keywords=None, skill_keywords=None,
        min_experience_years=None,
        # กลุ่ม 2: คุณสมบัติรอง (18-19 คะแนน)
        field_of_study_keywords=None, min_gpa=None, general_keywords=None,
        # กลุ่ม 3: ข้อมูลพื้นฐาน (8 คะแนน)
        edu_level_keywords=None,
        age_range=None,      # (min, max) FR-3.6
        gender=None,         # "male" | "female" | None (ไม่จำกัด) FR-3.10
        salary_range=None,   # (min, max) FR-3.11 — งบประมาณที่บริษัทตั้งไว้
        # เงื่อนไขแบบที่ 3 special (FR-4.9 — 15 คะแนนพิเศษ เฉพาะบางตำแหน่ง)
        enable_special_score=False,
        require_vehicle=False, require_license=False,   # FR-3.13 (5 คะแนน)
        min_toeic_score=None, other_language=None,        # FR-3.14 (10 คะแนน)

        pass_threshold=60,
        review_threshold=45,
    ):
        self.position_keywords    = position_keywords or []
        self.duties_keywords      = duties_keywords or []
        self.skill_keywords       = skill_keywords or []
        self.min_experience_years = min_experience_years

        self.field_of_study_keywords = field_of_study_keywords or []
        self.min_gpa                  = min_gpa
        self.general_keywords         = general_keywords or []

        self.edu_level_keywords = edu_level_keywords or []
        self.age_range           = age_range
        self.gender               = gender
        self.salary_range         = salary_range

        self.enable_special_score = enable_special_score
        self.require_vehicle = require_vehicle
        self.require_license = require_license
        self.min_toeic_score  = min_toeic_score
        self.other_language   = other_language

        self.pass_threshold   = pass_threshold
        self.review_threshold = review_threshold

    def validate(self):
        if not (0 <= self.review_threshold <= self.pass_threshold <= 100):
            raise ValueError("threshold ต้องอยู่ในช่วง 0-100")
        return True


# ============================================================
#  3. PDFReader
# ============================================================

class PDFReader:
    def read(self, path: str) -> str:
        text = ""
        try:
            doc = fitz.open(path)
            for page in doc:
                t = page.get_text()
                if t:
                    text += t + "\n"
            doc.close()
        except Exception as e:
            print(f"  [warn] เปิดไฟล์ไม่ได้: {e}")
        return text.strip().lower()

    def is_readable(self, path: str) -> bool:
        return bool(self.read(path))


# ============================================================
#  4. Analyzer
# ============================================================

class Analyzer:
    def __init__(self, config: Config = None, reader: PDFReader = None):
        self.config = config or Config()
        self.reader = reader or PDFReader()
        self.config.validate()

    def analyze(self, jd_text: str, resume_path: str) -> ResumeResult:
        filename = Path(resume_path).name
        text = self.reader.read(resume_path)

        if not text:
            return ResumeResult(name=filename, file=filename,
                error="อ่าน PDF ไม่ได้ (อาจเป็น scanned image)")

        gpa_value  = extract_gpa(text)
        exp_years  = extract_experience_years(text)
        age_value  = extract_age(text)
        gender_val = extract_gender(text)
        salary_val = extract_salary_expectation(text)
        vehicle    = extract_vehicle_status(text)
        lang_score = extract_language_scores(text)

        keyword_score, breakdown, missing = self._keyword_score(
            text, gpa_value, exp_years, age_value, gender_val, salary_val
        )
        ai_score = self._ai_score_placeholder(jd_text, text)
        struct   = self._struct_score(text)

        special_score = 0.0
        if self.config.enable_special_score:
            special_score = self._special_score(vehicle, lang_score)

        total = round(keyword_score + ai_score + struct["score"] + special_score, 1)

        rec = (
            "ผ่าน"               if total >= self.config.pass_threshold else
            "พิจารณาเพิ่มเติม"  if total >= self.config.review_threshold else
            "ไม่ผ่าน"
        )

        return ResumeResult(
            name=self._extract_name(text), file=filename, score=total,
            recommendation=rec,
            keyword_score=round(keyword_score, 1), ai_score=round(ai_score, 1),
            struct_score=round(struct["score"], 1), special_score=round(special_score, 1),
            experience=f"{exp_years:.0f} ปี" if exp_years else "ไม่ระบุ",
            gpa=gpa_value, age=age_value, gender=gender_val,
            salary_expectation=salary_val, vehicle_status=vehicle,
            language_scores=lang_score,
            struct_checks=struct["checks"], keyword_breakdown=breakdown,
            missing_keywords=missing,
        )

    def _keyword_score(self, text, gpa_value, exp_years, age_value, gender_val, salary_val):
        c = self.config
        breakdown = {}
        missing = []  # FR-5.5 4.2 — เก็บหัวข้อที่ไม่พบ ไว้โชว์ให้ HR เห็นเหตุผล

        def check(label, condition, points):
            breakdown[label] = points if condition else 0.0
            if not condition:
                missing.append(label)

        # กลุ่ม 1 (34)
        check("ตำแหน่งงาน (FR-3.2)", self._any_keyword_found(text, c.position_keywords), 10.0)
        check("ลักษณะงาน (FR-3.8)",   self._any_keyword_found(text, c.duties_keywords), 10.0)
        check("ทักษะ (FR-3.9)",       self._any_keyword_found(text, c.skill_keywords), 8.0)
        check("ประสบการณ์ (FR-3.7)",  self._meets_min(exp_years, c.min_experience_years), 6.0)

        # กลุ่ม 2 (18-19)
        check("สาขาวิชา (FR-3.4)",    self._any_keyword_found(text, c.field_of_study_keywords), 8.0)
        check("GPA (FR-3.12)",         self._meets_min(gpa_value, c.min_gpa), 6.0)
        check("Keyword ทั่วไป (FR-3.3)", self._any_keyword_found(text, c.general_keywords), 5.0)

        # กลุ่ม 3 (8)
        check("วุฒิการศึกษา (FR-3.5)", self._any_keyword_found(text, c.edu_level_keywords), 2.0)
        check("อายุ (FR-3.6)",         self._in_range(age_value, c.age_range), 2.0)
        check("เพศ (FR-3.10)",         self._gender_match(gender_val, c.gender), 2.0)
        check("เงินเดือน (FR-3.11)",   self._in_range(salary_val, c.salary_range), 2.0)

        raw_total = sum(breakdown.values())
        normalized = round((raw_total / 61.0) * 60, 2)  # normalize เพราะ requirement รวมได้ 61 ไม่ใช่ 60
        return normalized, breakdown, missing

    def _any_keyword_found(self, text, keywords):
        # หมายเหตุ: ถ้าไม่ได้กำหนดเงื่อนไข (list ว่าง) ถือว่า "ไม่ได้ใช้ filter นี้"
        # ให้ผ่านอัตโนมัติ ไม่ใช่ตัดคะแนน — ตรงกับ FR-4.5 ข้อ 2 (ไม่ระบุ = ไม่กระทบ)
        if not keywords:
            return True
        return any(kw.lower() in text for kw in keywords)

    def _meets_min(self, actual, minimum):
        if minimum is None:
            return True
        if actual is None:
            return False
        return actual >= minimum

    def _in_range(self, actual, value_range):
        if value_range is None:
            return True
        if actual is None:
            return False
        lo, hi = value_range
        return lo <= actual <= hi

    def _gender_match(self, actual, required):
        if required is None:
            return True
        if actual is None:
            return False
        return actual == required

    def _ai_score_placeholder(self, jd_text, resume_text):
        """FR-4.6 เวอร์ชัน placeholder — ของจริงต้องต่อ Groq API"""
        jd_words = set(re.findall(r'[a-zA-Z\u0E00-\u0E7F]+', jd_text.lower()))
        if not jd_words:
            return 0.0
        matched = sum(1 for w in jd_words if w in resume_text)
        return round((matched / len(jd_words)) * 25, 1)

    def _struct_score(self, text):
        checks = {
            "ตำแหน่งงาน (FR-3.2)": any(w in text for w in ["position", "ตำแหน่ง", "job title"]),
            "สาขาวิชา (FR-3.4)":    any(w in text for w in ["สาขา", "major", "field of study"]),
            "วุฒิการศึกษา (FR-3.5)": any(w in text for w in ["education", "university", "bachelor", "ปริญญา"]),
            "อายุ (FR-3.6)":         bool(re.search(r'อายุ|age\s*:?\s*\d+', text)),
            "ประสบการณ์ (FR-3.7)":   any(w in text for w in ["experience", "ประสบการณ์", "developer", "ทำงาน"]),
            "ลักษณะงาน (FR-3.8)":    any(w in text for w in ["responsibility", "duties", "หน้าที่"]),
            "ทักษะ (FR-3.9)":        any(w in text for w in ["skill", "python", "java", "sql", "ทักษะ"]),
            "เงินเดือน (FR-3.11)":   any(w in text for w in ["salary", "เงินเดือน", "expected salary"]),
            "GPA (FR-3.12)":          bool(re.search(r'gpa|เกรดเฉลี่ย', text)),
        }
        n = len(checks)
        per_item = 15.0 / n
        return {"checks": checks, "score": sum(per_item for v in checks.values() if v)}

    def _special_score(self, vehicle: dict, lang_score: dict) -> float:
        """FR-4.9 — คะแนนพิเศษ 15 คะแนน (เฉพาะตำแหน่งที่เปิดใช้)"""
        c = self.config
        score = 0.0

        # FR-3.13 ยานพาหนะ+ใบขับขี่ (5 คะแนน)
        vehicle_ok = (not c.require_vehicle or vehicle.get("has_vehicle")) and \
                     (not c.require_license or vehicle.get("has_license"))
        if vehicle_ok:
            score += 5.0

        # FR-3.14 ทักษะภาษา (10 คะแนน)
        lang_ok = True
        if c.min_toeic_score is not None:
            toeic = lang_score.get("TOEIC")
            lang_ok = toeic is not None and toeic >= c.min_toeic_score
        if lang_ok:
            score += 10.0

        return score

    def _extract_name(self, text):
        for line in text.strip().split('\n')[:5]:
            line = line.strip()
            if 2 < len(line) < 50 and not any(c in line for c in ['@', ':', '/', 'http', '.']):
                return line.title()
        return "ไม่ทราบชื่อ"


# ============================================================
#  5. ResumeScreener
# ============================================================

class ResumeScreener:
    def __init__(self, config: Config = None):
        self.analyzer = Analyzer(config=config)

    def screen(self, jd_path, resume_paths, min_score=0, pass_only=False):
        jd_file = Path(jd_path)
        if not jd_file.exists():
            raise FileNotFoundError(f"ไม่พบไฟล์ JD: {jd_path}")

        if jd_path.lower().endswith(".pdf"):
            import pdfplumber
            with pdfplumber.open(jd_path) as pdf:
                jd_text = "\n".join(p.extract_text() or "" for p in pdf.pages).lower()
        else:
            jd_text = open(jd_path, encoding="utf-8").read().lower()

        results = []
        for path in resume_paths:
            if not Path(path).exists():
                continue
            results.append(self.analyzer.analyze(jd_text, path))

        results.sort(key=lambda r: r.score, reverse=True)
        return [r for r in results
                if r.score >= min_score and (not pass_only or r.passed())]

    def save_json(self, results, output="results.json"):
        with open(output, "w", encoding="utf-8") as f:
            json.dump([r.to_dict() for r in results], f, ensure_ascii=False, indent=2)