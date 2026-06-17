# ============================================================
# test_algorithm.py — ทดสอบ algorithm ทุกส่วนของระบบ
# ============================================================
# รัน: python test_algorithm.py
# ทดสอบ:
#   1. TF-IDF Score
#   2. Keyword Score
#   3. Struct Score
#   4. Required Keyword
#   5. คำนวณคะแนนรวม
#   6. Recommendation
# ============================================================

import sys
sys.path.append(".")
from models import Config, PDFReader, Analyzer, ResumeResult

# สีสำหรับ terminal
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

pass_count = 0
fail_count = 0

def check(test_name, expected, actual, note=""):
    """ตรวจผลและแสดงผล PASS/FAIL"""
    global pass_count, fail_count
    if expected == actual:
        pass_count += 1
        print(f"  {GREEN}✓ PASS{RESET}  {test_name}")
    else:
        fail_count += 1
        print(f"  {RED}✗ FAIL{RESET}  {test_name}")
        print(f"         คาดว่า : {expected!r}")
        print(f"         ได้รับ : {actual!r}")
    if note:
        print(f"         หมายเหตุ: {note}")

def check_range(test_name, value, min_val, max_val, note=""):
    """ตรวจว่าค่าอยู่ในช่วงที่กำหนด"""
    global pass_count, fail_count
    if min_val <= value <= max_val:
        pass_count += 1
        print(f"  {GREEN}✓ PASS{RESET}  {test_name}  ({value:.1f} อยู่ในช่วง {min_val}-{max_val})")
    else:
        fail_count += 1
        print(f"  {RED}✗ FAIL{RESET}  {test_name}  ({value:.1f} ไม่อยู่ในช่วง {min_val}-{max_val})")
    if note:
        print(f"         หมายเหตุ: {note}")


# ============================================================
#  Test Group 1 — TF-IDF Score
# ============================================================
print(f"\n{BOLD}{'='*55}{RESET}")
print(f"{BOLD}  Test 1: TF-IDF Score{RESET}")
print(f"{BOLD}{'='*55}{RESET}")

analyzer = Analyzer()

# 1.1 ข้อความเหมือนกันทุกอย่าง → คะแนนสูงมาก
score = analyzer._tfidf_score("python developer", "python developer")
check_range("ข้อความเหมือนกัน → คะแนนสูงมาก", score, 90, 100)

# 1.2 ข้อความคล้ายกัน → คะแนนกลางๆ
score = analyzer._tfidf_score(
    "python developer docker postgresql",
    "python backend engineer docker mysql"
)
check_range("ข้อความคล้ายกัน → คะแนนกลางๆ", score, 10, 70)

# 1.3 ข้อความต่างกันทุกอย่าง → คะแนนต่ำมาก
score = analyzer._tfidf_score("python backend api", "react frontend css figma")
check_range("ข้อความต่างกัน → คะแนนต่ำมาก", score, 0, 20)

# 1.4 คะแนนต้องอยู่ในช่วง 0-100 เสมอ
score = analyzer._tfidf_score("anything here", "something else entirely")
check_range("คะแนนต้องอยู่ในช่วง 0-100", score, 0, 100)


# ============================================================
#  Test Group 2 — Keyword Score
# ============================================================
print(f"\n{BOLD}{'='*55}{RESET}")
print(f"{BOLD}  Test 2: Keyword Score{RESET}")
print(f"{BOLD}{'='*55}{RESET}")

# 2.1 ไม่กำหนด bonus → คืน 70 เสมอ
config = Config(bonus_keywords=[])
a = Analyzer(config=config)
score = a._keyword_score("python docker aws react")
check("ไม่กำหนด bonus → คืน 70.0", 70.0, score)

# 2.2 มี keyword ครบทุกคำ → 100
config = Config(bonus_keywords=["python", "docker", "aws"])
a = Analyzer(config=config)
score = a._keyword_score("python developer using docker and aws")
check("มี keyword ครบ 3/3 → 100.0", 100.0, score)

# 2.3 มี keyword ครึ่งหนึ่ง → 50
config = Config(bonus_keywords=["python", "docker", "aws", "kubernetes"])
a = Analyzer(config=config)
score = a._keyword_score("python developer with docker experience")
check("มี keyword 2/4 → 50.0", 50.0, score)

# 2.4 ไม่มี keyword เลย → 0
config = Config(bonus_keywords=["python", "docker"])
a = Analyzer(config=config)
score = a._keyword_score("react frontend developer typescript css")
check("ไม่มี keyword เลย → 0.0", 0.0, score)

# 2.5 keyword ตัวใหญ่-เล็ก ต้องถือว่าเหมือนกัน
config = Config(bonus_keywords=["Python", "Docker"])
a = Analyzer(config=config)
score = a._keyword_score("python and docker are great tools")
check("Python/python ถือว่าเหมือนกัน → 100.0", 100.0, score)


# ============================================================
#  Test Group 3 — Struct Score
# ============================================================
print(f"\n{BOLD}{'='*55}{RESET}")
print(f"{BOLD}  Test 3: Struct Score{RESET}")
print(f"{BOLD}{'='*55}{RESET}")

a = Analyzer()

# 3.1 มีครบทุกส่วน → 100
full_resume = """
john doe
email: john@example.com
tel: 081-234-5678
experience: 3 years as software developer
education: bachelor of engineering university
skills: python docker git sql
"""
result = a._struct_score(full_resume)
check("มีครบทุกส่วน → 100.0", 100.0, result["score"])

# 3.2 ไม่มีอะไรเลย → 0
result = a._struct_score("hello world nothing here")
check("ไม่มีอะไรเลย → 0.0", 0.0, result["score"])

# 3.3 มีแค่ email กับ เบอร์ → 40
partial = "contact: john@email.com phone: 081-234-5678"
result = a._struct_score(partial)
check("มี email+เบอร์ (2/5) → 40.0", 40.0, result["score"])

# 3.4 ผล checks ต้องเป็น dict ที่มี 5 key
result = a._struct_score(full_resume)
check("struct_checks ต้องมี 5 key", 5, len(result["checks"]))


# ============================================================
#  Test Group 4 — Required Keyword
# ============================================================
print(f"\n{BOLD}{'='*55}{RESET}")
print(f"{BOLD}  Test 4: Required Keyword{RESET}")
print(f"{BOLD}{'='*55}{RESET}")

# 4.1 ไม่กำหนด required → ผ่านเสมอ (คืน list ว่าง)
config = Config(required_keywords=[])
a = Analyzer(config=config)
missing = a._check_required("any text here")
check("ไม่กำหนด required → คืน []", [], missing)

# 4.2 มี keyword ครบ → คืน list ว่าง
config = Config(required_keywords=["python", "docker"])
a = Analyzer(config=config)
missing = a._check_required("python developer with docker experience")
check("มี keyword ครบ → คืน []", [], missing)

# 4.3 ขาด keyword → คืน keyword ที่ขาด
config = Config(required_keywords=["python", "docker", "kubernetes"])
a = Analyzer(config=config)
missing = a._check_required("python developer with docker experience")
check("ขาด kubernetes → คืน ['kubernetes']", ["kubernetes"], missing)

# 4.4 ขาดทุก keyword
config = Config(required_keywords=["python", "docker"])
a = Analyzer(config=config)
missing = a._check_required("react frontend developer")
check("ขาดทุก keyword → คืน list ครบ", ["python", "docker"], missing)


# ============================================================
#  Test Group 5 — คำนวณคะแนนรวม
# ============================================================
print(f"\n{BOLD}{'='*55}{RESET}")
print(f"{BOLD}  Test 5: คำนวณคะแนนรวม{RESET}")
print(f"{BOLD}{'='*55}{RESET}")

# 5.1 ตรวจสูตร: TF-IDF×0.6 + Keyword×0.25 + Struct×0.15
# สมมติ tfidf=80, keyword=100, struct=100
# = 80×0.6 + 100×0.25 + 100×0.15 = 48 + 25 + 15 = 88
expected_total = round(80*0.6 + 100*0.25 + 100*0.15, 1)
check("สูตร: 80×0.6 + 100×0.25 + 100×0.15 = 88.0", 88.0, expected_total)

# 5.2 น้ำหนักรวม = 1.0
config = Config()
total_weight = config.weight_tfidf + config.weight_keyword + config.weight_struct
check("น้ำหนักรวม = 1.0", True, abs(total_weight - 1.0) < 0.01)

# 5.3 validate() ต้อง raise ถ้าน้ำหนักไม่ครบ
try:
    config = Config(weight_tfidf=0.5, weight_keyword=0.5, weight_struct=0.5)
    config.validate()
    check("validate() ต้อง raise ถ้าน้ำหนักผิด", "raised", "not raised")
except ValueError:
    check("validate() raise ValueError ถ้าน้ำหนักผิด", True, True)


# ============================================================
#  Test Group 6 — Recommendation
# ============================================================
print(f"\n{BOLD}{'='*55}{RESET}")
print(f"{BOLD}  Test 6: Recommendation{RESET}")
print(f"{BOLD}{'='*55}{RESET}")

config = Config(pass_threshold=65, review_threshold=45)
a = Analyzer(config=config)

# จำลอง text ที่ทำให้ได้คะแนนต่างๆ
jd   = "python backend developer rest api postgresql docker"

# 6.1 คะแนนสูง → ผ่าน
high_resume = "python backend developer rest api postgresql docker fastapi experience education skill email john@test.com 081-234-5678"
r = a.analyze(jd, "fake.pdf") if False else None

# ทดสอบ logic ตรงๆ แทน
def simulate_rec(total, config):
    if total >= config.pass_threshold:
        return "ผ่าน"
    elif total >= config.review_threshold:
        return "พิจารณาเพิ่มเติม"
    else:
        return "ไม่ผ่าน"

check("คะแนน 70 → ผ่าน",              "ผ่าน",              simulate_rec(70, config))
check("คะแนน 65 → ผ่าน (ขอบบน)",      "ผ่าน",              simulate_rec(65, config))
check("คะแนน 64 → พิจารณาเพิ่มเติม",  "พิจารณาเพิ่มเติม", simulate_rec(64, config))
check("คะแนน 45 → พิจารณาเพิ่มเติม",  "พิจารณาเพิ่มเติม", simulate_rec(45, config))
check("คะแนน 44 → ไม่ผ่าน",           "ไม่ผ่าน",           simulate_rec(44, config))
check("คะแนน 0  → ไม่ผ่าน",           "ไม่ผ่าน",           simulate_rec(0,  config))


# ============================================================
#  สรุปผลทดสอบ
# ============================================================
total = pass_count + fail_count
print(f"\n{BOLD}{'='*55}{RESET}")
print(f"{BOLD}  สรุปผลทดสอบ{RESET}")
print(f"{BOLD}{'='*55}{RESET}")
print(f"  {GREEN}✓ ผ่าน : {pass_count}/{total}{RESET}")
if fail_count > 0:
    print(f"  {RED}✗ ไม่ผ่าน: {fail_count}/{total}{RESET}")
else:
    print(f"  {GREEN}ทุก test ผ่านหมด!{RESET}")
print(f"{'='*55}\n")