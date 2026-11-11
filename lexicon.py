# ============================================================
# lexicon.py — พจนานุกรมวุฒิ / มหาวิทยาลัย / คำพ้องตำแหน่งและทักษะ (ไทย-อังกฤษ)
# HR เพิ่มคำพ้องเองได้ในไฟล์ synonyms_custom.txt (หนึ่งกลุ่มต่อบรรทัด คั่นด้วย |)
# ============================================================

import re
from pathlib import Path

DEGREE_LEVELS = [
    (4, r"ปริญญาเอก|ดุษฎีบัณฑิต|ph\.?\s?d|doctor of|doctorate"),
    (3, r"ปริญญาโท|มหาบัณฑิต|master|m\.\s?eng|m\.\s?sc|m\.\s?b\.?a|mba\b|วศ\.\s?ม|วท\.\s?ม|บธ\.\s?ม|ศศ\.\s?ม|ค\.\s?ม"),
    (2, r"ปริญญาตรี|bachelor|b\.\s?eng|b\.\s?sc|b\.\s?b\.?a|b\.\s?a\.|วศ\.\s?บ|วท\.\s?บ|บธ\.\s?บ|ศศ\.\s?บ|นศ\.\s?บ|บช\.\s?บ|ค\.\s?บ|อ\.\s?บ|รป\.\s?บ|น\.\s?บ|ทล\.\s?บ|อส\.\s?บ|บัณฑิต"),
    (1, r"ปวส|ปวช|อนุปริญญา|higher vocational|vocational|diploma"),
    (0, r"มัธยม|high school|ม\.\s?6|secondary school|matthayom"),
]
DEGREE_RE = [(level, re.compile(p, re.IGNORECASE)) for level, p in DEGREE_LEVELS]

LEVEL_LABEL = {0: "มัธยมศึกษา", 1: "ปวช./ปวส.", 2: "ปริญญาตรี", 3: "ปริญญาโท", 4: "ปริญญาเอก"}


def degree_level(text: str):
    """ระดับวุฒิสูงสุดที่พบในข้อความ (0-4) หรือ None"""
    for level, rx in DEGREE_RE:
        if rx.search(text or ""):
            return level
    return None


SYNONYM_GROUPS = [
    ["วิศวกรอุตสาหการ", "วิศวกรรมอุตสาหการ", "industrial engineer", "industrial engineering"],
    ["วิศวกรเครื่องกล", "วิศวกรรมเครื่องกล", "mechanical engineer", "mechanical engineering"],
    ["วิศวกรไฟฟ้า", "วิศวกรรมไฟฟ้า", "electrical engineer", "electrical engineering"],
    ["วิศวกรโยธา", "วิศวกรรมโยธา", "civil engineer", "civil engineering"],
    ["วิศวกรเคมี", "วิศวกรรมเคมี", "chemical engineer", "chemical engineering"],
    ["วิศวกรรมโลหการ", "วิศวกรโลหการ", "metallurgical engineer", "metallurgical engineering", "metallurgy"],
    ["วิศวกรรมคอมพิวเตอร์", "computer engineer", "computer engineering"],
    ["วิศวกรรมเกษตร", "agricultural engineering", "agricultural engineer"],
    ["วิศวกรการผลิต", "วิศวกรฝ่ายผลิต", "production engineer", "manufacturing engineer", "วิศวกรรมการผลิต", "manufacturing engineering"],
    ["วิศวกรกระบวนการ", "process engineer"],
    ["ซ่อมบำรุง", "บำรุงรักษา", "maintenance", "maintenance engineer", "วิศวกรซ่อมบำรุง", "ช่างซ่อมบำรุง"],
    ["ควบคุมคุณภาพ", "quality control", "qc"],
    ["ประกันคุณภาพ", "quality assurance", "qa"],
    ["การตลาด", "marketing", "digital marketing", "การตลาดออนไลน์", "การตลาดดิจิทัล"],
    ["ฝ่ายขาย", "พนักงานขาย", "sales", "sales representative"],
    ["วิศวกรฝ่ายขาย", "sales engineer"],
    ["นักบัญชี", "บัญชี", "accountant", "accounting"],
    ["การเงิน", "finance", "financial"],
    ["ทรัพยากรบุคคล", "human resources", "human resource", "hr", "สรรหาบุคลากร", "recruitment", "recruiter"],
    ["จัดซื้อ", "purchasing", "procurement"],
    ["คลังสินค้า", "warehouse", "logistics", "โลจิสติกส์"],
    ["ความปลอดภัย", "เจ้าหน้าที่ความปลอดภัย", "จป", "safety", "occupational safety", "safety officer"],
    ["ไอที", "it support", "information technology", "เทคโนโลยีสารสนเทศ"],
    ["นักพัฒนาซอฟต์แวร์", "software developer", "software engineer", "programmer", "โปรแกรมเมอร์"],
    ["เขียนแบบ", "autocad", "cad", "drafting"],
    ["solidworks", "solid works"],
    ["plc", "programmable logic controller"],
    ["excel", "microsoft excel", "vlookup"],
    ["boq", "bill of quantities", "ถอดแบบ", "ประมาณราคา", "estimator"],
    ["lean", "lean manufacturing", "ลีน"],
    ["kaizen", "ไคเซ็น"],
    ["5s", "5ส"],
    ["iso 9001", "iso9001"],
    ["ภาษาอังกฤษ", "english"],
    ["เหล็ก", "steel", "โลหะ", "metal"],
    ["ระบบอัตโนมัติ", "automation"],
    ["iot", "internet of things"],
]

UNIVERSITY_ALIASES = [
    ["มหาวิทยาลัยเชียงใหม่", "ม.เชียงใหม่", "มช", "chiang mai university", "cmu"],
    ["สถาบันเทคโนโลยีพระจอมเกล้าเจ้าคุณทหารลาดกระบัง", "สจล", "kmitl", "ลาดกระบัง"],
    ["มหาวิทยาลัยเกษตรศาสตร์", "ม.เกษตรศาสตร์", "มก", "kasetsart university", "kasetsart"],
    ["จุฬาลงกรณ์มหาวิทยาลัย", "จุฬา", "chulalongkorn university", "chulalongkorn"],
    ["มหาวิทยาลัยธรรมศาสตร์", "ม.ธรรมศาสตร์", "มธ", "thammasat university", "thammasat"],
    ["มหาวิทยาลัยเทคโนโลยีพระจอมเกล้าธนบุรี", "มจธ", "kmutt", "บางมด"],
    ["มหาวิทยาลัยเทคโนโลยีพระจอมเกล้าพระนครเหนือ", "มจพ", "kmutnb", "พระนครเหนือ"],
    ["มหาวิทยาลัยขอนแก่น", "ม.ขอนแก่น", "มข", "khon kaen university"],
    ["มหาวิทยาลัยสงขลานครินทร์", "ม.สงขลานครินทร์", "มอ", "prince of songkla university", "psu"],
    ["มหาวิทยาลัยมหิดล", "ม.มหิดล", "mahidol university", "mahidol"],
    ["มหาวิทยาลัยเทคโนโลยีสุรนารี", "มทส", "suranaree university of technology", "suranaree"],
    ["มหาวิทยาลัยศรีนครินทรวิโรฒ", "มศว", "srinakharinwirot university"],
    ["มหาวิทยาลัยเทคโนโลยีราชมงคล", "ราชมงคล", "rajamangala university of technology", "rmut"],
]

_CUSTOM_FILE = Path(__file__).with_name("synonyms_custom.txt")


def _load_groups():
    groups = [list(g) for g in SYNONYM_GROUPS + UNIVERSITY_ALIASES]
    if _CUSTOM_FILE.exists():
        for line in _CUSTOM_FILE.read_text(encoding="utf-8").splitlines():
            terms = [t.strip().lower() for t in line.split("|") if t.strip()]
            if len(terms) >= 2 and not line.lstrip().startswith("#"):
                groups.append(terms)
    index = {}
    for g in groups:
        members = {t.lower() for t in g}
        for t in members:
            index.setdefault(t, set()).update(members)
    return index


_INDEX = _load_groups()


def expand_term(term: str) -> list:
    """คำค้นพร้อมคำพ้อง — คำหลักอยู่ตัวแรกเสมอ"""
    t = (term or "").strip().lower()
    if not t:
        return []
    extra = set(_INDEX.get(t, set()))
    for key, members in _INDEX.items():
        if len(key) >= 4 and (key in t) and key != t:
            extra.update(members)
    extra.discard(t)
    return [t] + sorted(extra, key=len, reverse=True)


def expand_terms(terms) -> list:
    out, seen = [], set()
    for term in terms or []:
        for t in expand_term(term):
            if t not in seen:
                seen.add(t)
                out.append(t)
    return out
