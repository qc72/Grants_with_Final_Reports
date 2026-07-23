from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from parser import ProjectRecord


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        yield connection
    finally:
        connection.close()


def initialize_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                folder_name TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                program TEXT NOT NULL DEFAULT '',
                academic_year TEXT NOT NULL DEFAULT '',
                funding_amount TEXT NOT NULL DEFAULT '',
                principal_investigator TEXT NOT NULL DEFAULT '',
                pi_college TEXT NOT NULL DEFAULT '',
                community_partners TEXT NOT NULL DEFAULT '',
                student_involvement TEXT NOT NULL DEFAULT '',
                number_of_students TEXT NOT NULL DEFAULT '',
                community_need TEXT NOT NULL DEFAULT '',
                community_impact TEXT NOT NULL DEFAULT '',
                publications TEXT NOT NULL DEFAULT '',
                cel_classification TEXT NOT NULL DEFAULT '',
                confidence TEXT NOT NULL DEFAULT '',
                brief_explanation TEXT NOT NULL DEFAULT '',
                final_report_available TEXT NOT NULL DEFAULT '',
                automatic_report_path TEXT NOT NULL DEFAULT '',
                selected_report_path TEXT,
                final_report_score INTEGER NOT NULL DEFAULT 0,
                final_report_confidence TEXT NOT NULL DEFAULT 'None',
                summary_text TEXT NOT NULL DEFAULT '',
                highlight_text TEXT NOT NULL DEFAULT '',
                project_note_text TEXT NOT NULL DEFAULT '',
                missing_expected_files_json TEXT NOT NULL DEFAULT '[]',
                fingerprint TEXT NOT NULL,
                storage_folder TEXT NOT NULL,
                source_batch TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS source_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
                relative_path TEXT NOT NULL,
                filename TEXT NOT NULL,
                suffix TEXT NOT NULL DEFAULT '',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT 'other',
                UNIQUE(project_id, relative_path)
            );

            CREATE TABLE IF NOT EXISTS pdf_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
                relative_path TEXT NOT NULL,
                filename TEXT NOT NULL,
                score INTEGER NOT NULL,
                reasons_json TEXT NOT NULL DEFAULT '[]',
                UNIQUE(project_id, relative_path)
            );

            CREATE TABLE IF NOT EXISTS import_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                detected_count INTEGER NOT NULL DEFAULT 0,
                new_count INTEGER NOT NULL DEFAULT 0,
                updated_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                review_count INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS import_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                import_run_id INTEGER NOT NULL REFERENCES import_runs(id) ON DELETE CASCADE,
                project_id TEXT NOT NULL DEFAULT '',
                folder_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                fingerprint TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_projects_program ON projects(program);
            CREATE INDEX IF NOT EXISTS idx_projects_year ON projects(academic_year);
            CREATE INDEX IF NOT EXISTS idx_projects_report_confidence ON projects(final_report_confidence);
            CREATE INDEX IF NOT EXISTS idx_import_items_run ON import_items(import_run_id);
            """
        )
        connection.commit()


def begin_import(db_path: Path, batch_name: str) -> int:
    with connect(db_path) as connection:
        cursor = connection.execute(
            "INSERT INTO import_runs(batch_name, started_at, status) VALUES (?, ?, 'running')",
            (batch_name, utc_now()),
        )
        connection.commit()
        return int(cursor.lastrowid)


def finish_import(db_path: Path, run_id: int, counts: dict[str, int], status: str, message: str = "") -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            UPDATE import_runs
            SET completed_at = ?, status = ?, detected_count = ?, new_count = ?, updated_count = ?,
                skipped_count = ?, review_count = ?, error_count = ?, message = ?
            WHERE id = ?
            """,
            (
                utc_now(), status, counts.get("detected", 0), counts.get("new", 0), counts.get("updated", 0),
                counts.get("skipped", 0), counts.get("review", 0), counts.get("error", 0), message, run_id,
            ),
        )
        connection.commit()


def add_import_item(
    db_path: Path,
    run_id: int,
    *,
    project_id: str,
    folder_name: str,
    status: str,
    message: str = "",
    fingerprint: str = "",
) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO import_items(import_run_id, project_id, folder_name, status, message, fingerprint)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, project_id, folder_name, status, message, fingerprint),
        )
        connection.commit()


def get_existing_fingerprint(db_path: Path, project_id: str) -> str | None:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT fingerprint FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        return str(row["fingerprint"]) if row else None


def upsert_project(
    db_path: Path,
    record: ProjectRecord,
    *,
    storage_folder: str,
    source_batch: str,
) -> str:
    now = utc_now()
    with connect(db_path) as connection:
        existing = connection.execute(
            "SELECT project_id, created_at, selected_report_path FROM projects WHERE project_id = ?",
            (record.project_id,),
        ).fetchone()
        action = "updated" if existing else "new"
        created_at = existing["created_at"] if existing else now
        selected_report_path = existing["selected_report_path"] if existing else None
        valid_paths = {item["relative_path"] for item in record.files}
        if selected_report_path not in valid_paths:
            selected_report_path = None

        values = record.to_dict()
        connection.execute(
            """
            INSERT INTO projects (
                project_id, folder_name, title, program, academic_year, funding_amount,
                principal_investigator, pi_college, community_partners, student_involvement,
                number_of_students, community_need, community_impact, publications,
                cel_classification, confidence, brief_explanation, final_report_available,
                automatic_report_path, selected_report_path, final_report_score,
                final_report_confidence, summary_text, highlight_text, project_note_text,
                missing_expected_files_json, fingerprint, storage_folder, source_batch,
                created_at, updated_at
            ) VALUES (
                :project_id, :folder_name, :title, :program, :academic_year, :funding_amount,
                :principal_investigator, :pi_college, :community_partners, :student_involvement,
                :number_of_students, :community_need, :community_impact, :publications,
                :cel_classification, :confidence, :brief_explanation, :final_report_available,
                :automatic_report_path, :selected_report_path, :final_report_score,
                :final_report_confidence, :summary_text, :highlight_text, :project_note_text,
                :missing_expected_files_json, :fingerprint, :storage_folder, :source_batch,
                :created_at, :updated_at
            )
            ON CONFLICT(project_id) DO UPDATE SET
                folder_name = excluded.folder_name,
                title = excluded.title,
                program = excluded.program,
                academic_year = excluded.academic_year,
                funding_amount = excluded.funding_amount,
                principal_investigator = excluded.principal_investigator,
                pi_college = excluded.pi_college,
                community_partners = excluded.community_partners,
                student_involvement = excluded.student_involvement,
                number_of_students = excluded.number_of_students,
                community_need = excluded.community_need,
                community_impact = excluded.community_impact,
                publications = excluded.publications,
                cel_classification = excluded.cel_classification,
                confidence = excluded.confidence,
                brief_explanation = excluded.brief_explanation,
                final_report_available = excluded.final_report_available,
                automatic_report_path = excluded.automatic_report_path,
                selected_report_path = excluded.selected_report_path,
                final_report_score = excluded.final_report_score,
                final_report_confidence = excluded.final_report_confidence,
                summary_text = excluded.summary_text,
                highlight_text = excluded.highlight_text,
                project_note_text = excluded.project_note_text,
                missing_expected_files_json = excluded.missing_expected_files_json,
                fingerprint = excluded.fingerprint,
                storage_folder = excluded.storage_folder,
                source_batch = excluded.source_batch,
                updated_at = excluded.updated_at
            """,
            {
                **values,
                "selected_report_path": selected_report_path,
                "missing_expected_files_json": json.dumps(record.missing_expected_files),
                "storage_folder": storage_folder,
                "source_batch": source_batch,
                "created_at": created_at,
                "updated_at": now,
            },
        )

        connection.execute("DELETE FROM source_files WHERE project_id = ?", (record.project_id,))
        connection.executemany(
            """
            INSERT INTO source_files(project_id, relative_path, filename, suffix, size_bytes, sha256, role)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    record.project_id, item["relative_path"], item["filename"], item["suffix"],
                    item["size_bytes"], item["sha256"], item["role"],
                )
                for item in record.files
            ],
        )

        connection.execute("DELETE FROM pdf_candidates WHERE project_id = ?", (record.project_id,))
        connection.executemany(
            """
            INSERT INTO pdf_candidates(project_id, relative_path, filename, score, reasons_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    record.project_id, item.relative_path, item.filename, item.score,
                    json.dumps(item.reasons),
                )
                for item in record.pdf_candidates
            ],
        )
        connection.commit()
        return action


def list_projects(db_path: Path) -> list[dict]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT *, COALESCE(selected_report_path, automatic_report_path) AS effective_report_path
            FROM projects ORDER BY project_id
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_project(db_path: Path, project_id: str) -> dict | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT *, COALESCE(selected_report_path, automatic_report_path) AS effective_report_path
            FROM projects WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()
        return dict(row) if row else None


def get_source_files(db_path: Path, project_id: str) -> list[dict]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM source_files WHERE project_id = ? ORDER BY relative_path",
            (project_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_pdf_candidates(db_path: Path, project_id: str) -> list[dict]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM pdf_candidates WHERE project_id = ? ORDER BY score DESC, filename",
            (project_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["reasons"] = json.loads(item.pop("reasons_json"))
            result.append(item)
        return result


def set_report_override(db_path: Path, project_id: str, relative_path: str | None) -> None:
    with connect(db_path) as connection:
        connection.execute(
            "UPDATE projects SET selected_report_path = ?, updated_at = ? WHERE project_id = ?",
            (relative_path, utc_now(), project_id),
        )
        connection.commit()


def list_import_runs(db_path: Path, limit: int = 100) -> list[dict]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM import_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]


def list_import_items(db_path: Path, run_id: int) -> list[dict]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM import_items WHERE import_run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
        return [dict(row) for row in rows]
