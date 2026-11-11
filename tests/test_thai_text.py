from datetime import date

from thai_text import (normalize_text, text_quality, find_date_ranges, merge_month_spans,
                       parse_birthdate, age_on, MatchText)


def test_pua_and_split_vowels_are_fixed():
    raw = "นายสมพงษ ขอมูลสวนตัว ทํางาน"
    assert normalize_text(raw) == "นายสมพงษ์ ข้อมูลส่วนตัว ทำงาน"


def test_thai_digits_and_double_sara_e():
    assert normalize_text("เกรด ๓.๒๕ เเละ") == "เกรด 3.25 และ"


def test_quality_drops_for_broken_text():
    assert text_quality("ภาษาไทยปกติ ทำงานได้ดี") > 0.9
    assert text_quality("�� ภาษา �") < 0.85


def test_thai_month_range_to_present():
    today = date(2026, 11, 11)
    ranges = find_date_ranges("วิศวกร\nมกราคม 2565 - ปัจจุบัน", today)
    assert ranges[0][0] == (2022, 1) and ranges[0][1] == (2026, 11)


def test_english_and_numeric_ranges():
    today = date(2026, 11, 11)
    r = find_date_ranges("May 2023 – Aug 2023\n06/2020 - 12/2021\nมิ.ย. 2560 - ธ.ค. 2565", today)
    spans = [(a, b) for a, b, *_ in r]
    assert ((2023, 5), (2023, 8)) in spans
    assert ((2020, 6), (2021, 12)) in spans
    assert ((2017, 6), (2022, 12)) in spans


def test_overlapping_jobs_are_not_double_counted():
    assert merge_month_spans([((2020, 1), (2020, 12)), ((2020, 6), (2021, 6))]) == 18


def test_birthdates_buddhist_and_iso():
    assert parse_birthdate("วันเกิด: 15 กุมภาพันธ์ 2543") == date(2000, 2, 15)
    assert parse_birthdate("Date of Birth: 2001-02-07") == date(2001, 2, 7)
    assert parse_birthdate("Birthday: 2 May 2001") == date(2001, 5, 2)
    assert age_on(date(2000, 2, 15), date(2026, 11, 11)) == 26


def test_match_english_word_boundary_and_thai():
    doc = MatchText("Skills: PLC programming, AutoCAD\nขยายงานขายหน้าร้าน")
    assert doc.find("plc")
    assert not doc.find("cad")
    assert doc.find("ขาย")
