# ============================================================
# models.py — รวมทุก class ไว้ในไฟล์เดียว
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

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
except ImportError:
    raise ImportError("please install : python -m pip install scikit-learn")


# ── helper: ดึง GPA จากข้อความ ────────────────────────────────
def extract_gpa(text: str) -> Optional[float]:
    """ดึงค่า GPA จากข้อความ resume คืน float หรือ None ถ้าไม่พบ"""
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


# ============================================================
#  1. ResumeResult
# ============================================================

@dataclass
class ResumeResult:
    name: str
    file: str
    score: float = 0.0
    recommendation: str = ""
    tfidf: float = 0.0
    keyword: float = 0.0
    struct: float = 0.0
    experience: str = "ไม่ระบุ"
    gpa: Optional[float] = None
    error: Optional[str] = None
    struct_checks: dict = field(default_factory=dict)
    req_keywords: dict = field(default_factory=dict)  # {"python": True, "excel": False}
    bon_keywords: dict = field(default_factory=dict)  # {"powerbi": True, "crm": False}

    def to_dict(self) -> dict:
        return {
            "name":           self.name,
            "file":           self.file,
            "score":          self.score,
            "recommendation": self.recommendation,
            "tfidf":          self.tfidf,
            "keyword":        self.keyword,
            "struct":         self.struct,
            "experience":     self.experience,
            "gpa":            self.gpa,
            "error":          self.error,
            "struct_checks":  self.struct_checks,
            "req_keywords":   self.req_keywords,
            "bon_keywords":   self.bon_keywords,
        }

    def passed(self) -> bool:
        return self.recommendation == "ผ่าน"


# ============================================================
#  2. Config
# ============================================================

class Config:
    def __init__(
        self,
        required_keywords=None,
        edu_keywords=None,
        bonus_keywords=None,
        pass_threshold=60,
        review_threshold=45,
        weight_tfidf=0.40,
        weight_keyword=0.45,
        weight_struct=0.15,
        min_gpa=None,           # GPA ขั้นต่ำ เช่น 2.50 (None = ไม่กำหนด)
    ):
        self.required_keywords = required_keywords or []
        self.edu_keywords      = edu_keywords or []
        self.bonus_keywords    = bonus_keywords or []
        self.pass_threshold    = pass_threshold
        self.review_threshold  = review_threshold
        self.weight_tfidf      = weight_tfidf
        self.weight_keyword    = weight_keyword
        self.weight_struct     = weight_struct
        self.min_gpa           = min_gpa

    def validate(self):
        total = self.weight_tfidf + self.weight_keyword + self.weight_struct
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"น้ำหนักรวม {total:.2f} ต้องเท่ากับ 1.0")
        if not (0 <= self.review_threshold <= self.pass_threshold <= 100):
            raise ValueError("threshold ต้องอยู่ในช่วง 0-100")
        return True

    def __repr__(self):
        return (f"Config(pass={self.pass_threshold}, "
                f"review={self.review_threshold}, "
                f"weights=[{self.weight_tfidf}/"
                f"{self.weight_keyword}/{self.weight_struct}], "
                f"min_gpa={self.min_gpa})")


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
            return ResumeResult(
                name=filename, file=filename,
                error="อ่าน PDF ไม่ได้ (อาจเป็น scanned image)"
            )

        # ── ดึง GPA จาก resume ──────────────────────────────
        gpa_value = extract_gpa(text)

        # ── keyword breakdown (ทำก่อนเช็ค required) ─────────
        req_hits = {kw: (kw.lower() in text)
                    for kw in self.config.required_keywords}
        bon_hits = {kw: (kw.lower() in text)
                    for kw in self.config.bonus_keywords}

        # ── เช็ค required keywords + วุฒิ + GPA ────────────
        missing = self._check_required(text, gpa_value=gpa_value)
        if missing:
            return ResumeResult(
                name=self._extract_name(text),
                file=filename,
                score=0.0,
                recommendation="ไม่ผ่าน",
                error=f"ขาดคุณสมบัติ: {', '.join(missing)}",
                experience=self._extract_exp(text),
                gpa=gpa_value,
                req_keywords=req_hits,
                bon_keywords=bon_hits,
            )

        # ── คำนวณคะแนน 3 ส่วน ───────────────────────────────
        tfidf   = self._tfidf_score(jd_text, text)
        keyword = self._keyword_score(text)
        struct  = self._struct_score(text)
        c       = self.config

        total = round(
            tfidf           * c.weight_tfidf   +
            keyword         * c.weight_keyword +
            struct["score"] * c.weight_struct,
            1
        )

        rec = (
            "ผ่าน"               if total >= c.pass_threshold else
            "พิจารณาเพิ่มเติม"  if total >= c.review_threshold else
            "ไม่ผ่าน"
        )

        return ResumeResult(
            name=self._extract_name(text),
            file=filename,
            score=total,
            recommendation=rec,
            tfidf=round(tfidf, 1),
            keyword=round(keyword, 1),
            struct=round(struct["score"], 1),
            experience=self._extract_exp(text),
            gpa=gpa_value,
            struct_checks=struct["checks"],
            req_keywords=req_hits,
            bon_keywords=bon_hits,
        )

    def _check_required(self, text: str, gpa_value: Optional[float] = None) -> list:
        missing = [kw for kw in self.config.required_keywords
                   if kw.lower() not in text]

        # ── เช็ควุฒิการศึกษา (OR logic) ─────────────────────
        if self.config.edu_keywords:
            has_edu = any(kw.lower() in text for kw in self.config.edu_keywords)
            if not has_edu:
                missing.append(
                    f"วุฒิการศึกษา (ต้องมีอย่างน้อยหนึ่งใน: {self.config.edu_keywords})"
                )

        # ── เช็ค GPA ────────────────────────────────────────
        if self.config.min_gpa is not None:
            if gpa_value is None:
                missing.append("ไม่พบ GPA ใน resume")
            elif gpa_value < self.config.min_gpa:
                missing.append(
                    f"GPA {gpa_value:.2f} ต่ำกว่าเกณฑ์ที่กำหนด ({self.config.min_gpa:.2f})"
                )
            # gpa_value >= min_gpa → ผ่าน ไม่ต้อง append

        return missing

    def _tfidf_score(self, jd_text, resume_text):
        try:
            vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
            mat = vec.fit_transform([jd_text, resume_text])
            return round(cosine_similarity(mat[0:1], mat[1:2])[0][0] * 100, 2)
        except Exception:
            return 0.0

    def _keyword_score(self, text):
        if not self.config.bonus_keywords:
            return 70.0
        found = sum(1 for kw in self.config.bonus_keywords if kw.lower() in text)
        return (found / len(self.config.bonus_keywords)) * 100

    def _struct_score(self, text):
        checks = {
            "มี Email":
                bool(re.search(r'[\w.-]+@[\w.-]+\.\w+', text)),
            "มี เบอร์โทร":
                bool(re.search(r'(\+66|0[689])\d{8}|\d{3}[-.\s]\d{3}[-.\s]\d{4}', text)),
            "มี ประสบการณ์":
                any(w in text for w in ["experience", "ประสบการณ์", "developer", "ทำงาน"]),
            "มี การศึกษา":
                any(w in text for w in ["education", "university", "bachelor", "ปริญญา", "engineering"]),
            "มี ทักษะ":
                any(w in text for w in ["skill", "python", "java", "sql", "docker", "git"]),
        }
        return {
            "checks": checks,
            "score":  (sum(checks.values()) / len(checks)) * 100,
        }

    def _extract_name(self, text):
        for line in text.strip().split('\n')[:5]:
            line = line.strip()
            if 2 < len(line) < 50 and not any(
                    c in line for c in ['@', ':', '/', 'http', '.']):
                return line.title()
        return "ไม่ทราบชื่อ"

    def _extract_exp(self, text):
        for p in [r'(\d+)\s*\+?\s*years?\s*(?:of\s*)?experience',
                  r'experience\s*:?\s*(\d+)\s*years?',
                  r'(\d+)\s*ปี']:
            m = re.search(p, text)
            if m:
                return f"{m.group(1)} ปี"
        return "ไม่ระบุ"


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

        print(f"\nJob Description : {jd_path}")
        print(f"Resume ทั้งหมด  : {len(resume_paths)} ไฟล์")
        print("=" * 55)

        results = []
        for path in resume_paths:
            if not Path(path).exists():
                print(f"[skip] ไม่พบ: {path}")
                continue
            print(f"กำลังวิเคราะห์: {path} ...", end=" ", flush=True)
            result = self.analyzer.analyze(jd_text, path)
            results.append(result)
            print("Error" if result.error else f"คะแนน {result.score}")

        results.sort(key=lambda r: r.score, reverse=True)
        return [r for r in results
                if r.score >= min_score and (not pass_only or r.passed())]

    def print_results(self, results):
        print(f"\n{'='*55}\n  ผลการคัดกรอง Resume\n{'='*55}")
        for rank, r in enumerate(results, start=1):
            self._print_one(r, rank)

        passed = sum(1 for r in results if r.recommendation == "ผ่าน")
        review = sum(1 for r in results if r.recommendation == "พิจารณาเพิ่มเติม")
        failed = sum(1 for r in results if r.recommendation == "ไม่ผ่าน")
        print(f"\n{'='*55}\n  สรุปผล\n{'='*55}")
        print(f"  ✓ ผ่าน              : {passed} คน")
        print(f"  ~ พิจารณาเพิ่มเติม : {review} คน")
        print(f"  ✗ ไม่ผ่าน           : {failed} คน")
        print(f"  ค่าใช้จ่าย AI       : 0 บาท")

    def save_json(self, results, output="results.json"):
        with open(output, "w", encoding="utf-8") as f:
            json.dump([r.to_dict() for r in results],
                      f, ensure_ascii=False, indent=2)
        print(f"\n  บันทึกผลลัพธ์: {output}\n{'='*55}\n")

    def _print_one(self, r: ResumeResult, rank: int):
        if r.error and not r.recommendation:
            print(f"\n[Error] {r.file}: {r.error}")
            return
        c = self.analyzer.config
        colors = {
            "ผ่าน":              ("\033[92m", "PASS"),
            "พิจารณาเพิ่มเติม": ("\033[93m", "REVIEW"),
            "ไม่ผ่าน":           ("\033[91m", "FAIL"),
        }
        color, symbol = colors.get(r.recommendation, ("\033[0m", "?"))
        bar = "█" * int(r.score / 5) + "░" * (20 - int(r.score / 5))
        gpa_str = f"{r.gpa:.2f}" if r.gpa is not None else "ไม่พบ"
        print(f"\n{'='*55}")
        print(f"อันดับ #{rank}  |  {r.name}")
        print(f"คะแนน  : {r.score}/100  [{bar}]")
        print(f"ผล     : {color}[ {symbol} ] {r.recommendation}\033[0m")
        print(f"GPA    : {gpa_str}")
        print(f"ประสบการณ์ : {r.experience}")
        print(f"  TF-IDF   : {r.tfidf:5.1f} × {c.weight_tfidf} = {r.tfidf*c.weight_tfidf:.1f}")
        print(f"  Keyword  : {r.keyword:5.1f} × {c.weight_keyword} = {r.keyword*c.weight_keyword:.1f}")
        print(f"  โครงสร้าง: {r.struct:5.1f} × {c.weight_struct} = {r.struct*c.weight_struct:.1f}")
        if r.struct_checks:
            for k, v in r.struct_checks.items():
                print(f"  {'✓' if v else '✗'}  {k}")