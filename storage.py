# ============================================================
# storage.py — ที่เก็บไฟล์ใบสมัครแยกตามผู้ใช้
# ============================================================

import hashlib
import shutil
from datetime import datetime
from pathlib import Path

RESULT_ROOT = Path("ResultFile")


def user_dirs(user_id):
    root = RESULT_ROOT / f"user_{int(user_id)}"
    return root / "Qualified", root / "TalentPool", root / "Uploaded"


def clean_folder(name):
    return "".join(c for c in (name or "") if c.isalnum() or c in " _-").strip()


def clean_filename(name):
    base = (name or "").replace("\\", "/").split("/")[-1].strip()
    base = "".join(c for c in base if c.isprintable())
    return "" if base in ("", ".", "..") or base.startswith(".") else base


def sort_resume_file(orig_name, tmp_path, recommendation, jd_label, user_id):
    """ผ่าน → Qualified/<ตำแหน่ง>_<วันที่>, อื่น ๆ → TalentPool/<ตำแหน่ง>"""
    qualified_dir, talent_pool_dir, _ = user_dirs(user_id)
    safe_position = clean_folder(jd_label or "unknown")[:50] or "unknown"
    file_name = clean_filename(orig_name) or "resume.pdf"
    if recommendation == "ผ่าน":
        dest_dir = qualified_dir / f"{safe_position}_{datetime.now().strftime('%Y-%m-%d')}"
    else:
        dest_dir = talent_pool_dir / safe_position
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy(tmp_path, dest_dir / file_name)
    except Exception as e:
        print(f"[warn] sort_resume_file failed: {e}")


_hash_cache = {}


def file_sha1(path):
    path = Path(path)
    st = path.stat()
    key = (str(path), st.st_mtime, st.st_size)
    digest = _hash_cache.get(key)
    if digest is None:
        digest = hashlib.sha1(path.read_bytes()).hexdigest()
        _hash_cache[key] = digest
    return digest, st.st_mtime


def user_pdf_files(user_id):
    qualified_dir, talent_pool_dir, uploaded_dir = user_dirs(user_id)
    files = []
    for base in (qualified_dir, talent_pool_dir):
        if base.exists():
            for sub in base.iterdir():
                if sub.is_dir():
                    files.extend((sub.name, f) for f in sub.iterdir() if f.suffix.lower() == ".pdf")
    if uploaded_dir.exists():
        files.extend(("Uploaded", f) for f in uploaded_dir.iterdir() if f.suffix.lower() == ".pdf")
    return files
