from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from database import initialize_database, list_projects
from importer import import_zip_path


def test_demo_batch_imports_and_skips_on_second_run() -> None:
    root = Path(__file__).resolve().parents[1]
    demo_zip = root / "demo" / "AVF_18_007_batch.zip"
    assert demo_zip.exists()
    with tempfile.TemporaryDirectory() as temporary:
        temporary_root = Path(temporary)
        db_path = temporary_root / "grants.db"
        docs = temporary_root / "documents"
        initialize_database(db_path)
        first = import_zip_path(
            demo_zip, batch_name="demo", db_path=db_path, document_root=docs
        )
        assert first["new"] == 1
        assert first["error"] == 0
        projects = list_projects(db_path)
        assert projects[0]["project_id"] == "AVF 18.007"
        assert projects[0]["category"] == "AVF"
        assert projects[0]["academic_year"] == "2017-2018"
        assert projects[0]["final_report_confidence"] == "High"

        second = import_zip_path(
            demo_zip, batch_name="demo again", db_path=db_path, document_root=docs
        )
        assert second["skipped"] == 1
        assert second["new"] == 0


def test_year_normalization_and_category_derivation() -> None:
    from parser import category_from_project_id, normalize_academic_year

    assert category_from_project_id("ECG 21.004") == "ECG"
    assert normalize_academic_year("2021 – 2022 (activities 2022 – 23)") == "2021-2022"
    assert normalize_academic_year("2018–2019 (planning); full implementation 2022") == "2018-2019"
    assert normalize_academic_year("2015 – 2017 (activities 2015 – 17)") == "2015-2017"
