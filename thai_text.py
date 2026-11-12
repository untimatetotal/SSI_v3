# ============================================================
# thai_text.py — จัดการข้อความภาษาไทย: ปรับมาตรฐาน วันที่ พ.ศ. การจับคำ
# ============================================================

import re
import unicodedata
from datetime import date
from typing import Optional

THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

PUA_THAI_MAP = {
    "\uf700": "ฐ", "\uf701": "ิ", "\uf702": "ี", "\uf703": "ึ", "\uf704": "ื",
    "\uf705": "่", "\uf706": "้", "\uf707": "๊", "\uf708": "๋", "\uf709": "์",
    "\uf70a": "่", "\uf70b": "้", "\uf70c": "๊", "\uf70d": "๋", "\uf70e": "์",
    "\uf70f": "ญ", "\uf710": "ั", "\uf711": "ํ", "\uf712": "็", "\uf713": "่",
    "\uf714": "้", "\uf715": "๊", "\uf716": "๋", "\uf717": "์", "\uf718": "ุ",
    "\uf719": "ู", "\uf71a": "ฺ",
}
PUA_TRANS = str.maketrans(PUA_THAI_MAP)
ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad]")
THAI_CHAR = re.compile("[\u0e00-\u0e7f]")
THAI_MARK = "\u0e31\u0e34-\u0e3a\u0e47-\u0e4e"
LEADING_MARK = re.compile(f"(?:^|[\\s(\\[])[{THAI_MARK}]")
PUA_ANY = re.compile("[\ue000-\uf8ff]")
DECOR = re.compile("[\u2022\u2023\u2043\u2219\u25a0-\u25ff\u2600-\u27bf\u2b00-\u2bff\ue000-\uf8ff\U0001f300-\U0001faff\ufe0f]")


def has_thai(text: str) -> bool:
    return bool(THAI_CHAR.search(text or ""))


def normalize_text(text: str) -> str:
    """ปรับข้อความให้เป็นมาตรฐาน: แก้รหัสพิเศษของฟอนต์ไทยเก่า สระแยก เลขไทย อักขระมองไม่เห็น"""
    if not text:
        return ""
    t = text.translate(PUA_TRANS)
    t = ZERO_WIDTH.sub("", t)
    t = unicodedata.normalize("NFC", t)
    t = re.sub("\u0e4d([\u0e48-\u0e4b])\u0e32", "\\1\u0e33", t)
    t = t.replace("\u0e4d\u0e32", "\u0e33")
    t = t.replace("\u0e40\u0e40", "\u0e41")
    t = t.translate(THAI_DIGITS)
    t = DECOR.sub(" ", t)
    t = t.replace("\u00a0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" ?\n ?", "\n", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def text_quality(raw: str) -> float:
    """คะแนนคุณภาพข้อความ 0-1 (1 = ดี) — ต่ำเมื่อมีรหัสพิเศษ, ตัวแทนอักขระเสีย หรือสระ/วรรณยุกต์ขึ้นต้นคำ"""
    if not raw or not raw.strip():
        return 0.0
    thai_count = len(THAI_CHAR.findall(raw)) or 1
    bad = raw.count("\ufffd") * 3
    bad += len(PUA_ANY.findall(raw.translate(PUA_TRANS)))
    bad += len(LEADING_MARK.findall(raw))
    if not has_thai(raw):
        return max(0.0, 1.0 - raw.count("\ufffd") / max(len(raw), 1) * 10)
    return max(0.0, 1.0 - bad / thai_count * 5)


# ── ปี พ.ศ. / เดือนไทย / ช่วงวันที่ ─────────────────────────────

MONTHS = {
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4, "พฤษภาคม": 5, "มิถุนายน": 6,
    "กรกฎาคม": 7, "สิงหาคม": 8, "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
    "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4, "พ.ค.": 5, "มิ.ย.": 6,
    "ก.ค.": 7, "ส.ค.": 8, "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12,
    "มค": 1, "กพ": 2, "มีค": 3, "เมย": 4, "พค": 5, "มิย": 6,
    "กค": 7, "สค": 8, "กย": 9, "ตค": 10, "พย": 11, "ธค": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_ALT = "|".join(sorted((re.escape(k) for k in MONTHS), key=len, reverse=True))
PRESENT_WORDS = r"(?:ปัจจุบัน|present|current|now|to date|ถึงปัจจุบัน)"
_SEP = r"\s*(?:-|–|—|~|ถึง|to|until)\s*"
_YEAR = r"((?:19|20|25)\d{2})"
_MONTH_YEAR = rf"(?:({_MONTH_ALT})\.?\s*,?\s*{_YEAR}|(\d{{1,2}})\s*[/.-]\s*{_YEAR}|{_YEAR})"

RANGE_RE = re.compile(
    rf"{_MONTH_YEAR}{_SEP}(?:{PRESENT_WORDS}|{_MONTH_YEAR})",
    re.IGNORECASE,
)


def to_ce_year(year: int) -> int:
    return year - 543 if year >= 2400 else year


def _ym(groups, today: date):
    month_name, y1, month_num, y2, y_only = groups
    if month_name:
        return to_ce_year(int(y1)), MONTHS.get(month_name.lower().rstrip("."), MONTHS.get(month_name.lower()))
    if month_num:
        m = int(month_num)
        return to_ce_year(int(y2)), m if 1 <= m <= 12 else None
    if y_only:
        return to_ce_year(int(y_only)), None
    return None


def find_date_ranges(text: str, today: Optional[date] = None):
    """คืน list ของ (start_ym, end_ym, ข้อความที่พบ, ตำแหน่ง) โดย ym = (ปี ค.ศ., เดือนหรือ None)"""
    today = today or date.today()
    found = []
    for m in RANGE_RE.finditer(text or ""):
        g = m.groups()
        start = _ym(g[0:5], today)
        if m.group(0) and re.search(PRESENT_WORDS + r"\s*$", m.group(0), re.IGNORECASE):
            end = (today.year, today.month)
        else:
            end = _ym(g[5:10], today)
        if not start or not end:
            continue
        if not (1970 <= start[0] <= today.year + 1 and 1970 <= end[0] <= today.year + 1):
            continue
        found.append((start, end, m.group(0), m.start()))
    return found


def months_between(start, end) -> int:
    sy, sm = start
    ey, em = end
    sm = sm or 1
    em = em or 12
    months = (ey - sy) * 12 + (em - sm) + 1
    return max(0, months)


def merge_month_spans(spans):
    """รวมช่วงที่ทับกัน แล้วคืนจำนวนเดือนรวม — spans เป็น list ของ (start_ym, end_ym)"""
    intervals = []
    for start, end in spans:
        s = start[0] * 12 + ((start[1] or 1) - 1)
        e = end[0] * 12 + ((end[1] or 12) - 1)
        if e < s:
            s, e = e, s
        intervals.append((s, e))
    intervals.sort()
    total, cur = 0, None
    for s, e in intervals:
        if cur is None or s > cur[1] + 1:
            if cur:
                total += cur[1] - cur[0] + 1
            cur = [s, e]
        else:
            cur[1] = max(cur[1], e)
    if cur:
        total += cur[1] - cur[0] + 1
    return total


BIRTH_LABEL = r"(?:born(?:\s+on)?|วันเดือนปีเกิด|วัน\s*เดือน\s*ปี\s*เกิด|วันเกิด|เกิดวันที่|เกิด|date\s*of\s*birth|birth\s*date|birth\s*of\s*date|birthday|d\.?o\.?b\.?)"
BIRTH_RE = re.compile(
    rf"{BIRTH_LABEL}\s*[:：]?\s*"
    rf"(?:(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_ALT})\.?\s*,?\s*{_YEAR}"
    rf"|({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s*{_YEAR}"
    rf"|{_YEAR}\s*[-/.]\s*(\d{{1,2}})\s*[-/.]\s*(\d{{1,2}})"
    rf"|(\d{{1,2}})\s*[-/.]\s*(\d{{1,2}})\s*[-/.]\s*{_YEAR}"
    rf"|(?:พ\.?ศ\.?|ค\.?ศ\.?)?\s*{_YEAR})",
    re.IGNORECASE,
)


BIRTH_SHORT_RE = re.compile(rf"{BIRTH_LABEL}\s*[:：]?\s*(\d{{1,2}})\s*[-/.]\s*(\d{{1,2}})\s*[-/.]\s*(\d{{2}})(?!\d)", re.IGNORECASE)


def _short_year_birthdate(text: str, today: Optional[date] = None) -> Optional[date]:
    """ปีสองหลัก เช่น 15/02/43 — ลองตีความเป็น พ.ศ. (25xx) และ ค.ศ. (19xx/20xx) แล้วเลือกแบบที่ได้อายุสมเหตุสมผล"""
    m = BIRTH_SHORT_RE.search(text or "")
    if not m:
        return None
    today = today or date.today()
    day, month, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    candidates = [2500 + yy - 543, 2000 + yy, 1900 + yy]
    if not has_thai(text):
        candidates = [2000 + yy, 1900 + yy, 2500 + yy - 543]
    for year in candidates:
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if age_on(d, today):
            return d
    return None


def parse_birthdate(text: str) -> Optional[date]:
    m = BIRTH_RE.search(text or "")
    if not m:
        return _short_year_birthdate(text)
    g = m.groups()
    try:
        if g[0]:
            return date(to_ce_year(int(g[2])), MONTHS[g[1].lower().rstrip(".")] if g[1].lower().rstrip(".") in MONTHS else MONTHS[g[1].lower()], int(g[0]))
        if g[3]:
            return date(to_ce_year(int(g[5])), MONTHS[g[3].lower().rstrip(".")] if g[3].lower().rstrip(".") in MONTHS else MONTHS[g[3].lower()], int(g[4]))
        if g[6]:
            return date(to_ce_year(int(g[6])), int(g[7]), int(g[8]))
        if g[9]:
            return date(to_ce_year(int(g[11])), int(g[10]), int(g[9]))
        if g[12]:
            return date(to_ce_year(int(g[12])), 7, 1)
    except (ValueError, KeyError):
        return None
    return None


def age_on(birth: date, today: Optional[date] = None) -> Optional[int]:
    today = today or date.today()
    age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    return age if 15 <= age <= 75 else None


# ── การจับคำ (ไทยไม่มีเว้นวรรค) ──────────────────────────────

_tokenizer = None


def _tokenize(text: str):
    global _tokenizer
    if _tokenizer is None:
        try:
            from pythainlp.tokenize import word_tokenize
            _tokenizer = lambda s: word_tokenize(s, engine="newmm", keep_whitespace=False)
        except Exception:
            _tokenizer = False
    if not _tokenizer:
        return None
    return _tokenizer(text)


class MatchText:
    """ข้อความที่เตรียมไว้สำหรับจับคำ — สร้างครั้งเดียวต่อเอกสาร"""

    def __init__(self, text: str):
        self.raw = normalize_text(text or "")
        self.lower = self.raw.lower()
        self._tokens = None
        self.lines = [ln.strip() for ln in self.raw.split("\n") if ln.strip()]

    @property
    def tokens(self):
        if self._tokens is None:
            toks = _tokenize(self.lower) if has_thai(self.lower) else None
            self._tokens = set(toks) if toks else set()
        return self._tokens

    def find(self, term: str):
        """คืนบรรทัดหลักฐานถ้าเจอคำ, ไม่เจอคืน None"""
        term = normalize_text(term).lower().strip()
        if not term:
            return None
        if not has_thai(term):
            pattern = r"(?<![a-z0-9])" + r"\s*".join(re.escape(p) for p in term.split()) + r"(?![a-z0-9])"
            m = re.search(pattern, self.lower)
            return self._snippet(m.start()) if m else None
        if len(term) <= 2 and self.tokens and term not in self.tokens:
            return None
        if len(term) == 3 and self.tokens and not any(
                tok == term or tok.startswith(term) or tok.endswith(term) for tok in self.tokens):
            return None
        idx = self.lower.find(term)
        return self._snippet(idx) if idx >= 0 else None

    def _snippet(self, pos: int) -> str:
        start = self.lower.rfind("\n", 0, pos) + 1
        end = self.lower.find("\n", pos)
        end = len(self.raw) if end < 0 else end
        line = self.raw[start:end].strip()
        if len(line) > 140:
            rel = pos - start
            line = ("…" if rel > 60 else "") + line[max(0, rel - 60):rel + 80] + "…"
        return line


# ── แก้คำที่ OCR อ่านผิดบ่อยในใบสมัคร (ผิด 1 ตัวอักษร เช่น "เคียรตินิยม" → "เกียรตินิยม") ──

OCR_LEXICON = sorted({
    "เกียรตินิยม", "ปริญญาตรี", "ปริญญาโท", "ปริญญาเอก", "ประสบการณ์", "ประวัติการศึกษา",
    "ประวัติการทำงาน", "มหาวิทยาลัย", "วิศวกรรมศาสตร์", "วิศวกรรม", "วิทยาศาสตร์", "บริหารธุรกิจ",
    "เกรดเฉลี่ยสะสม", "เกรดเฉลี่ย", "คะแนนเฉลี่ย", "เฉลี่ยสะสม", "ความสามารถ", "ภาษาอังกฤษ", "ข้อมูลส่วนตัว",
    "วันเกิด", "ตำแหน่ง", "รับผิดชอบ", "สหกิจศึกษา", "อุตสาหการ", "เครื่องกล", "คอมพิวเตอร์",
    "ควบคุมคุณภาพ", "ซ่อมบำรุง", "การผลิต", "ปัจจุบัน", "กุมภาพันธ์", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "พฤศจิกายน", "ธันวาคม", "มกราคม", "มีนาคม", "เมษายน", "ตุลาคม",
    "เทคโนโลยี", "วิทยาลัย", "การศึกษา", "การทำงาน", "ทักษะการ", "โปรแกรม", "นักศึกษา",
}, key=len, reverse=True)


def fix_ocr_thai(text: str) -> str:
    """แก้คำในพจนานุกรมที่ OCR อ่านผิด 1 ตัวอักษร (เฉพาะคำยาว 7 ตัวขึ้นไป เพื่อไม่แก้คำอื่นผิด)"""
    if not text or not has_thai(text):
        return text
    chars = list(text)
    n = len(chars)
    for word in OCR_LEXICON:
        L = len(word)
        if L < 7:
            continue
        i = 0
        while i <= n - L:
            if not ("\u0e00" <= chars[i] <= "\u0e7f"):
                i += 1
                continue
            diff = 0
            for a, b in zip(chars[i:i + L], word):
                if a != b:
                    diff += 1
                    if diff > 1:
                        break
            if diff == 1:
                chars[i:i + L] = list(word)
                i += L
            elif diff == 0:
                i += L
            else:
                i += 1
    fixed = "".join(chars)
    for variant, word in _MISSING_MARK_VARIANTS:
        if variant in fixed:
            fixed = re.sub(rf"{re.escape(variant)}(?![\u0e31\u0e34-\u0e3a\u0e47-\u0e4e])", word, fixed)
    return fixed


def _missing_mark_variants():
    """คำในพจนานุกรมที่ขาดสระบน/ล่างหรือวรรณยุกต์ไป 1 ตัว เช่น "เฉลีย" ← "เฉลี่ย" """
    marks = set("\u0e31\u0e34\u0e35\u0e36\u0e37\u0e38\u0e39\u0e47\u0e48\u0e49\u0e4a\u0e4b\u0e4c\u0e4d")
    lexicon = set(OCR_LEXICON)
    out = {}
    for word in OCR_LEXICON:
        if len(word) < 6:
            continue
        for i, ch in enumerate(word):
            if ch in marks:
                variant = word[:i] + word[i + 1:]
                if variant not in lexicon and len(variant) >= 6:
                    out.setdefault(variant, word)
    return sorted(out.items(), key=lambda kv: len(kv[0]), reverse=True)


_MISSING_MARK_VARIANTS = _missing_mark_variants()
