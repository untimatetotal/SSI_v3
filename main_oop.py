# ============================================================
# main_oop.py — จุดเริ่มต้นโปรแกรม พร้อม Interactive Input
# ============================================================
# รัน: python main_oop.py
# โปรแกรมจะถามข้อมูลทีละขั้นตอนใน terminal
# ============================================================


import sys
import os
import shlex
sys.path.append(".")
from models import Config, ResumeScreener

 
 

# ============================================================
#  ฟังก์ชันช่วย — รับข้อมูลจากผู้ใช้
# ============================================================

def ask(question, default=None):
    """
    ถามคำถามและรับค่าจากผู้ใช้
    ถ้ากด Enter โดยไม่พิมพ์อะไร จะใช้ค่า default
    """
    if default:
        prompt = f"  {question} [{default}]: "
    else:
        prompt = f"  {question}: "
    answer = input(prompt).strip()
    return answer if answer else default


def ask_keywords(question):
    """
    รับ keyword หลายคำ คั่นด้วยช่องว่าง
    คืน list ของ keyword หรือ [] ถ้าไม่กรอก
    เช่น กรอก "python docker aws" → ["python", "docker", "aws"]
    """
    answer = input(
        f"  {question}\n"
        f"  (คั่นด้วยช่องว่าง หรือ Enter ข้ามได้): "
    ).strip()
    if not answer:
        return []
    return [kw.lower() for kw in answer.split()]


def ask_files(question):
    """
    รับชื่อไฟล์หลายไฟล์ คั่นด้วยช่องว่าง
    รองรับชื่อไฟล์ที่มีช่องว่างโดยใส่ " " ครอบ
    เช่น: resume1.pdf "resume somchai.pdf" resume2.pdf
    """
    print(f"  {question}")
    print('  (คั่นด้วยช่องว่าง เช่น: resume1.pdf "resume somchai.pdf")')
    answer = input("  > ").strip()
    if not answer:
        return []
    try:
        # shlex.split รองรับ "ชื่อไฟล์ที่มีช่องว่าง"
        return shlex.split(answer)
    except Exception:
        return answer.split()


def print_section(title):
    """แสดงหัวข้อแต่ละส่วน"""
    print(f"\n── {title} " + "─" * max(1, 42 - len(title)))


def ask_jd_input():
    """
    ให้ผู้ใช้เลือกว่าจะอ่าน JD จากไฟล์ หรือกรอกตรงใน terminal
    ถ้ากรอกตรง → สร้างไฟล์ jd_temp.txt แล้วคืน path นั้น
    """
    print_section("Job Description")
    print("  1 = อ่านจากไฟล์ที่มีอยู่แล้ว")
    print("  2 = กรอกตรงในนี้เลย (สร้างไฟล์ให้อัตโนมัติ)")
    choice = input("  เลือก [1]: ").strip() or "1"

    if choice == "1":
        # อ่านจากไฟล์ — วนถามจนกว่าจะพบไฟล์จริง
        while True:
            jd_path = ask("ชื่อไฟล์ JD", "job_description.txt")
            if os.path.exists(jd_path):
                print(f"  ✓ พบไฟล์: {jd_path}")
                return jd_path
            print(f"  ✗ ไม่พบไฟล์ '{jd_path}' กรุณาลองใหม่")

    else:
        # กรอกตรงใน terminal
        print("\n  กรอก Job Description (กด Enter 2 ครั้งเมื่อเสร็จ):")
        print("  ตัวอย่าง:")
        print("    Position: Backend Developer")
        print("    Skills: Python, Docker, PostgreSQL")
        print("    Experience: 2+ years")
        print("    Education: Bachelor degree")
        print("  " + "-" * 42)

        lines = []
        empty_count = 0
        while empty_count < 2:
            line = input("  ")
            if line == "":
                empty_count += 1
            else:
                empty_count = 0
                lines.append(line)

        jd_text = "\n".join(lines)

        if not jd_text.strip():
            print("  ✗ ไม่มีข้อความ ใช้ค่าว่างแทน")
            jd_text = "job description"

        # บันทึกเป็นไฟล์ชั่วคราว
        jd_path = "jd_temp.txt"
        with open(jd_path, "w", encoding="utf-8") as f:
            f.write(jd_text)

        print(f"\n  ✓ บันทึกเป็นไฟล์: {jd_path} ({len(jd_text)} ตัวอักษร)")
        return jd_path


# ============================================================
#  main() — ฟังก์ชันหลัก
# ============================================================

def main():
    print("\n" + "=" * 55)
    print("   ระบบคัดกรอง Resume — SSI v3")
    print("   TF-IDF + Rule-Based (ฟรี ไม่ใช้ AI)")
    print("=" * 55)

    # ── ขั้นที่ 1: Job Description ──────────────────────────
    jd_path = ask_jd_input()

    # ── ขั้นที่ 2: ไฟล์ Resume ──────────────────────────────
    print_section("ไฟล์ Resume (PDF)")
    while True:
        resume_paths = ask_files("ชื่อไฟล์ Resume ทั้งหมด")
        if not resume_paths:
            print("  ✗ กรุณาใส่ไฟล์อย่างน้อย 1 ไฟล์")
            continue

        found   = [f for f in resume_paths if os.path.exists(f)]
        missing = [f for f in resume_paths if not os.path.exists(f)]

        for f in found:   print(f"  ✓ {f}")
        for f in missing: print(f"  ✗ ไม่พบ: {f}")

        if found:
            resume_paths = found
            break
        print("  ✗ ไม่พบไฟล์เลย กรุณาลองใหม่")

    # ── ขั้นที่ 3: Required Keywords ────────────────────────
    print_section("คุณสมบัติบังคับ (Required)")
    print("  ผู้สมัครต้องมี keyword เหล่านี้")
    print("  ถ้าขาดคำใดคำหนึ่ง = ตัดออกทันที คะแนน 0")

    required_keywords = ask_keywords("keyword บังคับ เช่น: python docker")

    

    # วุฒิการศึกษาขั้นต่ำ
    print("\n  วุฒิการศึกษาขั้นต่ำ:")
    print("  1 = ปวส./อนุปริญญา")
    print("  2 = ปริญญาตรี")
    print("  3 = ปริญญาโท")
    print("  Enter = ไม่กำหนด")
    edu_map = {
         "1": ["diploma", "ปวส", "associate", "อนุปริญญา", "ประกาศนียบัตร",
          "bachelor", "bachalor", "ปริญญาตรี", "บัณฑิต", "วศ.บ", "บธ.บ", "วท.บ",
          "master", "ปริญญาโท", "graduate", "มหาบัณฑิต", "วศ.ม", "วท.ม"],

    "2": ["bachelor", "bachalor", "ปริญญาตรี", "บัณฑิต", "วศ.บ", "บธ.บ", "วท.บ",
          "master", "ปริญญาโท", "graduate", "มหาบัณฑิต", "วศ.ม", "วท.ม"],
          
    "3": ["master", "ปริญญาโท", "graduate", "มหาบัณฑิต", "วศ.ม", "วท.ม"],
    }

    edu_keywords = []
    edu_choice = input(" เลือก หมายเลข 1 2 3: ").strip()
    if edu_choice in edu_map: 
        edu_keywords = edu_map[edu_choice]
       
        print(f"  ✓ เพิ่ม keyword การศึกษา: {edu_keywords}")

   # edu_choice = input("  เลือก: ").strip()
   # if edu_choice in edu_map:
       # required_keywords.extend(edu_map[edu_choice])
       # print(f"  ✓ เพิ่ม keyword การศึกษา: {edu_map[edu_choice]}")

    if required_keywords:
        print(f"\n  สรุป keyword บังคับ: {required_keywords}")
    else:
        print("  (ไม่กำหนด keyword บังคับ)")

    # ── ขั้นที่ 4: Bonus Keywords ────────────────────────────
    print_section("Bonus Keywords (ได้คะแนนเพิ่ม)")
    print("  skill ที่อยากได้ มีแล้วได้คะแนนเพิ่ม ไม่มีก็ไม่ตัดออก")

    bonus_keywords = ask_keywords("bonus keyword เช่น: docker aws redis kubernetes")

    if bonus_keywords:
        print(f"  ✓ bonus keywords: {bonus_keywords}")
    else:
        print("  (ไม่กำหนด — ระบบใช้ค่ากลาง 70 คะแนน)")

    # ── ขั้นที่ 5: เกณฑ์คะแนน ───────────────────────────────
    print_section("เกณฑ์คะแนน (0-100)")

    try:
        pass_threshold   = int(ask("คะแนนขั้นต่ำที่ผ่าน",             "65"))
        review_threshold = int(ask("คะแนนขั้นต่ำที่พิจารณาเพิ่มเติม", "45"))
    except ValueError:
        print("  ✗ ค่าไม่ถูกต้อง ใช้ค่า default (65/45)")
        pass_threshold, review_threshold = 65, 45

    # ── ขั้นที่ 6: ตัวเลือกเพิ่มเติม ───────────────────────
    print_section("ตัวเลือกเพิ่มเติม")

    pass_only = (
        input("  แสดงเฉพาะที่ผ่านหรือไม่? (y/n) [n]: ")
        .strip().lower() == "y"
    )

    try:
        min_score = int(ask("แสดงเฉพาะคะแนน >=", "0"))
    except ValueError:
        min_score = 0

    output_file = ask("บันทึกผลลัพธ์เป็นไฟล์ชื่อ", "results.json")

    # ── สรุปก่อนรัน ──────────────────────────────────────────
    print("\n" + "=" * 55)
    print("  สรุปการตั้งค่า")
    print("=" * 55)
    print(f"  JD            : {jd_path}")
    print(f"  Resume        : {resume_paths}")
    print(f"  Required      : {required_keywords or 'ไม่กำหนด'}")
    print(f"  วุฒิขั้นต่ำ   : {edu_keywords or 'ไม่กำหนด'}")
    print(f"  Bonus         : {bonus_keywords or 'ไม่กำหนด'}")
    print(f"  Bonus         : {bonus_keywords or 'ไม่กำหนด'}")
    print(f"  ผ่านที่คะแนน  : {pass_threshold}")
    print(f"  พิจารณาที่    : {review_threshold}")
    print(f"  Pass only     : {'ใช่' if pass_only else 'ไม่'}")
    print(f"  Min score     : {min_score}")
    print(f"  Output file   : {output_file}")

    confirm = input("\n  เริ่มวิเคราะห์? (y/n) [y]: ").strip().lower()
    if confirm == "n":
        print("\n  ยกเลิกการวิเคราะห์")
        return

    # ── รันระบบ ──────────────────────────────────────────────
    config = Config(
        required_keywords=required_keywords,
        edu_keywords = edu_keywords, 
        bonus_keywords=bonus_keywords,
        pass_threshold=pass_threshold,
        review_threshold=review_threshold,
    )

    screener = ResumeScreener(config=config)

    results = screener.screen(
        jd_path=jd_path,
        resume_paths=resume_paths,
        min_score=min_score,
        pass_only=pass_only,
    )

    screener.print_results(results)
    screener.save_json(results, output=output_file)


# ── จุดเริ่มต้นโปรแกรม ──────────────────────────────────────
if __name__ == "__main__":
    main()