import sys
from pathlib import Path

import fitz

OUT = Path(__file__).parent / "fixtures"
THAI_FONT = "/usr/share/fonts/opentype/tlwg/Loma.otf"


def two_column_en(path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    left = ["CONTACT", "Phone: 081-234-5678", "Email: anan.test@example.com", "",
            "PERSONAL DETAILS", "Date of Birth: 2001-02-07", "Nationality: Thai", "",
            "SKILLS", "AutoCAD", "SolidWorks", "PLC Mitsubishi", "Lean Manufacturing"]
    right = ["Anan Testsuk", "Mechanical Engineer", "", "EDUCATION",
             "Bachelor of Engineering, Mechanical Engineering",
             "Test University, 2019 - 2023", "GPAX 3.41", "", "High School, GPA 3.90", "",
             "WORK EXPERIENCE",
             "Maintenance Engineer, Steel Works Co., Ltd.", "Jun 2023 - Present",
             "Preventive maintenance of rolling mill machines.", "",
             "Engineering Intern, Auto Parts Co.", "May 2022 - Jul 2022",
             "Supported production line improvement."]
    y = 60
    for line in left:
        page.insert_text((40, y), line, fontsize=10, fontname="helv")
        y += 16
    y = 60
    for line in right:
        page.insert_text((240, y), line, fontsize=10, fontname="helv")
        y += 16
    doc.save(path)


def thai_resume(path, html):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    css = f"@font-face {{font-family: th; src: url(Loma.otf);}} body {{font-family: th; font-size: 11pt;}}"
    archive = fitz.Archive(str(Path(THAI_FONT).parent))
    page.insert_htmlbox(fitz.Rect(40, 40, 555, 800), html, css=css, archive=archive)
    doc.save(path)


def scanned(src, path):
    src_doc = fitz.open(src)
    pix = src_doc[0].get_pixmap(dpi=200)
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, pixmap=pix)
    doc.save(path)


THAI_ENG = """<p>นายสมพงษ์ ทดสอบดี</p><p>วิศวกรอุตสาหการ</p>
<p>ข้อมูลส่วนตัว</p><p>วันเกิด: 15 กุมภาพันธ์ 2543</p>
<p>ประวัติการศึกษา</p><p>ปริญญาตรี วศ.บ. (วิศวกรรมอุตสาหการ) มหาวิทยาลัยทดสอบ</p><p>เกรดเฉลี่ยสะสม ๓.๒๕</p>
<p>ประสบการณ์การทำงาน</p><p>วิศวกรฝ่ายผลิต บริษัท เหล็กทดสอบ จำกัด</p><p>มกราคม 2565 - ปัจจุบัน</p>
<p>ควบคุมกระบวนการผลิตและลดของเสีย ด้วย Lean และ Kaizen</p>
<p>ทักษะ</p><p>AutoCAD, Microsoft Excel, ภาษาอังกฤษ TOEIC 650</p>"""

THAI_SALES = """<p>นางสาวมาลี ตัวอย่าง</p><p>พนักงานขาย</p>
<p>ข้อมูลส่วนตัว</p><p>อายุ 29 ปี</p>
<p>ประวัติการศึกษา</p><p>ปริญญาตรี บธ.บ. การตลาด เกรดเฉลี่ย 2.75</p>
<p>ประวัติการทำงาน</p><p>พนักงานขาย บริษัท ค้าปลีกทดสอบ</p><p>มิ.ย. 2560 - ธ.ค. 2565</p><p>ดูแลลูกค้าและยอดขายหน้าร้าน</p>"""

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    two_column_en(OUT / "en_two_column_mech.pdf")
    thai_resume(OUT / "th_ie_engineer.pdf", THAI_ENG)
    thai_resume(OUT / "th_sales.pdf", THAI_SALES)
    scanned(OUT / "th_ie_engineer.pdf", OUT / "th_ie_engineer_scanned.pdf")
    print("fixtures written to", OUT)
