from datetime import date
from pathlib import Path

import pytest

from models import Config
from resume_parser import parse_resume
from screening import score_candidate

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 11)


@pytest.fixture(scope="module")
def parsed():
    return {f: parse_resume(str(FIX / f"{f}.pdf"), None, TODAY)
            for f in ("en_two_column_mech", "th_ie_engineer", "th_sales")}


def cfg(**kw):
    return Config(pass_threshold=60, review_threshold=40, **kw)


def test_english_query_finds_thai_resume(parsed):
    r = score_candidate(parsed["th_ie_engineer"], cfg(position_keywords=["industrial engineer"]), "a.pdf")
    assert r["keyword_score"] == 60 and "ตำแหน่งงาน" in r["evidence"]


def test_irrelevant_candidate_scores_low(parsed):
    r = score_candidate(parsed["th_sales"], cfg(position_keywords=["industrial engineer"]), "a.pdf")
    assert r["keyword_score"] == 0 and r["recommendation"] == "ไม่ผ่าน"


def test_low_gpa_is_rejected_with_reason(parsed):
    r = score_candidate(parsed["th_sales"], cfg(position_keywords=["sales"], min_gpa=3.0), "a.pdf")
    assert r["recommendation"] == "ไม่ผ่าน"
    assert r["reject_reasons"] == ["GPA 2.75 ต่ำกว่าเกณฑ์ขั้นต่ำ 3.00"]


def test_missing_value_becomes_review_not_pass(parsed):
    r = score_candidate(parsed["th_ie_engineer"],
                        cfg(position_keywords=["industrial engineer"], salary_range=(15000, 25000)), "a.pdf")
    assert r["recommendation"] in ("พิจารณาเพิ่มเติม", "ผ่าน")
    r2 = score_candidate(parsed["en_two_column_mech"], cfg(position_keywords=["maintenance"], age_range=(22, 35),
                                                         min_gpa=3.0), "a.pdf")
    assert r2["recommendation"] == "ผ่าน"


def test_unknown_gpa_needs_review(parsed):
    p = dict(parsed["th_sales"])
    p["profile"] = dict(p["profile"], gpa=None)
    r = score_candidate(p, cfg(position_keywords=["sales"], min_gpa=3.0), "a.pdf")
    assert r["recommendation"] == "พิจารณาเพิ่มเติม"
    assert r["review_reasons"][0].startswith("ไม่พบ GPA")


def test_unreadable_file_is_flagged():
    r = score_candidate({"text": "", "meta": {}, "profile": {}}, cfg(position_keywords=["x"]), "bad.pdf")
    assert r["error"] and r["recommendation"] == "ไม่ผ่าน"
