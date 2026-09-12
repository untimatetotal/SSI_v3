# ============================================================
# database.py — SQLite database for CVScreener
# this file for enrollment & save history
# ============================================================
# v2: เพิ่ม search_candidates() เวอร์ชันชั่วคราวสำหรับ "ค้นหาจากคลัง"
#     (ฟีเจอร์นี้ในเวอร์ชันเต็มควรใช้ database_postgres.py แทน เมื่อ
#     Postgres กลับมาใช้ได้ — ตัวนี้เป็นแค่ fallback ชั่วคราว)
# ============================================================

import sqlite3
import json
import re
from pathlib import Path

DB_PATH = Path("cvscreener.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """สร้างตารางถ้ายังไม่มี และ migrate ถ้า schema เก่า"""
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT    NOT NULL UNIQUE,
            email        TEXT    NOT NULL UNIQUE,
            password     TEXT    NOT NULL,
            groq_api_key TEXT    NOT NULL DEFAULT '',
            created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)

    try:
        c.execute("ALTER TABLE users ADD COLUMN groq_api_key TEXT NOT NULL DEFAULT ''")
        print("[DB] Migrated: added groq_api_key column")
    except Exception:
        pass  # คอลัมน์มีอยู่แล้ว ไม่ต้อง error

    c.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id           TEXT    PRIMARY KEY,
            user_id      INTEGER NOT NULL,
            timestamp    TEXT    NOT NULL,
            jd_label     TEXT,
            resume_count INTEGER DEFAULT 0,
            summary      TEXT,
            results      TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    conn.commit()
    conn.close()
    print("[DB] Database initialized ✓")


# ── User functions ────────────────────────────────────────────

def create_user(username, email, hashed_password, groq_api_key=""):
    """สร้าง user ใหม่พร้อม groq_api_key — คืน user_id หรือ None ถ้าซ้ำ"""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO users (username, email, password, groq_api_key) VALUES (?, ?, ?, ?)",
            (username.strip(), email.strip().lower(), hashed_password, groq_api_key.strip())
        )
        conn.commit()
        return c.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_user_by_username(username):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ?", (username.strip(),))
        return c.fetchone()
    finally:
        conn.close()


def get_user_by_id(user_id):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return c.fetchone()
    finally:
        conn.close()


def get_user_groq_key(user_id) -> str:
    """ดึง Groq API Key ของ user"""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT groq_api_key FROM users WHERE id = ?", (user_id,))
        row = c.fetchone()
        return row["groq_api_key"] if row else ""
    finally:
        conn.close()


def update_groq_key(user_id, api_key: str) -> bool:
    """อัปเดต Groq API Key ของ user"""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE users SET groq_api_key = ? WHERE id = ?",
            (api_key.strip(), user_id)
        )
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


# ── History functions ─────────────────────────────────────────

def save_history(history_id, user_id, timestamp, jd_label, resume_count, summary, results):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO history
                (id, user_id, timestamp, jd_label, resume_count, summary, results)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            history_id, user_id, timestamp, jd_label, resume_count,
            json.dumps(summary, ensure_ascii=False),
            json.dumps(results, ensure_ascii=False),
        ))
        conn.commit()
    finally:
        conn.close()


def get_history_list(user_id):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT id, timestamp, jd_label, resume_count, summary
            FROM history WHERE user_id = ?
            ORDER BY timestamp DESC
        """, (user_id,))
        return [{
            "id":           row["id"],
            "timestamp":    row["timestamp"],
            "jd_label":     row["jd_label"],
            "resume_count": row["resume_count"],
            "summary":      json.loads(row["summary"] or "{}"),
        } for row in c.fetchall()]
    finally:
        conn.close()


def get_history_by_id(history_id, user_id):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT * FROM history WHERE id = ? AND user_id = ?
        """, (history_id, user_id))
        row = c.fetchone()
        if not row:
            return None
        return {
            "id":           row["id"],
            "timestamp":    row["timestamp"],
            "jd_label":     row["jd_label"],
            "resume_count": row["resume_count"],
            "summary":      json.loads(row["summary"] or "{}"),
            "results":      json.loads(row["results"] or "[]"),
        }
    finally:
        conn.close()


def delete_history(history_id, user_id):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "DELETE FROM history WHERE id = ? AND user_id = ?",
            (history_id, user_id)
        )
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


# ── Candidate search (ชั่วคราวสำหรับ SQLite) ────────────────────

def search_candidates(user_id, min_score=None, max_score=None, min_gpa=None,
                       min_experience=None, max_experience=None,
                       recommendation=None, jd_label_contains=None,
                       date_from=None, date_to=None, limit=100):
    """
    เวอร์ชันชั่วคราวสำหรับ SQLite — ค้นหาผู้สมัครข้าม session โดยสแกน
    history ทั้งหมดของ user แล้ว parse JSON ใน Python
    ⚠️ ช้ากว่า PostgreSQL (ไม่มี index บน field ข้างใน JSON) เหมาะกับ
    ข้อมูลปริมาณไม่มาก ใช้แทนกันไปก่อนจนกว่า Postgres จะกลับมาใช้ได้
    """
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM history WHERE user_id = ? ORDER BY timestamp DESC", (user_id,))
        rows = c.fetchall()
    finally:
        conn.close()

    def parse_exp(exp_text):
        if not exp_text:
            return None
        m = re.search(r'(\d+(?:\.\d+)?)', str(exp_text))
        return float(m.group(1)) if m else None

    results = []
    for row in rows:
        try:
            candidates = json.loads(row["results"] or "[]")
        except json.JSONDecodeError:
            continue

        for cand in candidates:
            score = cand.get("score") or 0
            if min_score is not None and score < min_score:
                continue
            if max_score is not None and score > max_score:
                continue

            gpa = cand.get("gpa")
            if min_gpa is not None and (gpa is None or gpa < min_gpa):
                continue

            exp_years = parse_exp(cand.get("experience"))
            if min_experience is not None and (exp_years is None or exp_years < min_experience):
                continue
            if max_experience is not None and (exp_years is None or exp_years > max_experience):
                continue

            if recommendation and cand.get("recommendation") != recommendation:
                continue
            if jd_label_contains and jd_label_contains.lower() not in (row["jd_label"] or "").lower():
                continue
            if date_from and row["timestamp"] < date_from:
                continue
            if date_to and row["timestamp"] > date_to:
                continue

            results.append({**cand, "jd_label": row["jd_label"], "created_at": row["timestamp"]})

    results.sort(key=lambda r: r.get("score", 0), reverse=True)
    return results[:limit]