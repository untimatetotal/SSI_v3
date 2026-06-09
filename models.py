# ============================================================
# models.py — รวมทุก class ไว้ในไฟล์เดียว
# ============================================================
# ประกอบด้วย:
#   ResumeResult   — เก็บผลลัพธ์ resume 1 ไฟล์
#   Config         — เก็บการตั้งค่าทั้งหมด
#   PDFReader      — อ่านข้อความจาก PDF
#   Analyzer       — คำนวณคะแนน
#   ResumeScreener — ประสานงานทุกอย่าง
# ============================================================

import re # find
import json # transfer to json 
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional



# Exceptin for user (about tool of program)
try:
    import fitz
except ImportError:
    raise ImportError("please install : python -m pip install pymupdf")

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
except ImportError:
    raise ImportError("please install : python -m pip install scikit-learn")


# ============================================================
#  1. ResumeResult — contain resume 1 file
# ============================================================

@dataclass
class ResumeResult:
    # set constructor  start value = 0 
    name: str
    file: str
    score: float = 0.0
    recommendation: str = "" # ข้อความแนะนำ 
    tfidf: float = 0.0
    keyword: float = 0.0
    struct: float = 0.0  # โครงสร้าง resume (หัวข้อ)
    experience: str = "ไม่ระบุ"
    error: Optional[str] = None
    struct_checks: dict = field(default_factory=dict)


    def to_dict(self) -> dict: # dict : contain data form key , value
        return {
            "name": self.name, "file": self.file,
            "score": self.score, "recommendation": self.recommendation,
            "tfidf": self.tfidf, "keyword": self.keyword,
            "struct": self.struct, "experience": self.experience,
            "error": self.error, "struct_checks": self.struct_checks,
        }


    def passed(self) -> bool:
        return self.recommendation == "ผ่าน"


# ============================================================
#  2. Config — contain setting program
# ============================================================


class Config:
    def __init__(
        self,

        required_keywords=None,
        edu_keywords = None, 
        bonus_keywords=None,
        pass_threshold=60,
        review_threshold=45,
        weight_tfidf=0.40,
        weight_keyword=0.45,
        weight_struct=0.15,
    ):
        

    # set keyword
        self.required_keywords = required_keywords or []
        self.edu_keywords = edu_keywords or []
        self.bonus_keywords    = bonus_keywords or []

        self.pass_threshold    = pass_threshold
        self.review_threshold  = review_threshold
        self.weight_tfidf      = weight_tfidf
        self.weight_keyword    = weight_keyword
        self.weight_struct     = weight_struct

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
                f"{self.weight_keyword}/{self.weight_struct}])")



# ============================================================ 
#  3. PDFReader — read text from PDF file 
# ============================================================


class PDFReader:
    def read(self, path: str) -> str:
        text = ""
        try:
            doc = fitz.open(path) # open pdf file
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
#  4. Analyzer — calculate point
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

       # check require keyword ก่อน (กรองชั้นแรก)
       # ถ้สคำ keyword หายตัดออกเลย 
        missing = self._check_required(text)
        if missing:
            return ResumeResult(
                name=self._extract_name(text), file=filename,
                score=0.0, recommendation="ไม่ผ่าน",
                error=f"ขาด keyword บังคับ: {', '.join(missing)}",
                experience=self._extract_exp(text),
            )
       # calculate point 3 section 

        tfidf   = self._tfidf_score(jd_text, text) # point JD
        keyword = self._keyword_score(text) # kw bonus 
        struct  = self._struct_score(text) 
        c       = self.config


        # รวมคะแนนตาม weight
        total = round(
            tfidf   * c.weight_tfidf   +
            keyword * c.weight_keyword +
            struct["score"] * c.weight_struct, 1
        )

        rec = ("ผ่าน" if total >= c.pass_threshold
               else "พิจารณาเพิ่มเติม" if total >= c.review_threshold
               else "ไม่ผ่าน")

        return ResumeResult(
            name=self._extract_name(text), file=filename,
            score=total, recommendation=rec,
            tfidf=round(tfidf, 1), keyword=round(keyword, 1),
            struct=round(struct["score"], 1),
            experience=self._extract_exp(text),
            struct_checks=struct["checks"],
        )

    def _check_required(self, text):
     missing =  [kw for kw in self.config.required_keywords 
                 if  kw.lower() not in text]
     if self.config.edu_keywords:
         has_edu = any(kw.lower()in text
                       for kw in self.config.edu_keywords)
         if not has_edu:
             missing.append(f"วุฒิการศึกษา (ต้องมีอย่างน้อยหนึ่งใน: {self.config.edu_keywords})")
     return missing
         


    def _tfidf_score(self, jd_text, resume_text):
        # ตรวจสอบความคล้ายกัน ระหว่าง JD , Resume ด้วย TF-IDF (แบ่งตรวจสอบทั้งคำเดี่ยวและคู่คำ)
        try:
            vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
            mat = vec.fit_transform([jd_text, resume_text])
            return round(cosine_similarity(mat[0:1], mat[1:2])[0][0] * 100, 2)
        except Exception:
            return 0.0

    def _keyword_score(self, text):
        if not self.config.bonus_keywords: # bonus kw คือ ไม่มีก็ได้แต่คะแนนจะลดลง  ถ้าไม่ได้กำหนด bonus kw ไว้คะแนนจะไม่ลดลง 
            return 70.0 # return default value
        found = sum(1 for kw in self.config.bonus_keywords
                    if kw.lower() in text)
        return (found / len(self.config.bonus_keywords)) * 100


 # define field 
    def _struct_score(self, text):

        # check pattern 
        checks = {
            "มี Email":
                bool(re.search(r'[\w.-]+@[\w.-]+\.\w+', text)),
            "มี เบอร์โทร":
                bool(re.search(r'(\+66|0[689])\d{8}|\d{3}[-.\s]\d{3}[-.\s]\d{4}', text)),
            "มี ประสบการณ์":
                any(w in text for w in [
                    "experience", "ประสบการณ์", "developer", "ทำงาน"]),
            "มี การศึกษา":
                any(w in text for w in [
                    "education", "university", "bachelor", "ปริญญา", "engineering"]),
            "มี ทักษะ":
                any(w in text for w in [
                    "skill", "python", "java", "sql", "docker", "git"]),
        }
        return {"checks": checks,
                "score": (sum(checks.values()) / len(checks)) * 100}



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
#  5. ResumeScreener — connect all 
# ============================================================

class ResumeScreener:
    def __init__(self, config: Config = None):
        self.analyzer = Analyzer(config=config)

    def screen(self, jd_path, resume_paths, min_score=0, pass_only=False):
        jd_file = Path(jd_path)
        if not jd_file.exists():
            raise FileNotFoundError(f"ไม่พบไฟล์ JD: {jd_path}")
       # jd_text = jd_file.read_text(encoding="utf-8").lower()#

       #====== fix read text of pdf OR file Text
        if jd_path.lower().endswith(".pdf") :
            import pdfplumber
            with pdfplumber.open(jd_path) as pdf:
                jd_text = "\n".join(p.extract_text() or "" for p in pdf.pages).lower()
        else: 
               # ถ้าเป็น .txt หรือไฟล์อื่น → อ่านแบบ text ปกติ
              jd_text = open(jd_path, encoding="utf-8").read().lower()
           

        print(f"\nJob Description : {jd_path}")
        print(f"Resume ทั้งหมด  : {len(resume_paths)} ไฟล์")
        print("=" * 55)

    # analyze each file save at list 
        results = []
        for path in resume_paths:
            if not Path(path).exists():
                print(f"[skip] ไม่พบ: {path}")
                continue
            print(f"กำลังวิเคราะห์: {path} ...", end=" ", flush=True)
            result = self.analyzer.analyze(jd_text, path)
            results.append(result)
            print("Error" if result.error else f"คะแนน {result.score}")
        # sort resume most point before
        results.sort(key=lambda r: r.score, reverse=True)
        #กรองตาม min score และ pass only
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
        print(f"  ✓ ผ่าน              : {passed} คน") # คุณสมบัติตรง
        print(f"  ~ พิจารณาเพิ่มเติม : {review} คน")  # ส่งให้ HR พิจารณาเพิ่มเติมเอง
        print(f"  ✗ ไม่ผ่าน           : {failed} คน") # คุณสมบัติไม่ตรง 
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
        # progress bar: score=50 → 10 █ + 10 ░
        # int(score/5) = จำนวนบล็อก █
        bar = "█" * int(r.score / 5) + "░" * (20 - int(r.score / 5))
        print(f"\n{'='*55}")
        print(f"อันดับ #{rank}  |  {r.name}")
        print(f"คะแนน  : {r.score}/100  [{bar}]")
        print(f"ผล     : {color}[ {symbol} ] {r.recommendation}\033[0m")
        print(f"ประสบการณ์ : {r.experience}")
        print(f"  TF-IDF   : {r.tfidf:5.1f} × {c.weight_tfidf} = {r.tfidf*c.weight_tfidf:.1f}")
        print(f"  Keyword  : {r.keyword:5.1f} × {c.weight_keyword} = {r.keyword*c.weight_keyword:.1f}")
        print(f"  โครงสร้าง: {r.struct:5.1f} × {c.weight_struct} = {r.struct*c.weight_struct:.1f}")
        if r.struct_checks:
            for k, v in r.struct_checks.items():
                print(f"  {'✓' if v else '✗'}  {k}")