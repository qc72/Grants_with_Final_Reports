from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

try:
    import streamlit as st
except ModuleNotFoundError:  # Allows parser tests without the UI dependency.
    st = None

# The generated summaries are mostly consistent, but some use "1 Narrative"
# instead of "1. Narrative", "Item" instead of "Field", and "Quotes" or
# "Source file" instead of the singular labels. The renderer intentionally
# recognizes concepts rather than depending on one exact template.
SECTION_RE = re.compile(r"^\s*(?:section\s+)?([1-5])\s*[.):-]?\s*(.+?)\s*$", re.IGNORECASE)
LEADING_LIST_MARKER_RE = re.compile(r"^\s*(?:[•●▪◦‣–—-]|\[\[BULLET\]\])\s*")
NOISE_LINES = {"top of form", "bottom of form"}


@dataclass
class SummarySection:
    number: str
    title: str
    kind: str
    lines: list[str] = field(default_factory=list)


@dataclass
class ParsedSummary:
    title: str = ""
    sections: list[SummarySection] = field(default_factory=list)


def _clean_line(value: str) -> str:
    # Keep paragraph boundaries but normalize spacing introduced by Word cells.
    return re.sub(r"[ \t\u00a0]+", " ", value.strip())


def _strip_list_marker(value: str) -> str:
    return LEADING_LIST_MARKER_RE.sub("", value).strip()


def _normalized(value: str) -> str:
    value = _strip_list_marker(_clean_line(value)).casefold()
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _section_kind(title: str) -> str | None:
    normalized = _normalized(title)
    if "narrative" in normalized and "summary" in normalized:
        return "narrative"
    if "key" in normalized and ("fact" in normalized or "information" in normalized):
        return "facts"
    if "evidence" in normalized and ("assessment" in normalized or "classification" in normalized):
        return "assessment"
    if "evidence" in normalized and ("quote" in normalized or normalized == "evidence"):
        return "evidence"
    if "missing" in normalized or "uncertain information" in normalized or "information gaps" in normalized:
        return "missing"
    return None


def _canonical_title(kind: str, original: str) -> str:
    return {
        "narrative": "Narrative summary",
        "facts": "Key facts",
        "assessment": "CEL evidence assessment",
        "evidence": "Evidence quotes",
        "missing": "Missing or uncertain information",
    }.get(kind, original.strip())


def _unnumbered_heading_kind(line: str) -> str | None:
    """Recognize only standalone heading phrases, not prose containing keywords."""
    if ":" in line or len(line) > 80:
        return None
    normalized = _normalized(line)
    patterns = {
        "narrative": (r"^narrative summary(?: words)?$",),
        "facts": (r"^(?:key project facts|project key facts|key facts)$",),
        "assessment": (r"^(?:cel )?evidence assessment$", r"^cel assessment$"),
        "evidence": (r"^evidence quotes?$", r"^supporting evidence$"),
        "missing": (
            r"^missing(?: or)? uncertain information$",
            r"^missing information$",
            r"^information gaps$",
        ),
    }
    for kind, expressions in patterns.items():
        if any(re.fullmatch(expression, normalized) for expression in expressions):
            return kind
    return None


def _extract_table_blocks(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Remove Word-table rows from the flat text and classify them.

    Very early importer versions appended all DOCX tables after all paragraphs.
    Newer versions preserve their position. Recognizing the table headers globally
    lets one renderer display both already-imported and newly imported records.
    """
    remaining: list[str] = []
    fact_lines: list[str] = []
    assessment_lines: list[str] = []
    mode: str | None = None

    for line in lines:
        parts = _split_pipe_row(line)
        if _is_two_column_header(parts):
            mode = "facts"
            continue
        if _is_assessment_header(parts):
            mode = "assessment"
            continue

        if mode and parts:
            if mode == "facts":
                fact_lines.append(line)
            else:
                assessment_lines.append(line)
            continue

        mode = None
        remaining.append(line)

    return remaining, fact_lines, assessment_lines


def parse_summary(text: str) -> ParsedSummary:
    lines = [_clean_line(line) for line in (text or "").splitlines()]
    lines = [line for line in lines if line and _normalized(line) not in NOISE_LINES]
    lines, fact_lines, assessment_lines = _extract_table_blocks(lines)

    parsed = ParsedSummary()
    current: SummarySection | None = None

    for line in lines:
        if not parsed.title and _normalized(line).startswith("grant summary"):
            parsed.title = line
            continue

        match = SECTION_RE.match(line)
        if match:
            kind = _section_kind(match.group(2))
            if kind:
                current = SummarySection(
                    number=match.group(1),
                    title=_canonical_title(kind, match.group(2)),
                    kind=kind,
                )
                parsed.sections.append(current)
                continue

        # Also tolerate unnumbered headings, provided the whole short line is a
        # recognizable section title rather than ordinary narrative text.
        unnumbered_kind = _unnumbered_heading_kind(line)
        if unnumbered_kind:
            number = {"narrative": "1", "facts": "2", "assessment": "3", "evidence": "4", "missing": "5"}[unnumbered_kind]
            current = SummarySection(
                number=number,
                title=_canonical_title(unnumbered_kind, line),
                kind=unnumbered_kind,
            )
            parsed.sections.append(current)
            continue

        if current is None:
            current = SummarySection(number="", title="Summary", kind="general")
            parsed.sections.append(current)
        current.lines.append(line)

    def ensure_section(kind: str, number: str, title: str) -> SummarySection:
        existing = next((section for section in parsed.sections if section.kind == kind), None)
        if existing is not None:
            return existing
        section = SummarySection(number=number, title=title, kind=kind)
        insert_at = min(int(number) - 1, len(parsed.sections))
        parsed.sections.insert(insert_at, section)
        return section

    if fact_lines:
        ensure_section("facts", "2", "Key facts").lines.extend(fact_lines)
    if assessment_lines:
        ensure_section("assessment", "3", "CEL evidence assessment").lines.extend(assessment_lines)

    return parsed


def _split_pipe_row(line: str) -> list[str]:
    if "|" not in line:
        return []
    return [_clean_line(part) for part in line.split("|")]


def _is_two_column_header(parts: list[str]) -> bool:
    if len(parts) < 2:
        return False
    left, right = _normalized(parts[0]), _normalized(parts[1])
    return left in {"field", "item", "fact", "category", "attribute", "field item"} and right in {"detail", "details", "value", "description"}


def _is_assessment_header(parts: list[str]) -> bool:
    if len(parts) < 3:
        return False
    first = _normalized(parts[0])
    second = _normalized(parts[1])
    third = _normalized(parts[2])
    return (
        first in {"criterion", "criteria", "assessment criterion"}
        and second in {"met", "met yes no", "status", "result"}
        and any(token in third for token in ("explanation", "evidence", "detail", "reason"))
    )


def _normalize_academic_year(value: str) -> str:
    match = re.search(r"(?<!\d)(\d{4})\s*[-–—]\s*(\d{2}|\d{4})(?!\d)", value)
    if not match:
        return value
    start = int(match.group(1))
    end_text = match.group(2)
    if len(end_text) == 2:
        end = (start // 100) * 100 + int(end_text)
        if end < start:
            end += 100
    else:
        end = int(end_text)
    return f"{start:04d}-{end:04d}"


def _parse_facts(lines: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    rows: list[tuple[str, str]] = []
    leftovers: list[str] = []

    for line in lines:
        parts = _split_pipe_row(line)
        if _is_two_column_header(parts):
            continue
        if len(parts) >= 2:
            field_name = _strip_list_marker(parts[0])
            detail = " | ".join(part for part in parts[1:] if part).strip()
            if field_name and detail:
                if _normalized(field_name) == "academic year":
                    detail = _normalize_academic_year(detail)
                rows.append((field_name, detail))
                continue
        leftovers.append(_strip_list_marker(line))

    return rows, [line for line in leftovers if line]


def _parse_assessment(
    lines: list[str],
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]], list[str]]:
    rows: list[tuple[str, str, str]] = []
    notes: list[tuple[str, str]] = []
    leftovers: list[str] = []

    for line in lines:
        parts = _split_pipe_row(line)
        if _is_assessment_header(parts):
            continue
        if len(parts) >= 2:
            label = _strip_list_marker(parts[0])
            status = parts[1].strip() if len(parts) > 1 else ""
            explanation = " | ".join(part for part in parts[2:] if part).strip()
            normalized_label = _normalized(label)

            if normalized_label == "confidence":
                continue
            if normalized_label in {"brief explanation", "assessment note", "summary explanation"}:
                value = explanation or status
                if value:
                    notes.append((label, value))
                continue
            if label and (status or explanation):
                rows.append((label, status, explanation))
                continue
        leftovers.append(_strip_list_marker(line))

    return rows, notes, [line for line in leftovers if line]


PREFIX_RE = re.compile(
    r"^(?:evidence\s+)?(quotes?|source(?:\s+(?:file|document))?|why\s+(?:it|this)\s+matters|relevance)\s*:\s*(.*)$",
    re.IGNORECASE,
)


def _parse_evidence(lines: list[str]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    active_field: str | None = None

    def finish_current() -> None:
        nonlocal current, active_field
        if current and any(current.get(key) for key in ("quote", "source", "why")):
            entries.append(current)
        current = None
        active_field = None

    for raw_line in lines:
        line = _strip_list_marker(raw_line)
        if not line:
            continue

        match = PREFIX_RE.match(line)
        if match:
            if current is None:
                current = {"label": "Evidence"}
            prefix = _normalized(match.group(1))
            value = match.group(2).strip()
            if prefix.startswith("quote"):
                active_field = "quote"
            elif prefix.startswith("source"):
                active_field = "source"
            else:
                active_field = "why"
            if value:
                current[active_field] = value
            continue

        # A non-prefixed line after a complete evidence item is the next label.
        if current and any(current.get(key) for key in ("quote", "source", "why")):
            finish_current()
            current = {"label": line}
            continue

        # A wrapped line can continue the field that immediately preceded it.
        if current is not None and active_field:
            current[active_field] = f"{current.get(active_field, '')} {line}".strip()
        elif current is None:
            current = {"label": line}
        else:
            current["label"] = f"{current.get('label', '')} {line}".strip()

    finish_current()
    return entries


def _render_styles() -> None:
    st.markdown(
        """
        <style>
        .grant-summary p { line-height: 1.66; margin: 0 0 0.95rem 0; }
        .grant-summary-table { width: 100%; border-collapse: collapse; table-layout: fixed; margin: 0.25rem 0 0.8rem 0; }
        .grant-summary-table th { text-align: left; padding: 0.65rem 0.75rem; border-bottom: 2px solid rgba(128,128,128,.35); }
        .grant-summary-table td { vertical-align: top; padding: 0.65rem 0.75rem; border-bottom: 1px solid rgba(128,128,128,.22); line-height: 1.45; overflow-wrap: anywhere; }
        .grant-summary-table.facts th:first-child, .grant-summary-table.facts td:first-child { width: 28%; font-weight: 600; }
        .grant-summary-table.assessment th:nth-child(1), .grant-summary-table.assessment td:nth-child(1) { width: 25%; }
        .grant-summary-table.assessment th:nth-child(2), .grant-summary-table.assessment td:nth-child(2) { width: 12%; }
        .grant-summary-table.assessment th:nth-child(3), .grant-summary-table.assessment td:nth-child(3) { width: 63%; }
        .grant-evidence-card { border: 1px solid rgba(128,128,128,.25); border-radius: .55rem; padding: .85rem 1rem; margin: 0 0 .8rem 0; }
        .grant-evidence-label { font-weight: 650; margin-bottom: .45rem; }
        .grant-evidence-quote { border-left: 3px solid rgba(128,128,128,.45); padding-left: .8rem; line-height: 1.55; margin-bottom: .55rem; }
        .grant-evidence-meta { font-size: .9rem; opacity: .78; margin-top: .35rem; }
        .grant-summary-list { line-height: 1.6; margin-top: .2rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _safe_paragraph(text: str) -> None:
    st.markdown(
        f'<div class="grant-summary"><p>{html.escape(_strip_list_marker(text))}</p></div>',
        unsafe_allow_html=True,
    )


def _render_bullet_items(items: list[str]) -> None:
    if not items:
        return
    body = "".join(f"<li>{html.escape(_strip_list_marker(item))}</li>" for item in items if item)
    st.markdown(f'<ul class="grant-summary-list">{body}</ul>', unsafe_allow_html=True)


def _render_narrative(lines: list[str]) -> None:
    index = 0
    while index < len(lines):
        line = lines[index]
        if LEADING_LIST_MARKER_RE.match(line):
            bullets: list[str] = []
            while index < len(lines) and LEADING_LIST_MARKER_RE.match(lines[index]):
                bullets.append(lines[index])
                index += 1
            _render_bullet_items(bullets)
            continue

        _safe_paragraph(line)

        # Older stored summaries lost Word's bullet marker. Recover common lists
        # where a colon-introduction is followed by lowercase list items.
        if line.rstrip().endswith(":"):
            inferred: list[str] = []
            probe = index + 1
            while probe < len(lines) and len(inferred) < 8:
                candidate = _strip_list_marker(lines[probe])
                if candidate and candidate[:1].islower() and len(candidate) <= 220:
                    inferred.append(candidate)
                    probe += 1
                else:
                    break
            if inferred:
                _render_bullet_items(inferred)
                index = probe
                continue
        index += 1


def _render_html_table(rows: list[tuple[str, ...]], headers: tuple[str, ...], css_class: str) -> None:
    if not rows:
        st.info("No structured information was included in this section.")
        return
    header_html = "".join(f"<th>{html.escape(value)}</th>" for value in headers)
    row_html = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in row) + "</tr>"
        for row in rows
    )
    st.markdown(
        f'<table class="grant-summary-table {css_class}"><thead><tr>{header_html}</tr></thead><tbody>{row_html}</tbody></table>',
        unsafe_allow_html=True,
    )


def _render_evidence(lines: list[str]) -> None:
    entries = _parse_evidence(lines)
    if not entries:
        for line in lines:
            _safe_paragraph(line)
        return

    for entry in entries:
        label = html.escape(entry.get("label", "Evidence"))
        quote = entry.get("quote", "")
        source = entry.get("source", "")
        why = entry.get("why", "")
        pieces = [f'<div class="grant-evidence-label">{label}</div>']
        if quote:
            pieces.append(f'<div class="grant-evidence-quote">{html.escape(quote)}</div>')
        if why:
            pieces.append(f'<div>{html.escape(why)}</div>')
        if source:
            pieces.append(f'<div class="grant-evidence-meta">Source: {html.escape(source)}</div>')
        st.markdown(f'<div class="grant-evidence-card">{"".join(pieces)}</div>', unsafe_allow_html=True)


def render_summary(text: str) -> None:
    """Render a generated DOCX summary despite small template variations."""
    if st is None:
        raise RuntimeError("Streamlit is required to render summaries.")

    parsed = parse_summary(text)
    if not parsed.sections:
        st.info("No summary content is available.")
        return

    _render_styles()

    for index, section in enumerate(parsed.sections):
        heading = f"{section.number}. {section.title}" if section.number else section.title
        st.markdown(f"### {html.escape(heading)}")

        if section.kind == "facts":
            rows, leftovers = _parse_facts(section.lines)
            _render_html_table(rows, ("Field", "Detail"), "facts")
            for line in leftovers:
                _safe_paragraph(line)
        elif section.kind == "assessment":
            rows, notes, leftovers = _parse_assessment(section.lines)
            _render_html_table(rows, ("Criterion", "Met?", "Explanation"), "assessment")
            for label, value in notes:
                st.markdown(f"**{html.escape(label)}:** {html.escape(value)}")
            for line in leftovers:
                _safe_paragraph(line)
        elif section.kind == "evidence":
            _render_evidence(section.lines)
        elif section.kind == "missing":
            _render_bullet_items(section.lines)
        elif section.kind == "narrative":
            _render_narrative(section.lines)
        else:
            _render_narrative(section.lines)

        if index < len(parsed.sections) - 1:
            st.divider()
