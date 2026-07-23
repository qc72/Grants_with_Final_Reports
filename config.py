from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DATA_ROOT = Path(os.getenv("GRANT_INSIGHTS_HOME", APP_DIR / "data")).resolve()
DB_PATH = Path(os.getenv("GRANT_INSIGHTS_DB", DATA_ROOT / "grants.db")).resolve()
DOCUMENT_ROOT = Path(os.getenv("GRANT_INSIGHTS_DOCUMENTS", DATA_ROOT / "documents")).resolve()

MAX_ZIP_ENTRIES = int(os.getenv("GRANT_INSIGHTS_MAX_ZIP_ENTRIES", "50000"))
MAX_EXPANDED_BYTES = int(os.getenv("GRANT_INSIGHTS_MAX_EXPANDED_BYTES", str(8 * 1024**3)))
MAX_COMPRESSION_RATIO = float(os.getenv("GRANT_INSIGHTS_MAX_COMPRESSION_RATIO", "500"))


def ensure_directories() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    DOCUMENT_ROOT.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
