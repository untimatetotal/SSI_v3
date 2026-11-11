# ============================================================
# purge_old_data.py — ลบข้อมูลผู้สมัครที่เก่ากว่ากำหนด (PDPA: ไม่เก็บข้อมูลนานเกินจำเป็น)
# ใช้:  python purge_old_data.py --days 365            (ดูรายการที่จะลบ ไม่ลบจริง)
#       python purge_old_data.py --days 365 --apply    (ลบจริง)
# ============================================================

import argparse
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database_postgres import get_db

RESULT_ROOT = Path("ResultFile")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT count(*) AS n FROM screening_sessions WHERE created_at < %s", (cutoff,))
        sessions = c.fetchone()["n"]
        c.execute("SELECT count(*) AS n FROM resume_profiles WHERE updated_at < %s", (cutoff,))
        profiles = c.fetchone()["n"]
        old_files = [f for f in RESULT_ROOT.rglob("*.pdf")
                     if datetime.fromtimestamp(f.stat().st_mtime, timezone.utc) < cutoff]
        print(f"ก่อน {cutoff:%Y-%m-%d}: ประวัติ {sessions} รายการ, ข้อมูลที่อ่านแล้ว {profiles} รายการ, ไฟล์ {len(old_files)} ไฟล์")
        if not args.apply:
            print("ยังไม่ได้ลบ ใส่ --apply เพื่อลบจริง")
            return
        c.execute("DELETE FROM screening_sessions WHERE created_at < %s", (cutoff,))
        c.execute("DELETE FROM resume_profiles WHERE updated_at < %s", (cutoff,))
        conn.commit()
    for f in old_files:
        try:
            os.remove(f)
        except OSError as e:
            print(f"ลบไม่ได้: {f} ({e})")
    print("ลบเรียบร้อย ไฟล์ที่ถูกลบจะหายจากคลังเมื่อค้นหาครั้งถัดไป")


if __name__ == "__main__":
    main()
