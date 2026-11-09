"""Delete the SQLite DB and re-import from the Excel files."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import DB_PATH            # noqa: E402
from core.database import init_db     # noqa: E402
from services.importer import load_data  # noqa: E402


def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"[reset] deleted {DB_PATH}")
    init_db()
    report: list = []
    load_data(report)
    for lvl, who, msg in report:
        print(f"[import] {lvl:5} {who:40} {msg}")
    print("[reset] done")


if __name__ == "__main__":
    main()