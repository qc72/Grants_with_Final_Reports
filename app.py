from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from parser import scan_zip_bytes

st.set_page_config(page_title="Grant Insights Explorer", page_icon="📚", layout="wide")


@st.cache_data(show_spinner="Reading project folders and documents...")
def cached_scan(zip_bytes: bytes) -> tuple[list[dict], str]:
    records, temp_dir = scan_zip_bytes(zip_bytes)
    return [r.to_dict() for r in records], temp_dir


def show_field(label: str, value: str) -> None:
    st.markdown(f"**{label}**")
    st.write(value or "—")


st.title("Grant Insights Explorer")
st.caption("Upload one ZIP, search all projects, inspect standardized insights, and open the likely final report.")

uploaded = st.file_uploader("Upload the master ZIP", type=["zip"])
if not uploaded:
    st.info("The ZIP should contain project folders such as `AVF 18.007 ...`. Nothing is saved permanently in this starter version.")
    st.stop()

records_raw, extraction_root = cached_scan(uploaded.getvalue())
# Keep the original dictionaries for nested candidate data.
records_by_id = {r["project_id"]: r for r in records_raw}

if not records_raw:
    st.error("No project folders were detected. Check that folders or project-note files contain an ID like `AVF 18.007`.")
    st.stop()

summary_rows = []
for r in records_raw:
    summary_rows.append({
        "Project ID": r["project_id"],
        "Title": r["title"],
        "Program": r["program"],
        "Academic year": r["academic_year"],
        "Funding": r["funding_amount"],
        "PI": r["principal_investigator"],
        "College": r["pi_college"],
        "CEL": r["cel_classification"],
        "Confidence": r["confidence"],
        "Report match": r["final_report_confidence"],
        "Quality flags": len(r["missing_expected_files"]),
    })
df = pd.DataFrame(summary_rows)

with st.sidebar:
    st.header("Filters")
    search = st.text_input("Search projects")
    programs = sorted(x for x in df["Program"].dropna().unique() if x)
    selected_programs = st.multiselect("Program", programs)
    report_conf = st.multiselect("Report-match confidence", ["High", "Medium", "Low", "None"])
    only_flags = st.checkbox("Only projects needing review")

filtered = df.copy()
if search:
    needle = search.casefold()
    matching_ids = []
    for r in records_raw:
        blob = "\n".join([
            str(r.get("project_id", "")), str(r.get("title", "")),
            str(r.get("summary_text", "")), str(r.get("highlight_text", "")),
            str(r.get("project_note_text", "")),
        ]).casefold()
        if needle in blob:
            matching_ids.append(r["project_id"])
    filtered = filtered[filtered["Project ID"].isin(matching_ids)]
if selected_programs:
    filtered = filtered[filtered["Program"].isin(selected_programs)]
if report_conf:
    filtered = filtered[filtered["Report match"].isin(report_conf)]
if only_flags:
    filtered = filtered[filtered["Quality flags"] > 0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Projects", len(filtered))
c2.metric("High-confidence reports", int((filtered["Report match"] == "High").sum()))
c3.metric("Needs review", int((filtered["Quality flags"] > 0).sum()))
c4.metric("Total projects loaded", len(df))

st.subheader("Project directory")
event = st.dataframe(
    filtered,
    width="stretch",
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "Quality flags": st.column_config.NumberColumn(help="Missing expected files or uncertain final-report detection"),
    },
)

selected_id = None
if event.selection.rows:
    selected_id = filtered.iloc[event.selection.rows[0]]["Project ID"]
elif not filtered.empty:
    selected_id = filtered.iloc[0]["Project ID"]

if not selected_id:
    st.warning("No project matches the current filters.")
    st.stop()

record = records_by_id[selected_id]
st.divider()
st.header(f"{record['project_id']} — {record['title'] or record['folder_name']}")
st.caption(f"Automatic final-report detection: {record['final_report_confidence']} confidence · score {record['final_report_score']}")

candidate_options = {c["filename"]: c["path"] for c in record["pdf_candidates"]}
chosen_report_path = record["final_report_path"]
if candidate_options:
    automatic_name = Path(record["final_report_path"]).name if record["final_report_path"] else next(iter(candidate_options))
    chosen_name = st.selectbox(
        "Final report file",
        options=list(candidate_options),
        index=list(candidate_options).index(automatic_name) if automatic_name in candidate_options else 0,
        help="The automatic choice is preselected. An administrator can select another PDF for this session.",
        key=f"report-choice-{selected_id}",
    )
    chosen_report_path = candidate_options[chosen_name]

overview, insights, report_tab, files_tab, quality_tab = st.tabs(
    ["Overview", "Insights", "Final report", "Files", "Quality review"]
)

with overview:
    left, right = st.columns(2)
    with left:
        show_field("Program", record["program"])
        show_field("Academic year", record["academic_year"])
        show_field("Funding", record["funding_amount"])
        show_field("Principal investigator", record["principal_investigator"])
        show_field("PI college / department", record["pi_college"])
    with right:
        show_field("Community partners", record["community_partners"])
        show_field("Student involvement", record["student_involvement"])
        show_field("Students involved", record["number_of_students"])
        show_field("CEL classification", record["cel_classification"])
        show_field("Evidence confidence", record["confidence"])

with insights:
    show_field("Community need", record["community_need"])
    show_field("Community impact", record["community_impact"])
    show_field("Publications / products", record["publications"])
    show_field("Brief assessment", record["brief_explanation"])
    if record["summary_text"]:
        with st.expander("Full generated summary", expanded=True):
            st.markdown(record["summary_text"])
    else:
        st.info("No summary DOCX was found.")

with report_tab:
    report_path = chosen_report_path
    if report_path and Path(report_path).exists():
        st.write(f"Selected file: **{Path(report_path).name}**")
        st.pdf(report_path, height=850)
        with open(report_path, "rb") as fh:
            st.download_button("Download selected report", fh, file_name=Path(report_path).name, mime="application/pdf")
    else:
        st.warning("No likely final report was found.")

with files_tab:
    for file_path in record["files"]:
        path = Path(file_path)
        rel = path.relative_to(extraction_root) if extraction_root in str(path) else path.name
        c_name, c_action = st.columns([5, 1])
        c_name.write(f"📄 {rel}")
        with open(path, "rb") as fh:
            c_action.download_button("Download", fh.read(), file_name=path.name, key=f"download-{selected_id}-{file_path}")

with quality_tab:
    if record["missing_expected_files"]:
        st.warning("Needs review: " + ", ".join(record["missing_expected_files"]))
    else:
        st.success("All expected files were found and the report match is reasonably confident.")

    candidates = pd.DataFrame(record["pdf_candidates"])
    if not candidates.empty:
        candidates = candidates[["filename", "score", "reasons", "path"]]
        candidates["reasons"] = candidates["reasons"].apply(lambda x: "\n".join(x))
        st.subheader("PDF candidate scores")
        st.dataframe(candidates.drop(columns=["path"]), width="stretch", hide_index=True)
        st.caption("Production version: add an administrator override and save the chosen report to the index.")

st.download_button(
    "Export filtered project index as CSV",
    filtered.to_csv(index=False).encode("utf-8"),
    file_name="grant_project_index.csv",
    mime="text/csv",
)
