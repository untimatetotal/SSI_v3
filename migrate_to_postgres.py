# ============================================================
# migrate_to_postgres.py — ย้ายข้อมูลจาก cvscreener.db (SQLite เดิม)
# ไปยัง PostgreSQL schema ใหม่
# ============================================================

import sqlite3
import json
from pathlib import Path

import database_postgres as pg

SQLITE_PATH = Path("cvscreener.db")


def main():
    if not SQLITE_PATH.exists():
        print(f"[migrate] ไม่พบไฟล์ {SQLITE_PATH} — ตรวจสอบว่ารันสคริปต์นี้ในโฟลเดอร์ที่ถูกต้อง")
        return

    print("[migrate] กำลังสร้างตารางใน PostgreSQL (ถ้ายังไม่มี)...")
    pg.init_db()

    src = sqlite3.connect(SQLITE_PATH)
    src.row_factory = sqlite3.Row

    # ── 1. Migrate users ─────────────────────────────────────
    user_id_map = {}
    old_users = src.execute("SELECT * FROM users").fetchall()
    print(f"[migrate] พบ users {len(old_users)} รายการ")

    for u in old_users:
        new_id = pg.create_user(
            username=u["username"],
            email=u["email"],
            hashed_password=u["password"],
            groq_api_key=u["groq_api_key"] or "",
        )
        if new_id is None:
            print(f"  [skip] username '{u['username']}' มีอยู่แล้วในระบบใหม่ — ใช้ id เดิมที่มีอยู่แทน")
            existing = pg.get_user_by_username(u["username"])
            new_id = existing["id"] if existing else None
        else:
            print(f"  [ok]   {u['username']} → user_id ใหม่ = {new_id}")
        if new_id:
            user_id_map[u["id"]] = new_id

    # ── 2. Migrate history → screening_sessions + candidates ──
    old_history = src.execute("SELECT * FROM history").fetchall()
    print(f"\n[migrate] พบ history {len(old_history)} รายการ")

    migrated, skipped = 0, 0
    for h in old_history:
        new_user_id = user_id_map.get(h["user_id"])
        if new_user_id is None:
            print(f"  [skip] history {h['id']} — ไม่พบ user เจ้าของ (user_id เดิม={h['user_id']})")
            skipped += 1
            continue

        try:
            summary = json.loads(h["summary"] or "{}")
            results = json.loads(h["results"] or "[]")
        except json.JSONDecodeError:
            print(f"  [skip] history {h['id']} — JSON เสีย parse ไม่ได้")
            skipped += 1
            continue

        pg.save_history(
            history_id=h["id"],
            user_id=new_user_id,
            timestamp=h["timestamp"],
            jd_label=h["jd_label"],
            resume_count=h["resume_count"],
            summary=summary,
            results=results,
        )
        migrated += 1

    src.close()

    print(f"\n[migrate] เสร็จสิ้น")
    print(f"  ย้าย history สำเร็จ : {migrated} รายการ")
    print(f"  ข้าม               : {skipped} รายการ")
    print(f"\n[migrate] แนะนำขั้นตอนถัดไป:")
    print(f"  1. ตรวจสอบจำนวน row ใน candidates table ว่าตรงกับที่คาดไว้")
    print(f"     (SELECT COUNT(*) FROM candidates;)")
    print(f"  2. ทดสอบ login และดูประวัติผ่านหน้าเว็บจริงก่อนลบ cvscreener.db เดิม")
    print(f"  3. เก็บ cvscreener.db เดิมไว้เป็น backup อย่างน้อย 1-2 สัปดาห์หลัง migrate")


if __name__ == "__main__":
    main()