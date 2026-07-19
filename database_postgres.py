# ============================================================
# database_postgres.py — PostgreSQL version ของ database.py
# ============================================================

import os
import re
import json
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

from crypto_utils import encrypt_value, decrypt_value

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("ไม่พบ DATABASE_URL ใน environment variables — ต้องตั้งค่าก่อนรัน")


@contextmanager
def get_db():
    """เปิด connection แบบ context manager — ปิด connection ให้อัตโนมัติเสมอ"""
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()


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
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = %s", (username.strip(),))
        return c.fetchone()


def get_user_by_id(user_id):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return c.fetchone()


def get_user_groq_key(user_id) -> str:
    """ดึงและถอดรหัส Groq API Key ของ user"""
    with get_db() as conn:
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
            insight = r.get("insight") or {}
            c.execute("""
                INSERT INTO candidates
                    (session_id, user_id, name, file_name, score, recommendation,
                     tfidf_score, keyword_score, struct_score, ai_score,
                     gpa, experience_years, jd_label, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                history_id, user_id, r.get("name"), r.get("file"), r.get("score"),
                r.get("recommendation"), r.get("tfidf"), r.get("keyword"), r.get("struct"),
                insight.get("ai_score"), r.get("gpa"),
                parse_experience_years(r.get("experience")),
                jd_label, timestamp,
            ))

        conn.commit()


def get_history_list(user_id):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, created_at AS timestamp, jd_label, resume_count, summary
            FROM screening_sessions WHERE user_id = %s
            ORDER BY created_at DESC
        """, (user_id,))
        return [dict(row) for row in c.fetchall()]


def get_history_by_id(history_id, user_id):
    with get_db() as conn:
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

def search_candidates(user_id, min_score=None, max_score=None, min_gpa=None,
                       min_experience=None, max_experience=None,
                       recommendation=None, jd_label_contains=None,
                       date_from=None, date_to=None, limit=100):
    """ค้นหาผู้สมัครข้าม session ทั้งหมดของ user ด้วยเงื่อนไขหลายมิติ"""
    conditions = ["user_id = %s", "deleted_at IS NULL"]
    params = [user_id]

    if min_score is not None:
        conditions.append("score >= %s"); params.append(min_score)
    if max_score is not None:
        conditions.append("score <= %s"); params.append(max_score)
    if min_gpa is not None:
        conditions.append("gpa >= %s"); params.append(min_gpa)
    if min_experience is not None:
        conditions.append("experience_years >= %s"); params.append(min_experience)
    if max_experience is not None:
        conditions.append("experience_years <= %s"); params.append(max_experience)
    if recommendation:
        conditions.append("recommendation = %s"); params.append(recommendation)
    if jd_label_contains:
        conditions.append("jd_label ILIKE %s"); params.append(f"%{jd_label_contains}%")
    if date_from:
        conditions.append("created_at >= %s"); params.append(date_from)
    if date_to:
        conditions.append("created_at <= %s"); params.append(date_to)

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT * FROM candidates
        WHERE {where_clause}
        ORDER BY score DESC
        LIMIT %s
    """
    params.append(limit)

    with get_db() as conn:
        c = conn.cursor()
        c.execute(query, params)
        return [dict(row) for row in c.fetchall()]