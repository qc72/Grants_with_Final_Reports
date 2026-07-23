from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import fitz  # PyMuPDF
from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

PROJECT_ID_RE = re.compile(r"\b([A-Za-z]{2,})[ _-]+(\d{2}\.\d{3})\b")


@dataclass
class PdfCandidate:
    relative_path: str
    filename: str
    score: int
    reasons: list[str] = field(default_factory=list)


@dataclass
class ProjectRecord:
    project_id: str
    folder_name: str
    title: str = ""
    category: str = ""
    program: str = ""
    academic_year: str = ""
    funding_amount: str = ""
    principal_investigator: str = ""
    pi_college: str = ""
    community_partners: str = ""
    student_involvement: str = ""
    number_of_students: str = ""
    community_need: str = ""
    community_impact: str = ""
    publications: str = ""
    cel_classification: str = ""
    confidence: str = ""
    brief_explanation: str = ""
    final_report_available: str = ""
    automatic_report_path: str = ""
    final_report_score: int = 0
    final_report_confidence: str = "None"
    summary_text: str = ""
    highlight_text: str = ""
    project_note_text: str = ""
    missing_expected_files: list[str] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)
    pdf_candidates: list[PdfCandidate] = field(default_factory=list)
    fingerprint: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["pdf_candidates"] = [asdict(x) for x in self.pdf_candidates]
        return data


def canonical_project_id(value: str) -> str | None:
    match = PROJECT_ID_RE.search(value)
    if not match:
        return None
    return f"{match.group(1).upper()} {match.group(2)}"




def category_from_project_id(project_id: str) -> str:
    """Return the grant category code, e.g. ``ECG`` from ``ECG 16.003``."""
    canonical = canonical_project_id(project_id) or project_id.strip().upper()
    prefix = re.split(r"[ _-]+", canonical, maxsplit=1)[0]
    return prefix[:3].upper()


def normalize_academic_year(value: str) -> str:
    """Keep the first academic-year range and format it as YYYY-YYYY.

    Examples:
        2021 – 2022 (activities 2022–23) -> 2021-2022
        2018–2019 (planning); implementation 2022 -> 2018-2019
    """
    if not value:
        return ""
    match = re.search(r"(?<!\d)(\d{4})\s*[\-–—]\s*(\d{2}|\d{4})(?!\d)", value)
    if not match:
        return value.strip()
    start = int(match.group(1))
    end_text = match.group(2)
    if len(end_text) == 2:
        century = (start // 100) * 100
        end = century + int(end_text)
        if end < start:
            end += 100
    else:
        end = int(end_text)
    return f"{start:04d}-{end:04d}"

def project_slug(project_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", project_id).strip("_")


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="replace")


def read_docx(path: Path) -> str:
    """Read paragraphs and tables in their original DOCX order."""
    doc = Document(path)
    chunks: list[str] = []

    for child in doc.element.body.iterchildren():
        if isinstance(child, CT_P):
            paragraph = Paragraph(child, doc)
            text = paragraph.text.strip()
            if text:
                chunks.append(text)
        elif isinstance(child, CT_Tbl):
            table = Table(child, doc)
            for row in table.rows:
                cells = [re.sub(r"\s+", " ", cell.text).strip() for cell in row.cells]
                if any(cells):
                    chunks.append(" | ".join(cells))

    return "\n".join(chunks)


def read_pdf(path: Path, max_pages: int | None = None) -> str:
    chunks: list[str] = []
    with fitz.open(path) as doc:
        page_count = len(doc) if max_pages is None else min(len(doc), max_pages)
        for index in range(page_count):
            chunks.append(doc[index].get_text("text"))
    return "\n".join(chunks)


def normalize_label(label: str) -> str:
    label = label.strip().lower()
    label = re.sub(r"[^a-z0-9]+", " ", label)
    return re.sub(r"\s+", " ", label).strip()


def parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("•-")
        if not line:
            continue
        if ":" in line:
            key, value = line.split(":", 1)
        elif " | " in line:
            key, value = line.split(" | ", 1)
        else:
            continue
        key = normalize_label(key)
        value = value.strip()
        if key and value:
            values[key] = value
    return values


ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("title", "project title"),
    "category": ("category",),
    "program": ("program", "category program"),
    "academic_year": ("academic year",),
    "funding_amount": ("funding amount", "total funding"),
    "principal_investigator": ("pi project lead", "principal investigator", "project lead"),
    "pi_college": ("pi college or department", "pi college", "pi college department"),
    "community_partners": ("community partner s", "community partners", "community partner"),
    "student_involvement": ("student involvement",),
    "number_of_students": ("number of students involved", "number of students"),
    "community_need": ("main community need", "community need"),
    "community_impact": ("main community impact", "community impact"),
    "publications": ("publications final products", "publications or final products", "publications products"),
    "cel_classification": ("overall cel classification", "cel classification"),
    "confidence": ("confidence",),
    "brief_explanation": ("brief explanation",),
    "final_report_available": ("final report available",),
}


def first_value(*maps: dict[str, str], aliases: Iterable[str]) -> str:
    for mapping in maps:
        for alias in aliases:
            value = mapping.get(alias, "").strip()
            if value:
                return value
    return ""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_project(folder: Path, files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(folder).as_posix().lower()):
        relative = path.relative_to(folder).as_posix()
        digest.update(relative.encode("utf-8", errors="replace"))
        digest.update(b"\0")
        digest.update(str(path.stat().st_size).encode("ascii"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def score_final_report(path: Path, project_id: str, project_root: Path) -> PdfCandidate:
    normalized_name = path.name.lower().replace("_", " ").replace("-", " ")
    score = 0
    reasons: list[str] = []

    def add(points: int, reason: str) -> None:
        nonlocal score
        score += points
        reasons.append(f"{points:+d}: {reason}")

    project_tokens = project_id.lower().split()
    if all(token in normalized_name for token in project_tokens):
        add(3, "filename contains project ID")
    if "final report" in normalized_name:
        add(10, "filename says final report")
    elif "report" in normalized_name:
        add(3, "filename contains report")
    if "budget" in normalized_name:
        add(-10, "filename indicates budget")
    if "application" in normalized_name or "proposal" in normalized_name:
        add(-9, "filename indicates application/proposal")
    if "worksheet" in normalized_name:
        add(-7, "filename indicates worksheet")
    if "interim" in normalized_name or "progress" in normalized_name:
        add(-4, "filename indicates a non-final report")

    try:
        text = read_pdf(path, max_pages=8).lower()
    except Exception as exc:
        add(-20, f"PDF text could not be read ({type(exc).__name__})")
        return PdfCandidate(path.relative_to(project_root).as_posix(), path.name, score, reasons)

    signals = [
        ("final report", 12, "document text says final report"),
        ("submitted on", 4, "contains submission metadata"),
        ("how have undergraduate students contributed", 7, "contains final-report questionnaire"),
        ("what has been the role", 4, "contains partner-role question"),
        ("overall, how satisfied", 5, "contains recipient satisfaction question"),
        ("would you recommend this funding", 4, "contains closing report question"),
        ("final report received", 3, "contains final-report receipt metadata"),
    ]
    for needle, points, reason in signals:
        if needle in text:
            add(points, reason)

    if "project budget" in text and "final report" not in text:
        add(-8, "content appears to be a budget")
    if ("application" in text[:3000] or "proposal" in text[:3000]) and "final report" not in text:
        add(-5, "opening content appears to be an application/proposal")

    return PdfCandidate(path.relative_to(project_root).as_posix(), path.name, score, reasons)


def confidence_from_candidates(candidates: list[PdfCandidate]) -> str:
    if not candidates:
        return "None"
    ordered = sorted(candidates, key=lambda item: item.score, reverse=True)
    top = ordered[0].score
    gap = top - ordered[1].score if len(ordered) > 1 else top
    if top >= 18 and gap >= 8:
        return "High"
    if top >= 10 and gap >= 3:
        return "Medium"
    return "Low"


def candidate_folder_score(folder: Path) -> int:
    files = [path for path in folder.rglob("*") if path.is_file()]
    score = 0
    for path in files:
        name = path.name.lower()
        if path.suffix.lower() == ".docx" and "summary" in name:
            score += 8
        if path.suffix.lower() == ".txt" and "highlight" in name:
            score += 8
        if path.suffix.lower() == ".txt" and "project" in name and "note" in name:
            score += 8
        if path.suffix.lower() == ".pdf":
            score += 1
    return score


def identify_project_directories(root: Path) -> list[tuple[str, Path, list[str]]]:
    grouped: dict[str, list[Path]] = {}
    for path in root.rglob("*"):
        if path.is_dir():
            project_id = canonical_project_id(path.name)
            if project_id:
                grouped.setdefault(project_id, []).append(path)

    for path in root.rglob("*.txt"):
        lower = path.name.lower()
        if "highlight" not in lower and not ("project" in lower and "note" in lower):
            continue
        try:
            project_id = canonical_project_id(read_text(path)[:3000])
        except OSError:
            project_id = None
        if project_id:
            grouped.setdefault(project_id, []).append(path.parent)

    results: list[tuple[str, Path, list[str]]] = []
    for project_id, paths in grouped.items():
        unique_paths = sorted(set(paths), key=lambda item: item.as_posix().lower())
        ranked = sorted(unique_paths, key=lambda item: (candidate_folder_score(item), -len(item.parts)), reverse=True)
        selected = ranked[0]
        warnings: list[str] = []
        if len(ranked) > 1:
            warnings.append(f"Found {len(ranked)} folders for {project_id}; selected {selected.name}.")
        results.append((project_id, selected, warnings))
    return sorted(results, key=lambda item: item[0])


def find_best_file(files: list[Path], *, suffix: str, include: tuple[str, ...]) -> Path | None:
    candidates = [
        path
        for path in files
        if path.suffix.lower() == suffix and all(token in path.name.lower() for token in include)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: (len(path.name), path.name.lower()))[0]


def role_for_file(path: Path, selected_report: str) -> str:
    name = path.name.lower()
    relative = path.as_posix()
    if relative == selected_report:
        return "final_report"
    if path.suffix.lower() == ".docx" and "summary" in name:
        return "summary"
    if path.suffix.lower() == ".txt" and "highlight" in name:
        return "highlight"
    if path.suffix.lower() == ".txt" and "project" in name and "note" in name:
        return "project_note"
    if path.suffix.lower() == ".pdf":
        return "pdf"
    return "other"


def scan_project(folder: Path, expected_project_id: str | None = None) -> ProjectRecord:
    files = [path for path in folder.rglob("*") if path.is_file()]
    summary_path = find_best_file(files, suffix=".docx", include=("summary",))
    highlight_path = find_best_file(files, suffix=".txt", include=("highlight",))
    note_path = next(
        (
            path
            for path in files
            if path.suffix.lower() == ".txt" and "project" in path.name.lower() and "note" in path.name.lower()
        ),
        None,
    )

    summary_text = read_docx(summary_path) if summary_path else ""
    highlight_text = read_text(highlight_path) if highlight_path else ""
    note_text = read_text(note_path) if note_path else ""
    project_id = expected_project_id or canonical_project_id(folder.name)
    if not project_id:
        project_id = canonical_project_id("\n".join((highlight_text, note_text, summary_text))) or folder.name

    highlight_values = parse_key_values(highlight_text)
    note_values = parse_key_values(note_text)
    summary_values = parse_key_values(summary_text)
    value_maps = (highlight_values, note_values, summary_values)

    pdfs = [path for path in files if path.suffix.lower() == ".pdf"]
    candidates = sorted(
        (score_final_report(path, project_id, folder) for path in pdfs),
        key=lambda item: (item.score, item.filename.lower()),
        reverse=True,
    )
    selected = candidates[0] if candidates else None
    confidence = confidence_from_candidates(candidates)

    missing: list[str] = []
    if not summary_path:
        missing.append("summary.docx")
    if not highlight_path:
        missing.append("highlight.txt")
    if not note_path:
        missing.append("project_note.txt")
    if not selected or selected.score < 10:
        missing.append("confident final-report PDF")
    elif confidence in {"Low", "None"}:
        missing.append("final-report selection needs review")

    fields = {
        field_name: first_value(*value_maps, aliases=aliases)
        for field_name, aliases in ALIASES.items()
    }
    # Category is intentionally the first three characters of the grant ID.
    # This is more consistent than free-text program names in source documents.
    fields["category"] = category_from_project_id(project_id)
    fields["academic_year"] = normalize_academic_year(fields["academic_year"])
    automatic_report = selected.relative_path if selected else ""

    file_rows: list[dict] = []
    for path in sorted(files, key=lambda item: item.relative_to(folder).as_posix().lower()):
        relative_path = path.relative_to(folder).as_posix()
        file_rows.append(
            {
                "relative_path": relative_path,
                "filename": path.name,
                "suffix": path.suffix.lower(),
                "size_bytes": path.stat().st_size,
                "sha256": file_sha256(path),
                "role": role_for_file(Path(relative_path), automatic_report),
            }
        )

    return ProjectRecord(
        project_id=project_id,
        folder_name=folder.name,
        **fields,
        automatic_report_path=automatic_report,
        final_report_score=selected.score if selected else 0,
        final_report_confidence=confidence,
        summary_text=summary_text,
        highlight_text=highlight_text,
        project_note_text=note_text,
        missing_expected_files=missing,
        files=file_rows,
        pdf_candidates=candidates,
        fingerprint=fingerprint_project(folder, files),
    )
