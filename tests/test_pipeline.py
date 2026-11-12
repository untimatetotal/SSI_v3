import io
import time
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


class FakeLLM:
    def __init__(self, *a, **k):
        self.usage = {"in": 100, "out": 50, "calls": 0}

    def chat_json(self, system, user, max_tokens=2000):
        self.usage["calls"] += 1
        if "job description" in system.lower():
            return {"positions": ["วิศวกรอุตสาหการ", "Industrial Engineer"], "duties": ["ควบคุมกระบวนการผลิต"],
                    "skills": ["Lean", "AutoCAD"], "fields_of_study": ["วิศวกรรมอุตสาหการ"],
                    "min_experience_years": 2, "min_degree": "bachelor", "min_gpa": None, "summary": "วิศวกร"}
        if "shortlisted" in system:
            return {"candidates": []}
        raise RuntimeError("AI resume extraction disabled in test")


@pytest.fixture
def app_client(monkeypatch, tmp_path):
    import database_postgres as db
    monkeypatch.setattr(db, "init_db", lambda: None)
    store, history = {}, {}
    monkeypatch.setattr(db, "get_profile", lambda u, s: store.get((u, s)))
    monkeypatch.setattr(db, "save_profile", lambda u, s, v, src, t, m, p: store.__setitem__(
        (u, s), {"parser_version": v, "source": src, "text": t, "meta": m, "profile": p}))
    monkeypatch.setattr(db, "save_history", lambda **kw: history.__setitem__(kw["history_id"], kw))
    monkeypatch.setattr(db, "get_user_groq_key", lambda u: "gsk_test")
    notes = {}
    monkeypatch.setattr(db, "get_notes", lambda u, lst: {k: v for k, v in notes.items() if k in lst})
    monkeypatch.setattr(db, "save_note", lambda u, sha, data: notes.__setitem__(sha, data) if data else notes.pop(sha, None))
    monkeypatch.setattr(db, "owns_resume", lambda u, sha: True)
    monkeypatch.setenv("SECRET_KEY", "test")
    monkeypatch.chdir(tmp_path)
    import importlib
    import analysis_service
    importlib.reload(analysis_service)
    monkeypatch.setattr(analysis_service, "LLM", FakeLLM)
    import app_flask
    importlib.reload(app_flask)
    monkeypatch.setattr(app_flask, "get_user_groq_key", lambda u: "gsk_test")
    app_flask.app.config["TESTING"] = True
    client = app_flask.app.test_client()
    with client.session_transaction() as s:
        s["user_id"] = 1
        s["username"] = "tester"
    client.notes = notes
    return client, history, store


def wait(client, job_id):
    for _ in range(200):
        r = client.get(f"/analyze/status/{job_id}")
        data = r.get_json()
        if data["status"] != "running":
            return data
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def files(*names):
    return [(io.BytesIO((FIX / n).read_bytes()), n) for n in names]


def test_criteria_only_background_job(app_client):
    client, history, store = app_client
    r = client.post("/analyze", data={
        "positions": '["industrial engineer"]', "min_gpa": "3.0", "min_experience": "2", "edu": "2",
        "ai_mode": "tfidf", "resumes": files("th_ie_engineer.pdf", "th_sales.pdf", "en_two_column_mech.pdf"),
    }, content_type="multipart/form-data")
    assert r.status_code == 202
    data = wait(client, r.get_json()["job_id"])
    assert data["status"] == "done", data
    res = {x["file"]: x for x in data["result"]["results"]}
    assert res["th_ie_engineer.pdf"]["recommendation"] == "ผ่าน"
    assert res["th_sales.pdf"]["recommendation"] == "ไม่ผ่าน"
    assert "GPA 2.75" in res["th_sales.pdf"]["reject_reasons"][0]
    assert data["result"]["results"][0]["file"] == "th_ie_engineer.pdf"
    assert len(history) == 1 and len(store) == 3
    assert Path("ResultFile/user_1/Qualified").exists()


def test_ai_fills_requirements_from_jd_and_falls_back(app_client):
    client, history, store = app_client
    jd = (io.BytesIO("รับสมัครวิศวกรอุตสาหการ ประสบการณ์ 2 ปี".encode()), "jd.txt")
    r = client.post("/analyze", data={"ai_mode": "hybrid", "jd_file": jd,
                                      "resumes": files("th_ie_engineer.pdf", "th_sales.pdf")},
                    content_type="multipart/form-data")
    data = wait(client, r.get_json()["job_id"])
    assert data["status"] == "done", data
    summary = data["result"]["summary"]
    assert "ตำแหน่งงาน" in summary["auto_filled"] and summary["max_possible_score"] == 100
    assert any("AI อ่านใบสมัครไม่สำเร็จ" in w for w in summary["warnings"])
    top = data["result"]["results"][0]
    assert top["file"] == "th_ie_engineer.pdf" and top["ai_score"] > 0


def test_validation_errors(app_client):
    client, *_ = app_client
    r = client.post("/analyze", data={"positions": "[]", "resumes": files("th_sales.pdf")},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    r = client.post("/analyze", data={"positions": '["x"]', "pass_threshold": "abc", "resumes": files("th_sales.pdf")},
                    content_type="multipart/form-data")
    assert r.status_code == 400 and "ตัวเลข" in r.get_json()["error"]
    r = client.post("/analyze", data={"positions": '["x"]'}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_unauthenticated_navigation_redirects(app_client):
    client, *_ = app_client
    with client.session_transaction() as s:
        s.clear()
    r = client.get("/", headers={"Sec-Fetch-Mode": "navigate", "Accept": "text/html"})
    assert r.status_code == 302
    r = client.get("/history", headers={"Accept": "*/*"})
    assert r.status_code == 401


def test_jd_extract_endpoint(app_client, monkeypatch):
    client, *_ = app_client
    import app_flask
    monkeypatch.setattr(app_flask, "LLM", FakeLLM)
    jd = (io.BytesIO("รับสมัครวิศวกรอุตสาหการ".encode()), "jd.txt")
    r = client.post("/api/jd/extract", data={"jd_file": jd}, content_type="multipart/form-data")
    data = r.get_json()
    assert r.status_code == 200 and "Industrial Engineer" in data["positions"]
    assert data["min_degree_level"] == 2


def test_library_position_match_cross_language():
    from app_flask import match_position_terms
    row = {"text": "นายทดสอบ\nวิศวกรรมอุตสาหการ\nควบคุมการผลิต", "profile": {"job_titles": ["Process Engineer"]}}
    rel, matched = match_position_terms(row, ["industrial engineer"])
    assert matched and rel >= 3
    assert match_position_terms(row, ["accountant"])[1] == []


def test_library_keyword_filter(app_client, monkeypatch):
    client, *_ = app_client
    import app_flask
    rows = [
        {"id": 1, "file_name": "a.pdf", "text": "Bachelor, Chiang Mai University", "profile": {}, "score": 70.0,
         "gpa": None, "experience_years": None, "age": None, "gender": None, "salary_expectation": None},
        {"id": 2, "file_name": "b.pdf", "text": "มหาวิทยาลัยเกษตรศาสตร์", "profile": {}, "score": 80.0,
         "gpa": None, "experience_years": None, "age": None, "gender": None, "salary_expectation": None},
    ]
    monkeypatch.setattr(app_flask, "sync_library", lambda *a, **k: None)
    monkeypatch.setattr(app_flask, "library_search", lambda *a, **k: [dict(r) for r in rows])
    data = client.get("/api/candidates/search?keyword=" + "ม.เชียงใหม่").get_json()
    assert [c["file_name"] for c in data["candidates"]] == ["a.pdf"]
    assert data["candidates"][0]["matched_keywords"]


def test_hr_data_overrides_extracted_values(app_client):
    client, history, store = app_client
    import hashlib
    sha = hashlib.sha1((FIX / "th_sales.pdf").read_bytes()).hexdigest()
    r = client.post(f"/api/notes/{sha}", json={"gpa": "abc"})
    assert r.status_code == 400
    r = client.post(f"/api/notes/{sha}", json={"gpa": "3.40", "salary_expectation": "22,000", "tags": "โทรคัดกรองแล้ว", "note": "สนใจงานกะ"})
    assert r.status_code == 200 and client.notes[sha]["salary_expectation"] == 22000
    r = client.post("/analyze", data={"positions": '["sales"]', "min_gpa": "3.0", "salary_min": "20000", "salary_max": "25000",
                                      "ai_mode": "tfidf", "resumes": files("th_sales.pdf")}, content_type="multipart/form-data")
    res = wait(client, r.get_json()["job_id"])["result"]["results"][0]
    assert res["sha1"] == sha and res["gpa"] == 3.4 and not res["reject_reasons"]
    assert res["keyword_breakdown"]["เงินเดือน"] == 2 and "ข้อมูลจาก HR" in res["evidence"]
    assert res["hr_data"]["tags"] == ["โทรคัดกรองแล้ว"]
    r = client.post(f"/api/notes/{sha}", json={})
    assert sha not in client.notes
