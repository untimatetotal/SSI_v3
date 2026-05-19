# test_pdfreader.py
import sys
sys.path.append(".")
from models import PDFReader

reader = PDFReader()

pdf_files = [
    "resume_nida.pdf",
    "resume_somchai (2).pdf",
    "resume_arthit.pdf",
]

for pdf in pdf_files:
    print("=" * 55)
    print(f"ไฟล์: {pdf}")
    print("=" * 55)
    text = reader.read(pdf)
    if text:
        print(text)
    else:
        print("อ่านไม่ได้หรือไม่มีข้อความ")
    print()