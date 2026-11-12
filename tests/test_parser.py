from datetime import date
from pathlib import Path

import pytest

from resume_parser import parse_resume, find_gpa, rule_profile

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 11)


@pytest.fixture(scope="module", autouse=True)
def fixtures():
    if not (FIX / "th_ie_engineer.pdf").exists():
        import subprocess, sys
        subprocess.run([sys.executable, str(Path(__file__).parent / "make_fixtures.py")], check=True)


def test_gpa_prefers_highest_degree():
    text = "ปริญญาโท วศ.ม. GPAX 3.83\nปริญญาตรี วศ.บ. เกรดเฉลี่ยสะสม 3.82\nมัธยม GPA 3.69"
    gpa, level, _ = find_gpa(text)
    assert gpa == 3.83 and level == 3


def test_gpa_skips_high_school_when_degree_exists():
    gpa, level, _ = find_gpa("Bachelor of Engineering\nGPAX 3.41\nHigh School, GPA 3.90")
    assert gpa == 3.41


def test_internship_months_are_separate():
    text = ("WORK EXPERIENCE\nMaintenance Engineer, Steel Co.\nJun 2023 - Present\n\n"
            "Engineering Intern, Auto Co.\nMay 2022 - Jul 2022")
    p = rule_profile(text, TODAY)
    assert p["experience_months"] == 42 and p["internship_months"] == 3


def test_education_years_are_not_experience():
    p = rule_profile("EDUCATION\nBachelor, Test University 2019 - 2023\nSKILLS\nExcel", TODAY)
    assert p["experience_months"] is None


def test_thai_pdf_with_broken_font_codes():
    r = parse_resume(str(FIX / "th_ie_engineer.pdf"), None, TODAY)
    p = r["profile"]
    assert "ข้อมูลส่วนตัว" in r["text"]
    assert p["gpa"] == 3.25 and p["age"] == 26 and p["experience_months"] == 59
    assert p["languages"]["TOEIC"] == 650


def test_two_column_english_pdf():
    p = parse_resume(str(FIX / "en_two_column_mech.pdf"), None, TODAY)["profile"]
    assert p["gpa"] == 3.41 and p["highest_degree_level"] == 2
    assert p["experience_months"] == 42 and p["age"] == 25


def test_scanned_thai_pdf_uses_ocr():
    r = parse_resume(str(FIX / "th_ie_engineer_scanned.pdf"), None, TODAY)
    assert r["meta"]["method"] == "ocr"
    assert r["profile"]["gpa"] == 3.25


def test_folder_names_keep_thai_vowels():
    from storage import clean_folder
    assert clean_folder("เงื่อนไข Marketing") == "เงื่อนไข Marketing"
    assert clean_folder("../a/b") == "ab"
