# ============================================================
# database_postgres.py — PostgreSQL version ของ database.py
# ============================================================

import os
import re
import json
import time
import threading
import traceback
from decimal import Decimal
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pg_pool

from crypto_utils import encrypt_value, decrypt_value

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("ไม่พบ DATABASE_URL ใน environment variables — ต้องตั้งค่าก่อนรัน")


POOL_MAX = int(os.environ.get("DB_POOL_MAX", "10"))
IDLE_PING_SECONDS = 20

_pool = None
_pool_lock = threading.Lock()
_last_used = {}


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = pg_pool.ThreadedConnectionPool(
                    1, POOL_MAX, DATABASE_URL,
                    cursor_factory=psycopg2.extras.RealDictCursor,
                    keepalives=1, keepalives_idle=30,
                    keepalives_interval=10, keepalives_count=3,
                )
    return _pool


def _is_healthy(conn):
    if conn.closed:
        return False
    if time.time() - _last_used.get(id(conn), 0) < IDLE_PING_SECONDS:
        return True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.rollback()
        return True
    except Exception:
        return False


@contextmanager
def get_db(readonly=False):
    """ยืม connection จาก pool — ตรวจสุขภาพก่อนใช้ และคืนเข้า pool เสมอ"""
    db_pool = _get_pool()
    conn = db_pool.getconn()
    if not _is_healthy(conn):
        db_pool.putconn(conn, close=True)
        conn = db_pool.getconn()
    broken = False
    if readonly:
        conn.autocommit = True
    try:
        yield conn
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        broken = True
        raise
    finally:
        try:
            if readonly and not broken and not conn.closed:
                conn.autocommit = False
            elif not broken and not conn.closed:
                conn.rollback()
        except Exception:
            broken = True
        _last_used[id(conn)] = time.time()
        db_pool.putconn(conn, close=broken or bool(conn.closed))


def init_db():
    """รัน schema_postgres.sql เพื่อสร้างตาราง (ถ้ายังไม่มี)"""
    schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema_postgres.sql")
    with open(schema_path, encoding="utf-8") as f:
        schema_sql = f.read()
    with get_db() as conn:
        c = conn.cursor()
        c.execute(schema_sql)
        conn.commit()
    print("[DB] Database initialized (PostgreSQL) OK")


def parse_experience_years(exp_text):
    if not exp_text:
        return None
    match = re.search(r'(\d+(?:\.\d+)?)', str(exp_text))
    return float(match.group(1)) if match else None


SECTION_HEADERS = {
    "education", "other activities", "experience", "work experience", "skills",
    "summary", "profile", "objective", "references", "projects", "contact",
    "personal information", "languages", "certifications", "activities",
    "ประวัติการศึกษา", "ประสบการณ์", "ทักษะ", "ข้อมูลส่วนตัว",
}


def clean_name(name, file_name):
    n = (name or "").strip()
    if not n or n.lower() in SECTION_HEADERS:
        stem = os.path.splitext(os.path.basename(file_name or ""))[0]
        return stem or "ไม่ทราบชื่อ"
    return n


def _to_number(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _escape_like(text):
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ── User functions ────────────────────────────────────────────

def create_user(username, email, hashed_password, groq_api_key=""):
    """สร้าง user ใหม่ — เข้ารหัส groq_api_key ก่อนเก็บลง database เสมอ"""
    encrypted_key = encrypt_value(groq_api_key.strip()) if groq_api_key else ""
    with get_db() as conn:
        c = conn.cursor()
        try:
            c.execute("""
                INSERT INTO users (username, email, password_hash, groq_api_key_encrypted)
                VALUES (%s, %s, %s, %s) RETURNING id
            """, (username.strip(), email.strip().lower(), hashed_password, encrypted_key))
            user_id = c.fetchone()["id"]
            conn.commit()
            return user_id
        except psycopg2.IntegrityError:
            conn.rollback()
            return None


def get_user_by_username(username):
    with get_db(readonly=True) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = %s", (username.strip(),))
        return c.fetchone()


def get_user_by_id(user_id):
    with get_db(readonly=True) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return c.fetchone()


def get_user_groq_key(user_id) -> str:
    """ดึงและถอดรหัส Groq API Key ของ user"""
    with get_db(readonly=True) as conn:
        c = conn.cursor()
        c.execute("SELECT groq_api_key_encrypted FROM users WHERE id = %s", (user_id,))
        row = c.fetchone()
        if not row or not row["groq_api_key_encrypted"]:
            return ""
        return decrypt_value(row["groq_api_key_encrypted"])


def update_groq_key(user_id, api_key: str) -> bool:
    """เข้ารหัสแล้วอัปเดต Groq API Key ของ user"""
    encrypted_key = encrypt_value(api_key.strip()) if api_key else ""
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE users SET groq_api_key_encrypted = %s, updated_at = now() WHERE id = %s",
            (encrypted_key, user_id)
        )
        conn.commit()
        return c.rowcount > 0


# ── Session (history) functions ───────────────────────────────

def _valid_gpa(value):
    v = _to_number(value)
    return v if v is not None and 0 <= v <= 4 else None


def save_history(history_id, user_id, timestamp, jd_label, resume_count, summary, results, ai_mode="tfidf"):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO screening_sessions
                (id, user_id, created_at, jd_label, resume_count, ai_mode, summary, raw_results)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            history_id, user_id, timestamp, jd_label, resume_count, ai_mode,
            json.dumps(summary, ensure_ascii=False),
            json.dumps(results, ensure_ascii=False),
        ))

        for r in results:
            c.execute("""
                INSERT INTO candidates
                    (session_id, user_id, name, file_name, score, recommendation,
                     tfidf_score, keyword_score, struct_score, ai_score,
                     gpa, experience_years, jd_label, created_at,
                     age, gender, salary_expectation, reject_reasons, review_reasons)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                history_id, user_id, clean_name(r.get("name"), r.get("file")), r.get("file"),
                r.get("score"), r.get("recommendation") or None, None,
                r.get("keyword_score"), r.get("struct_score"), r.get("ai_score"),
                _valid_gpa(r.get("gpa")),
                parse_experience_years(r.get("experience")),
                jd_label, timestamp,
                r.get("age"), r.get("gender"), r.get("salary_expectation"),
                json.dumps(r.get("reject_reasons") or [], ensure_ascii=False),
                json.dumps(r.get("review_reasons") or [], ensure_ascii=False),
            ))

        conn.commit()


def get_history_list(user_id):
    with get_db(readonly=True) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, created_at AS timestamp, jd_label, resume_count, summary
            FROM screening_sessions WHERE user_id = %s
            ORDER BY created_at DESC
        """, (user_id,))
        return [dict(row) for row in c.fetchall()]


def get_history_by_id(history_id, user_id):
    with get_db(readonly=True) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, created_at AS timestamp, jd_label, resume_count, summary,
                   raw_results AS results
            FROM screening_sessions WHERE id = %s AND user_id = %s
        """, (history_id, user_id))
        row = c.fetchone()
        return dict(row) if row else None


def delete_history(history_id, user_id):
    """ลบ session — candidates ที่เชื่อมอยู่จะถูกลบตาม (ON DELETE CASCADE ใน schema)"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "DELETE FROM screening_sessions WHERE id = %s AND user_id = %s",
            (history_id, user_id)
        )
        conn.commit()
        return c.rowcount > 0


# ── Candidate search ──────────────────────────────────────────

CANDIDATE_COLUMNS = (
    "id, session_id, name, file_name, score, recommendation, tfidf_score, "
    "keyword_score, struct_score, ai_score, gpa, experience_years, jd_label, "
    "created_at, age, gender, salary_expectation, reject_reasons"
)


def _normalize_candidate(row):
    d = dict(row)
    for key, value in list(d.items()):
        if isinstance(value, Decimal):
            d[key] = float(value)
    if d.get("created_at") is not None:
        d["created_at"] = d["created_at"].isoformat(timespec="seconds")
    d["name"] = clean_name(d.get("name"), d.get("file_name"))
    d["file"] = d.get("file_name")
    exp = d.get("experience_years")
    d["experience"] = f"{exp:g} ปี" if exp is not None else None
    return d


def search_candidates(user_id, min_score=None, max_score=None, min_gpa=None,
                       min_experience=None, max_experience=None,
                       recommendation=None, jd_label_contains=None,
                       date_from=None, date_to=None,
                       age_min=None, age_max=None, gender=None,
                       salary_min=None, salary_max=None, limit=100):
    """ค้นหาผู้สมัครข้าม session ของ user — คืนเฉพาะแถวล่าสุดต่อ (ไฟล์, JD)"""
    conditions = []
    params = []

    def add(sql, value):
        conditions.append(sql)
        params.append(value)

    if min_score is not None:      add("score >= %s", min_score)
    if max_score is not None:      add("score <= %s", max_score)
    if min_gpa is not None:        add("gpa >= %s", min_gpa)
    if min_experience is not None: add("experience_years >= %s", min_experience)
    if max_experience is not None: add("experience_years <= %s", max_experience)
    if recommendation:             add("recommendation = %s", recommendation)
    if age_min is not None:        add("age >= %s", age_min)
    if age_max is not None:        add("age <= %s", age_max)
    if gender:                     add("gender = %s", gender)
    if salary_min is not None:     add("salary_expectation >= %s", salary_min)
    if salary_max is not None:     add("salary_expectation <= %s", salary_max)
    if date_from:                  add("created_at >= %s", date_from)
    if date_to:                    add("created_at <= %s", date_to)

    labels = [jd_label_contains] if isinstance(jd_label_contains, str) else list(jd_label_contains or [])
    labels = [x.strip() for x in labels if x and x.strip()]
    if labels:
        conditions.append("(" + " OR ".join(["jd_label ILIKE %s"] * len(labels)) + ")")
        params.extend(f"%{_escape_like(x)}%" for x in labels)

    outer_where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    query = f"""
        SELECT {CANDIDATE_COLUMNS} FROM (
            SELECT DISTINCT ON (COALESCE(file_name, id::text), COALESCE(jd_label, ''))
                   {CANDIDATE_COLUMNS}
            FROM candidates
            WHERE user_id = %s AND deleted_at IS NULL
            ORDER BY COALESCE(file_name, id::text), COALESCE(jd_label, ''), created_at DESC
        ) latest
        {outer_where}
        ORDER BY score DESC NULLS LAST
        LIMIT %s
    """
    with get_db(readonly=True) as conn:
        c = conn.cursor()
        c.execute(query, [user_id] + params + [limit])
        return [_normalize_candidate(row) for row in c.fetchall()]


# ── Resume library (คลังใบสมัคร: ข้อความ + ข้อมูลที่สกัดจากไฟล์) ─────

def library_index(user_id):
    with get_db(readonly=True) as conn:
        c = conn.cursor()
        c.execute("SELECT id, sha1, folder, file_name, file_mtime, profile->>'parser_version' AS parser_version FROM resume_library WHERE user_id = %s", (user_id,))
        return {row["sha1"].strip(): dict(row) for row in c.fetchall()}


def library_apply(user_id, inserts, updates, deletes):
    with get_db() as conn:
        c = conn.cursor()
        for r in inserts:
            c.execute("""
                INSERT INTO resume_library
                    (user_id, sha1, folder, file_name, file_mtime, text,
                     gpa, experience_years, age, gender, salary_expectation, profile)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, sha1) DO UPDATE
                SET folder = EXCLUDED.folder, file_name = EXCLUDED.file_name,
                    file_mtime = EXCLUDED.file_mtime, text = EXCLUDED.text, gpa = EXCLUDED.gpa,
                    experience_years = EXCLUDED.experience_years, age = EXCLUDED.age,
                    gender = EXCLUDED.gender, salary_expectation = EXCLUDED.salary_expectation,
                    profile = EXCLUDED.profile, indexed_at = now()
            """, (user_id, r["sha1"], r["folder"], r["file_name"], r["file_mtime"], r["text"],
                  _valid_gpa(r.get("gpa")), r.get("experience_years"), r.get("age"),
                  r.get("gender"), r.get("salary_expectation"),
                  json.dumps(r.get("profile") or {}, ensure_ascii=False)))
        for row_id, folder, file_name, mtime in updates:
            c.execute("""UPDATE resume_library SET folder = %s, file_name = %s, file_mtime = %s
                         WHERE id = %s AND user_id = %s""", (folder, file_name, mtime, row_id, user_id))
        if deletes:
            c.execute("DELETE FROM resume_library WHERE user_id = %s AND id = ANY(%s)", (user_id, list(deletes)))
        conn.commit()


def library_search(user_id, min_gpa=None, min_experience=None, age_min=None, age_max=None,
                   gender=None, salary_min=None, salary_max=None):
    """ค้นคลัง — ใช้ค่าที่ HR กรอกเอง (candidate_notes) แทนค่าที่อ่านจากไฟล์เมื่อมี"""
    conditions, params = [], []

    def add(sql, value):
        conditions.append(sql)
        params.append(value)

    if min_gpa is not None:        add("(x.gpa >= %s OR x.gpa IS NULL)", min_gpa)
    if min_experience is not None: add("(x.experience_years >= %s OR x.experience_years IS NULL)", min_experience)
    if age_min is not None:        add("(x.age >= %s OR x.age IS NULL)", age_min)
    if age_max is not None:        add("(x.age <= %s OR x.age IS NULL)", age_max)
    if gender:                     add("(x.gender = %s OR x.gender IS NULL)", gender)
    if salary_min is not None:     add("(x.salary_expectation >= %s OR x.salary_expectation IS NULL)", salary_min)
    if salary_max is not None:     add("(x.salary_expectation <= %s OR x.salary_expectation IS NULL)", salary_max)

    query = f"""
        SELECT * FROM (
            SELECT l.id, l.sha1, l.folder, l.file_name, l.text, l.indexed_at, l.profile,
                   COALESCE((n.data->>'gpa')::numeric, l.gpa) AS gpa,
                   COALESCE((n.data->>'experience_years')::numeric, l.experience_years) AS experience_years,
                   COALESCE((n.data->>'age')::int, l.age) AS age,
                   COALESCE(n.data->>'gender', l.gender) AS gender,
                   COALESCE((n.data->>'salary_expectation')::numeric, l.salary_expectation) AS salary_expectation,
                   n.data AS hr_data,
                   c.name, c.score, c.recommendation, c.keyword_score, c.ai_score, c.struct_score,
                   c.jd_label, c.reject_reasons, c.review_reasons, c.created_at
            FROM resume_library l
            LEFT JOIN candidate_notes n ON n.user_id = l.user_id AND n.sha1 = l.sha1
            LEFT JOIN LATERAL (
                SELECT name, score, recommendation, keyword_score, ai_score, struct_score,
                       jd_label, reject_reasons, review_reasons, created_at
                FROM candidates
                WHERE user_id = l.user_id AND file_name = l.file_name AND deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
            ) c ON true
            WHERE l.user_id = %s
        ) x
        {"WHERE " + " AND ".join(conditions) if conditions else ""}
    """
    with get_db(readonly=True) as conn:
        c = conn.cursor()
        c.execute(query, [user_id] + params)
        rows = []
        for row in c.fetchall():
            d = dict(row)
            for key, value in list(d.items()):
                if isinstance(value, Decimal):
                    d[key] = float(value)
            for key in ("created_at", "indexed_at"):
                if d.get(key) is not None:
                    d[key] = d[key].isoformat(timespec="seconds")
            d["sha1"] = (d.get("sha1") or "").strip()
            d["name"] = clean_name(d.get("name"), d.get("file_name"))
            d["file"] = d.get("file_name")
            exp = d.get("experience_years")
            d["experience"] = f"{exp:g} ปี" if exp is not None else None
            rows.append(d)
        return rows


# ── ข้อมูลที่ HR กรอกเองต่อใบสมัคร ─────────────────────────────

def get_notes(user_id, sha1_list):
    sha1_list = [s for s in sha1_list if s]
    if not sha1_list:
        return {}
    with get_db(readonly=True) as conn:
        c = conn.cursor()
        c.execute("SELECT sha1, data, updated_at FROM candidate_notes WHERE user_id = %s AND sha1 = ANY(%s)",
                  (user_id, sha1_list))
        return {row["sha1"].strip(): dict(row["data"] or {}, updated_at=row["updated_at"].isoformat(timespec="seconds"))
                for row in c.fetchall()}


def owns_resume(user_id, sha1):
    with get_db(readonly=True) as conn:
        c = conn.cursor()
        c.execute("""SELECT 1 FROM resume_profiles WHERE user_id = %s AND sha1 = %s
                     UNION SELECT 1 FROM resume_library WHERE user_id = %s AND sha1 = %s LIMIT 1""",
                  (user_id, sha1, user_id, sha1))
        return c.fetchone() is not None


def save_note(user_id, sha1, data):
    with get_db() as conn:
        c = conn.cursor()
        if data:
            c.execute("""
                INSERT INTO candidate_notes (user_id, sha1, data) VALUES (%s, %s, %s)
                ON CONFLICT (user_id, sha1) DO UPDATE SET data = EXCLUDED.data, updated_at = now()
            """, (user_id, sha1, json.dumps(data, ensure_ascii=False)))
        else:
            c.execute("DELETE FROM candidate_notes WHERE user_id = %s AND sha1 = %s", (user_id, sha1))
        conn.commit()


# ── Resume profile cache (อ่านไฟล์ครั้งเดียว ใช้ซ้ำได้) ─────────────

def get_profile(user_id, sha1):
    with get_db(readonly=True) as conn:
        c = conn.cursor()
        c.execute("""SELECT parser_version, source, text, meta, profile
                     FROM resume_profiles WHERE user_id = %s AND sha1 = %s""", (user_id, sha1))
        row = c.fetchone()
        return dict(row) if row else None


def save_profile(user_id, sha1, parser_version, source, text, meta, profile):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO resume_profiles (user_id, sha1, parser_version, source, text, meta, profile)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, sha1) DO UPDATE
            SET parser_version = EXCLUDED.parser_version, source = EXCLUDED.source, text = EXCLUDED.text,
                meta = EXCLUDED.meta, profile = EXCLUDED.profile, updated_at = now()
        """, (user_id, sha1, parser_version, source, text,
              json.dumps(meta or {}, ensure_ascii=False), json.dumps(profile or {}, ensure_ascii=False)))
        conn.commit()
