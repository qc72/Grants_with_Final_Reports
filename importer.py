from __future__ import annotations

import io
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable

from config import MAX_COMPRESSION_RATIO, MAX_EXPANDED_BYTES, MAX_ZIP_ENTRIES
from database import (
    add_import_item,
    begin_import,
    finish_import,
    get_existing_fingerprint,
    upsert_project,
)
from parser import identify_project_directories, project_slug, scan_project

ProgressCallback = Callable[[int, int, str], None]


def validate_member_name(name: str) -> None:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe ZIP entry blocked: {name}")
    if path.parts and ":" in path.parts[0]:
        raise ValueError(f"Unsafe drive-qualified ZIP entry blocked: {name}")


def safe_extract_zip(zip_path: Path, destination: Path) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        members = archive.infolist()
        if len(members) > MAX_ZIP_ENTRIES:
            raise ValueError(f"ZIP contains {len(members):,} entries; limit is {MAX_ZIP_ENTRIES:,}.")
        expanded = sum(member.file_size for member in members)
        if expanded > MAX_EXPANDED_BYTES:
            raise ValueError(
                f"ZIP expands to {expanded / 1024**3:.2f} GB; limit is {MAX_EXPANDED_BYTES / 1024**3:.2f} GB."
            )
        for member in members:
            validate_member_name(member.filename)
            if member.compress_size > 0 and member.file_size / member.compress_size > MAX_COMPRESSION_RATIO:
                raise ValueError(f"Suspicious compression ratio blocked: {member.filename}")
            target = (destination / member.filename).resolve()
            if destination != target and destination not in target.parents:
                raise ValueError(f"Unsafe ZIP entry blocked: {member.filename}")
        archive.extractall(destination)


def copy_project_atomically(source: Path, target: Path) -> tuple[Path | None, Path]:
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{target.name}.staging-{uuid.uuid4().hex}"
    backup = target.parent / f".{target.name}.backup-{uuid.uuid4().hex}" if target.exists() else None
    shutil.copytree(source, staging)
    if backup:
        target.rename(backup)
    staging.rename(target)
    return backup, target


def restore_project_copy(target: Path, backup: Path | None) -> None:
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    if backup and backup.exists():
        backup.rename(target)


def import_zip_path(
    zip_path: Path,
    *,
    batch_name: str,
    db_path: Path,
    document_root: Path,
    progress: ProgressCallback | None = None,
) -> dict:
    run_id = begin_import(db_path, batch_name)
    counts = {"detected": 0, "new": 0, "updated": 0, "skipped": 0, "review": 0, "error": 0}
    overall_status = "completed"
    overall_message = ""

    try:
        with tempfile.TemporaryDirectory(prefix="grant_batch_") as temp_directory:
            extraction_root = Path(temp_directory) / "extracted"
            extraction_root.mkdir(parents=True)
            safe_extract_zip(zip_path, extraction_root)
            projects = identify_project_directories(extraction_root)
            counts["detected"] = len(projects)

            if not projects:
                raise ValueError("No project folders with an ID such as 'AVF 18.007' were detected.")

            for index, (project_id, folder, detection_warnings) in enumerate(projects, start=1):
                if progress:
                    progress(index, len(projects), project_id)
                try:
                    record = scan_project(folder, expected_project_id=project_id)
                    existing_fingerprint = get_existing_fingerprint(db_path, record.project_id)
                    warning_text = " ".join(detection_warnings)
                    if existing_fingerprint == record.fingerprint:
                        counts["skipped"] += 1
                        add_import_item(
                            db_path, run_id, project_id=record.project_id, folder_name=record.folder_name,
                            status="skipped", message=(warning_text + " Unchanged fingerprint.").strip(),
                            fingerprint=record.fingerprint,
                        )
                        continue

                    storage_folder = project_slug(record.project_id)
                    target = document_root / storage_folder
                    backup, copied_target = copy_project_atomically(folder, target)
                    try:
                        action = upsert_project(
                            db_path, record, storage_folder=storage_folder, source_batch=batch_name
                        )
                    except Exception:
                        restore_project_copy(copied_target, backup)
                        raise
                    else:
                        if backup and backup.exists():
                            shutil.rmtree(backup, ignore_errors=True)

                    counts[action] += 1
                    needs_review = bool(record.missing_expected_files) or record.final_report_confidence in {"Low", "None"}
                    if needs_review:
                        counts["review"] += 1
                    message_parts = []
                    if warning_text:
                        message_parts.append(warning_text)
                    if record.missing_expected_files:
                        message_parts.append("Review: " + ", ".join(record.missing_expected_files))
                    add_import_item(
                        db_path, run_id, project_id=record.project_id, folder_name=record.folder_name,
                        status=action, message=" ".join(message_parts), fingerprint=record.fingerprint,
                    )
                except Exception as exc:
                    counts["error"] += 1
                    add_import_item(
                        db_path, run_id, project_id=project_id, folder_name=folder.name,
                        status="error", message=f"{type(exc).__name__}: {exc}",
                    )

        if counts["error"]:
            overall_status = "completed_with_errors"
            overall_message = f"{counts['error']} project(s) failed; successful projects were retained."
    except Exception as exc:
        overall_status = "failed"
        overall_message = f"{type(exc).__name__}: {exc}"
        counts["error"] += 1
    finally:
        finish_import(db_path, run_id, counts, overall_status, overall_message)

    return {"run_id": run_id, "status": overall_status, "message": overall_message, **counts}


def import_zip_bytes(
    zip_bytes: bytes,
    *,
    batch_name: str,
    db_path: Path,
    document_root: Path,
    progress: ProgressCallback | None = None,
) -> dict:
    with tempfile.NamedTemporaryFile(prefix="grant_upload_", suffix=".zip", delete=False) as handle:
        temporary_path = Path(handle.name)
        handle.write(zip_bytes)
    try:
        return import_zip_path(
            temporary_path,
            batch_name=batch_name,
            db_path=db_path,
            document_root=document_root,
            progress=progress,
        )
    finally:
        temporary_path.unlink(missing_ok=True)
