import shutil
import sys
from pathlib import Path

ROOT = Path("ResultFile")
LEGACY = ["Qualified", "TalentPool", "Uploaded"]


def main():
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        sys.exit("usage: python migrate_repository_to_user.py <user_id>")
    target = ROOT / f"user_{int(sys.argv[1])}"
    moved = 0
    for name in LEGACY:
        src = ROOT / name
        if not src.is_dir():
            continue
        for item in sorted(src.rglob("*")):
            if not item.is_file():
                continue
            dest = target / name / item.relative_to(src)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                print(f"skip (already exists): {dest}")
                continue
            shutil.move(str(item), str(dest))
            moved += 1
        for folder in sorted(src.rglob("*"), reverse=True):
            if folder.is_dir() and not any(folder.iterdir()):
                try:
                    folder.rmdir()
                except OSError:
                    pass
    print(f"moved {moved} files into {target}")


if __name__ == "__main__":
    main()
