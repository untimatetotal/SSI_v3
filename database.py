# ============================================================
# database.py — SQLite database for CVScreener
# ============================================================

import sqlite3
import json
from pathlib import Path

DB_PATH = Path("cvscreener.db")


def get_db():
    """เปิด connection กับ SQLite database"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # ให้ดึงข้อมูลเป็น dict-like
    return conn


def init_db():
    """สร้างตารางถ้ายังไม่มี"""
    conn = get_db()
    c = conn.cursor()

    # ── ตาราง users ──────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT    NOT NULL UNIQUE,
            email       TEXT    NOT NULL UNIQUE,
            password    TEXT    NOT NULL,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # ── ตาราง history ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id           TEXT    PRIMARY KEY,
            user_id      INTEGER NOT NULL,
            timestamp    TEXT    NOT NULL,
            jd_label     TEXT,
            resume_count INTEGER DEFAULT 0,
            summary      TEXT,   -- JSON string
            results      TEXT,   -- JSON string
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    conn.commit()
    conn.close()
    print("[DB] Database initialized ✓")


# ── User functions ────────────────────────────────────────────

def create_user(username, email, hashed_password):
    """สร้าง user ใหม่ คืน user_id หรือ None ถ้าซ้ำ"""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
            (username.strip(), email.strip().lower(), hashed_password)
        )
        conn.commit()
        return c.lastrowid
    except sqlite3.IntegrityError:
        return None  # username หรือ email ซ้ำ
    finally:
        conn.close()


def get_user_by_username(username):
    """หา user จาก username คืน Row หรือ None"""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ?", (username.strip(),))
        return c.fetchone()
    finally:
        conn.close()


def get_user_by_id(user_id):
    """หา user จาก id คืน Row หรือ None"""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return c.fetchone()
    finally:
        conn.close()


# ── History functions ─────────────────────────────────────────

def save_history(history_id, user_id, timestamp, jd_label, resume_count, summary, results):
    """บันทึก history ของ user"""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO history
                (id, user_id, timestamp, jd_label, resume_count, summary, results)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            history_id,
            user_id,
            timestamp,
            jd_label,
            resume_count,
            json.dumps(summary, ensure_ascii=False),
            json.dumps(results, ensure_ascii=False),
        ))
        conn.commit()
    finally:
        conn.close()


def get_history_list(user_id):
    """ดึงรายการ history ของ user (ไม่รวม results เต็ม)"""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT id, timestamp, jd_label, resume_count, summary
            FROM history
            WHERE user_id = ?
            ORDER BY timestamp DESC
        """, (user_id,))
        rows = c.fetchall()
        items = []
        for row in rows:
            items.append({
                "id":            row["id"],
                "timestamp":     row["timestamp"],
                "jd_label":      row["jd_label"],
                "resume_count":  row["resume_count"],
                "summary":       json.loads(row["summary"] or "{}"),
            })
        return items
    finally:
        conn.close()


def get_history_by_id(history_id, user_id):
    """ดึง history เต็มของ user (ป้องกันดู history ของคนอื่น)"""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT * FROM history
            WHERE id = ? AND user_id = ?
        """, (history_id, user_id))
        row = c.fetchone()
        if not row:
            return None
        return {
            "id":            row["id"],
            "timestamp":     row["timestamp"],
            "jd_label":      row["jd_label"],
            "resume_count":  row["resume_count"],
            "summary":       json.loads(row["summary"] or "{}"),
            "results":       json.loads(row["results"] or "[]"),
        }
    finally:
        conn.close()


def delete_history(history_id, user_id):
    """ลบ history (เฉพาะของตัวเอง)"""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "DELETE FROM history WHERE id = ? AND user_id = ?",
            (history_id, user_id)
        )
        conn.commit()
        return c.rowcount > 0  # True = ลบสำเร็จ
    finally:
        conn.close()