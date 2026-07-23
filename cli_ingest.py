from __future__ import annotations

import argparse
from pathlib import Path

from config import DB_PATH, DOCUMENT_ROOT, ensure_directories
from database import initialize_database
from importer import import_zip_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Import one grant-project ZIP batch.")
    parser.add_argument("zip_path", type=Path, help="Path to a ZIP batch")
    parser.add_argument("--batch-name", help="Label shown in import history")
    args = parser.parse_args()

    ensure_directories()
    initialize_database(DB_PATH)
    zip_path = args.zip_path.resolve()
    if not zip_path.exists():
        raise SystemExit(f"ZIP not found: {zip_path}")

    def progress(current: int, total: int, project_id: str) -> None:
        print(f"[{current}/{total}] {project_id}")

    result = import_zip_path(
        zip_path,
        batch_name=args.batch_name or zip_path.name,
        db_path=DB_PATH,
        document_root=DOCUMENT_ROOT,
        progress=progress,
    )
    print(result)
    if result["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
