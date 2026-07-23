from __future__ import annotations

from summary_renderer import (
    _parse_assessment,
    _parse_evidence,
    _parse_facts,
    parse_summary,
)


def section(parsed, kind: str):
    return next(item for item in parsed.sections if item.kind == kind)


def test_accepts_item_header_and_headings_without_periods():
    text = """Grant Summary: AVF 18.005 — Example
1 Narrative summary
Readable narrative.
2 Key facts
Item | Detail
Grant ID | AVF 18.005
Academic year | 2017-2018 (activities 2018-19)
3 CEL evidence assessment
Criterion | Met? | Explanation
Community need | Yes | Demonstrated.
Confidence | 0.60 | Internal score.
4 Evidence quotes
Student learning
Quotes: “Example quote.”
Source file: Final Report.pdf
Why it matters: Demonstrates learning.
5 Missing or uncertain information
One missing item.
"""
    parsed = parse_summary(text)
    assert [item.kind for item in parsed.sections] == [
        "narrative", "facts", "assessment", "evidence", "missing"
    ]
    facts, leftovers = _parse_facts(section(parsed, "facts").lines)
    assert leftovers == []
    assert ("Grant ID", "AVF 18.005") in facts
    assert ("Academic year", "2017-2018") in facts

    assessment, notes, leftovers = _parse_assessment(section(parsed, "assessment").lines)
    assert assessment == [("Community need", "Yes", "Demonstrated.")]
    assert notes == []
    assert leftovers == []

    evidence = _parse_evidence(section(parsed, "evidence").lines)
    assert evidence[0]["quote"] == "“Example quote.”"
    assert evidence[0]["source"] == "Final Report.pdf"


def test_recovers_tables_appended_by_legacy_importer():
    text = """Grant Summary: ECG 17.030 — Example
1. Narrative summary
Narrative.
2. Key facts
3. CEL evidence assessment
4. Evidence quotes
Evidence label
Quote: “Quote.”
Source: report.pdf
Why it matters: Useful.
5. Missing or uncertain information
A genuine missing item.
Field | Detail
Grant ID | ECG 17.030
Funding amount | $1,000
Criterion | Met? | Explanation
Community need | Yes | Demonstrated.
Confidence | 0.80 | Internal score.
"""
    parsed = parse_summary(text)
    facts, _ = _parse_facts(section(parsed, "facts").lines)
    assessment, _, _ = _parse_assessment(section(parsed, "assessment").lines)
    assert len(facts) == 2
    assert len(assessment) == 1
    assert section(parsed, "missing").lines == ["A genuine missing item."]


def test_accepts_unnumbered_section_headings():
    parsed = parse_summary("""Grant Summary: ABC 20.001 — Example
Narrative summary
Narrative.
Key project facts
Attribute | Value
Grant ID | ABC 20.001
CEL evidence assessment
Assessment criterion | Status | Evidence / explanation
Learning integration | Yes | Demonstrated.
Evidence quotes
Output
Evidence quote: “Created.”
Source document: report.pdf
Relevance: Shows an output.
Information gaps
None documented.
""")
    assert [item.kind for item in parsed.sections] == [
        "narrative", "facts", "assessment", "evidence", "missing"
    ]
