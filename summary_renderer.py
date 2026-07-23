from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

import pandas as pd

try:
    import streamlit as st
except ModuleNotFoundError:  # Allows parser tests without the UI dependency.
    st = None

SECTION_RE = re.compile(r"^\s*(\d+)\s*\.\s*(.+?)\s*$")
NUMBERED_LABEL_RE = re.compile(r"^\s*\d+\s*[.)-]?\s*")


@dataclass
class SummarySection:
    number: str
    title: str
    lines: list[str] = field(default_factory=list)


@dataclass
class ParsedSummary:
    title: str = ""
    sections: list[SummarySection] = field(default_factory=list)
    key_facts: list[tuple[str, str]] = field(default_factory=list)
    assessment: list[tuple[str, str, str]] = field(default_factory=list)


def _clean_line(value: str) -> str:
    return re.sub(r"[ \t]+", " ", value.strip())


def _extract_tables(lines: list[str]) -> tuple[list[str], list[tuple[str, str]], list[tuple[str, str, str]]]:
    """Extract known DOCX tables, including text imported by older app versions.

    Older versions appended all table rows at the bottom of the summary. Pulling
    them out by header lets the display put them back under their proper sections.
    """
    remaining: list[str] = []
    key_facts: list[tuple[str, str]] = []
    assessment: list[tuple[str, str, str]] = []
    mode: str | None = None

    for raw_line in lines:
        line = _clean_line(raw_line)
        normalized = line.casefold()

        if normalized == "field | detail":
            mode = "facts"
            continue
        if normalized == "criterion | met? | explanation":
            mode = "assessment"
            continue

        if mode == "facts" and "|" in line:
            parts = [_clean_line(part) for part in line.split("|", 1)]
            if len(parts) == 2:
                key_facts.append((parts[0], parts[1]))
                continue
        if mode == "assessment" and "|" in line:
            parts = [_clean_line(part) for part in line.split("|", 2)]
            if len(parts) == 3:
                # The confidence score is an internal assessment aid and is not
                # part of the viewer-facing project summary.
                if parts[0].casefold() != "confidence":
                    assessment.append(tuple(parts))
                continue

        # Any ordinary line ends the current table, except blank lines.
        if line:
            mode = None
            remaining.append(line)

    return remaining, key_facts, assessment


def parse_summary(text: str) -> ParsedSummary:
    lines = [_clean_line(line) for line in (text or "").splitlines()]
    lines = [line for line in lines if line]
    lines, key_facts, assessment = _extract_tables(lines)

    parsed = ParsedSummary(key_facts=key_facts, assessment=assessment)
    current: SummarySection | None = None

    for line in lines:
        if not parsed.title and line.casefold().startswith("grant summary:"):
            parsed.title = line
            continue

        match = SECTION_RE.match(line)
        if match:
            current = SummarySection(number=match.group(1), title=match.group(2))
            parsed.sections.append(current)
            continue

        if current is None:
            current = SummarySection(number="", title="Summary")
            parsed.sections.append(current)
        current.lines.append(line)

    return parsed


def _safe_paragraph(text: str) -> None:
    st.markdown(
        f'<div style="line-height:1.65; margin:0 0 0.9rem 0;">{html.escape(text)}</div>',
        unsafe_allow_html=True,
    )


def _render_table(rows: list[tuple[str, ...]], columns: list[str]) -> None:
    if not rows:
        st.info("No structured information was included in this section.")
        return
    frame = pd.DataFrame(rows, columns=columns)
    st.dataframe(frame, hide_index=True, width="stretch")


def _parse_evidence(lines: list[str]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    for line in lines:
        if line.startswith("Quote:"):
            if current is None:
                current = {"label": "Evidence"}
            current["quote"] = line.split(":", 1)[1].strip()
        elif line.startswith("Source:"):
            if current is None:
                current = {"label": "Evidence"}
            current["source"] = line.split(":", 1)[1].strip()
        elif line.startswith("Why it matters:"):
            if current is None:
                current = {"label": "Evidence"}
            current["why"] = line.split(":", 1)[1].strip()
        else:
            if current and any(key in current for key in ("quote", "source", "why")):
                entries.append(current)
            label = NUMBERED_LABEL_RE.sub("", line).strip() or "Evidence"
            current = {"label": label}

    if current and any(key in current for key in ("quote", "source", "why")):
        entries.append(current)
    return entries


def _render_evidence(lines: list[str]) -> None:
    entries = _parse_evidence(lines)
    if not entries:
        for line in lines:
            _safe_paragraph(line)
        return

    for entry in entries:
        st.markdown(f"##### {html.escape(entry.get('label', 'Evidence'))}")
        if entry.get("quote"):
            st.markdown(
                '<blockquote style="margin:0.25rem 0 0.6rem 0; padding-left:1rem;">'
                f'{html.escape(entry["quote"])}</blockquote>',
                unsafe_allow_html=True,
            )
        if entry.get("source"):
            st.caption(f"Source: {entry['source']}")
        if entry.get("why"):
            _safe_paragraph(entry["why"])
        st.divider()


def _render_bullets(lines: list[str]) -> None:
    if not lines:
        st.info("No missing or uncertain information was listed.")
        return
    items = "".join(f"<li>{html.escape(line)}</li>" for line in lines)
    st.markdown(f'<ul style="line-height:1.6;">{items}</ul>', unsafe_allow_html=True)


def render_summary(text: str) -> None:
    """Render generated summary text as structured, safe Streamlit content."""
    if st is None:
        raise RuntimeError("Streamlit is required to render summaries.")
    parsed = parse_summary(text)
    if not parsed.sections and not parsed.key_facts and not parsed.assessment:
        st.info("No summary content is available.")
        return

    for index, section in enumerate(parsed.sections):
        title_key = section.title.casefold()
        st.markdown(f"### {section.number + '. ' if section.number else ''}{section.title}")

        if "key fact" in title_key:
            _render_table(parsed.key_facts, ["Field", "Detail"])
        elif "evidence assessment" in title_key or "cel assessment" in title_key:
            _render_table(parsed.assessment, ["Criterion", "Met?", "Explanation"])
        elif "evidence quote" in title_key or title_key == "evidence":
            _render_evidence(section.lines)
        elif "missing" in title_key or "uncertain" in title_key:
            _render_bullets(section.lines)
        else:
            for line in section.lines:
                _safe_paragraph(line)

        if index < len(parsed.sections) - 1:
            st.divider()
