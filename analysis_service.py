# ============================================================
# analysis_service.py — วิเคราะห์ใบสมัครเป็นงานเบื้องหลัง พร้อมรายงานความคืบหน้า
# ============================================================

import shutil
import threading
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from database_postgres import get_profile, save_profile, save_history, get_notes
from hr_data import apply_hr_data
from llm import LLM
from models import Config
from requirements_ai import extract_requirements
from resume_parser import PARSER_VERSION, extract_text, parse_resume
from screening import score_candidate, sort_results, ai_summaries
from storage import file_sha1, sort_resume_file

JOB_TTL_SECONDS = 3600
_jobs = {}
_lock = threading.Lock()


def _public(job):
    return {k: job[k] for k in ("id", "status", "done", "total", "message", "result", "error")}


def get_job(job_id, user_id):
    with _lock:
        job = _jobs.get(job_id)
        if not job or job["user_id"] != user_id:
            return None
        return _public(job)


def _update(job_id, **fields):
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


def _cleanup():
    now = time.time()
    with _lock:
        for jid in [j for j, v in _jobs.items() if now - v["created"] > JOB_TTL_SECONDS]:
            _jobs.pop(jid, None)


def get_parsed(user_id, path, llm=None, sha1=None):
    """คืน (parsed, sha1) — ใช้ข้อมูลที่เคยอ่านไว้ถ้ามี, อ่านใหม่เมื่อเวอร์ชันเปลี่ยนหรือขอใช้ AI แต่ของเดิมไม่ได้ใช้ AI"""
    sha1 = sha1 or file_sha1(path)[0]
    cached = None
    try:
        cached = get_profile(user_id, sha1)
    except Exception:
        traceback.print_exc()
    if cached and cached["parser_version"] == PARSER_VERSION and (llm is None or cached["source"] == "ai"):
        return {"text": cached["text"] or "", "meta": cached["meta"] or {}, "profile": cached["profile"] or {}}, sha1
    parsed = parse_resume(str(path), llm)
    source = parsed["profile"].get("source", "rules")
    if cached and cached["parser_version"] == PARSER_VERSION and cached["source"] == "ai" and source != "ai":
        return {"text": cached["text"] or "", "meta": cached["meta"] or {}, "profile": cached["profile"] or {}}, sha1
    try:
        save_profile(user_id, sha1, PARSER_VERSION, source, parsed["text"], parsed["meta"], parsed["profile"])
    except Exception:
        traceback.print_exc()
    return parsed, sha1


def criteria_text(params) -> str:
    parts = []
    for label, key in (("ตำแหน่ง", "positions"), ("หน้าที่", "duties"), ("ทักษะ", "skills"),
                       ("สาขา", "fields"), ("อื่น ๆ", "general")):
        if params.get(key):
            parts.append(f"{label}: {', '.join(params[key])}")
    return "\n".join(parts)


def has_criteria(params) -> bool:
    return bool(criteria_text(params)) or any(params.get(k) is not None for k in (
        "min_gpa", "min_experience", "min_edu_level", "age_range", "salary_range", "gender"))


def start_job(user_id, work_dir, jd_paths, resumes, params, groq_key):
    _cleanup()
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = {"id": job_id, "user_id": user_id, "status": "running", "done": 0,
                         "total": len(resumes), "message": "กำลังเตรียมข้อมูล", "result": None,
                         "error": None, "created": time.time()}
    t = threading.Thread(target=_run, args=(job_id, user_id, work_dir, jd_paths, resumes, params, groq_key),
                         daemon=True)
    t.start()
    return job_id


def _run(job_id, user_id, work_dir, jd_paths, resumes, params, groq_key):
    try:
        result = run_analysis(job_id, user_id, jd_paths, resumes, params, groq_key)
        _update(job_id, status="done", result=result, message="เสร็จแล้ว")
    except AnalysisError as e:
        _update(job_id, status="error", error=str(e))
    except Exception:
        traceback.print_exc()
        _update(job_id, status="error", error="เกิดข้อผิดพลาดภายในระบบ ลองใหม่อีกครั้ง หากยังเป็นอยู่ให้แจ้งผู้ดูแล")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


class AnalysisError(Exception):
    pass


def run_analysis(job_id, user_id, jd_paths, resumes, params, groq_key):
    warnings = []
    llm = None
    if params.get("ai"):
        if groq_key:
            llm = LLM(groq_key)
        else:
            warnings.append("ไม่พบ Groq API Key ของบัญชีนี้ จึงวิเคราะห์โดยไม่ใช้ AI")

    _update(job_id, message="กำลังอ่าน Job Description")
    jd_text = "\n".join(extract_text(str(p))[0] for p in jd_paths).strip()
    if jd_paths and not jd_text:
        raise AnalysisError("อ่านข้อความจากไฟล์ Job Description / Job Specification ไม่ได้ ไฟล์อาจเป็นภาพสแกนที่ OCR อ่านไม่สำเร็จ "
                            "ลองใช้ไฟล์ที่เลือกข้อความได้ บันทึกเป็น .txt หรือนำไฟล์ออกแล้วคัดกรองตามเงื่อนไขอย่างเดียว")
    jd_label = params.get("jd_label") or (Path(jd_paths[0]).name.split("__", 1)[-1] if jd_paths else None)
    if not jd_label:
        titles = ", ".join(params.get("positions") or [])
        jd_label = (f"เงื่อนไข {titles}" if titles else "คัดกรองตามเงื่อนไข")[:60]

    positions, duties = list(params.get("positions") or []), list(params.get("duties") or [])
    skills, fields = list(params.get("skills") or []), list(params.get("fields") or [])
    requirement_source = jd_text or criteria_text(params)
    masterlist, auto_filled, requirements = [], [], None
    if llm and requirement_source:
        _update(job_id, message="AI กำลังสรุปข้อกำหนดตำแหน่ง")
        try:
            requirements = extract_requirements(llm, requirement_source)
            masterlist = requirements["groups"] or requirements["all_terms"]
            for label, current, key in (("ตำแหน่งงาน", positions, "positions"), ("ลักษณะงาน", duties, "duties"),
                                        ("ทักษะ", skills, "skills"), ("สาขาวิชา", fields, "fields_of_study")):
                if not current and requirements[key]:
                    current.extend(requirements[key])
                    auto_filled.append(label)
        except Exception as e:
            print(f"[warn] extract_requirements failed: {e}")
            warnings.append("AI สรุปข้อกำหนดจาก Job Description ไม่สำเร็จ จึงใช้เฉพาะเงื่อนไขที่กรอก")

    config = Config(
        position_keywords=positions, duties_keywords=duties, skill_keywords=skills,
        field_of_study_keywords=fields, general_keywords=params.get("general") or [],
        min_experience_years=params.get("min_experience"), min_gpa=params.get("min_gpa"),
        min_edu_level=params.get("min_edu_level"),
        age_range=params.get("age_range"), gender=params.get("gender"),
        salary_range=params.get("salary_range"),
        enable_special_score=params.get("enable_special", False),
        require_vehicle=params.get("require_vehicle", False),
        require_license=params.get("require_license", False),
        min_toeic_score=params.get("min_toeic"),
        ai_keyword_masterlist=masterlist,
        pass_threshold=params.get("pass_threshold", 60), review_threshold=params.get("review_threshold", 40),
    )
    if not config.has_keyword_criteria():
        warnings.append("ยังไม่ได้ตั้งเงื่อนไข คะแนนส่วน Keyword เป็น 0 (เปิดโหมด AI หรือใส่ Job Description เพื่อให้เติมเงื่อนไขอัตโนมัติ)")

    results, parsed_by_file, ai_extract_failed = [], {}, 0
    sha_by_name = {}
    for orig_name, path in resumes:
        try:
            sha_by_name[orig_name] = file_sha1(path)[0]
        except OSError:
            sha_by_name[orig_name] = None
    try:
        notes = get_notes(user_id, list(sha_by_name.values()))
    except Exception:
        traceback.print_exc()
        notes = {}
    for i, (orig_name, path) in enumerate(resumes, 1):
        _update(job_id, done=i - 1, message=f"กำลังอ่านใบสมัคร {i}/{len(resumes)}: {orig_name}")
        sha1 = sha_by_name.get(orig_name)
        try:
            parsed, _ = get_parsed(user_id, path, llm, sha1=sha1)
        except Exception:
            traceback.print_exc()
            parsed = {"text": "", "meta": {"method": "error"}, "profile": {}}
        hr = notes.get(sha1) if sha1 else None
        parsed = apply_hr_data(parsed, hr)
        if llm and (parsed.get("meta") or {}).get("ai_error"):
            ai_extract_failed += 1
        parsed_by_file[orig_name] = parsed
        result = score_candidate(parsed, config, orig_name)
        result["sha1"] = sha1
        result["hr_data"] = hr
        results.append(result)
    _update(job_id, done=len(resumes), message="กำลังจัดอันดับ")
    if ai_extract_failed:
        warnings.append(f"AI อ่านใบสมัครไม่สำเร็จ {ai_extract_failed} ฉบับ จึงใช้การอ่านแบบกฎสำรองสำหรับฉบับนั้น")

    results = sort_results(results)
    if llm and results:
        _update(job_id, message="AI กำลังสรุปผู้สมัครอันดับต้น")
        try:
            ai_summaries(llm, results, parsed_by_file, requirement_source or criteria_text(params))
        except Exception as e:
            print(f"[warn] ai_summaries failed: {e}")

    path_by_name = dict(resumes)
    for rank, r in enumerate(results, 1):
        r["rank"] = rank
        r["insight"] = None
        if path_by_name.get(r["file"]):
            sort_resume_file(r["file"], path_by_name[r["file"]], r["recommendation"], jd_label, user_id)

    usage = llm.usage if llm else {"in": 0, "out": 0, "calls": 0}
    summary = {
        "total": len(results),
        "passed": sum(1 for r in results if r["recommendation"] == "ผ่าน"),
        "review": sum(1 for r in results if r["recommendation"] == "พิจารณาเพิ่มเติม"),
        "failed": sum(1 for r in results if r["recommendation"] == "ไม่ผ่าน"),
        "ai_used": len(results) if masterlist else 0,
        "max_possible_score": 100 if masterlist else 75,
        "auto_filled": auto_filled,
        "auto_filled_source": "Job Description" if jd_text else "ตำแหน่งและเงื่อนไขที่กรอก",
        "requirements": requirements,
        "warnings": warnings,
        "tokens_input": usage["in"], "tokens_output": usage["out"],
        "tokens_used": usage["in"] + usage["out"], "ai_calls": usage.get("calls", 0),
    }
    history_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
    try:
        save_history(history_id=history_id, user_id=user_id,
                     timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
                     jd_label=jd_label, resume_count=len(resumes), summary=summary, results=results,
                     ai_mode="hybrid" if llm else "tfidf")
    except Exception:
        traceback.print_exc()
        summary["warnings"].append("บันทึกประวัติไม่สำเร็จ ผลลัพธ์นี้จะไม่อยู่ในหน้าประวัติ")
    return {"results": results, "summary": summary, "history_id": history_id}
