from __future__ import annotations

import json
import os
from pathlib import Path

import fitz

import pandas as pd
import streamlit as st

from config import DB_PATH, DOCUMENT_ROOT, ensure_directories
from database import (
    get_pdf_candidates,
    get_project,
    get_source_files,
    initialize_database,
    list_import_items,
    list_import_runs,
    list_projects,
    set_report_override,
)
from importer import import_zip_bytes, import_zip_path

st.set_page_config(page_title="Grant Insights Explorer", page_icon="📚", layout="wide")
ensure_directories()
initialize_database(DB_PATH)


def money_number(value: str) -> float:
    try:
        return float(value.replace("$", "").replace(",", "").strip())
    except (AttributeError, ValueError):
        return 0.0


def human_size(size: int) -> str:
    amount = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if amount < 1024 or unit == "GB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{size} B"


def show_field(label: str, value: str) -> None:
    st.markdown(f"**{label}**")
    st.write(value or "—")


def admin_allowed() -> bool:
    expected = os.getenv("GRANT_INSIGHTS_ADMIN_PASSWORD", "")
    if not expected:
        st.warning("Admin password is not configured. Set `GRANT_INSIGHTS_ADMIN_PASSWORD` before production use.")
        return True
    supplied = st.text_input("Admin password", type="password", key="admin-password")
    return supplied == expected


def project_quality(row: dict) -> str:
    missing = json.loads(row.get("missing_expected_files_json") or "[]")
    if row.get("selected_report_path"):
        missing = [
            flag for flag in missing
            if flag not in {"confident final-report PDF", "final-report selection needs review"}
        ]
    if missing or (not row.get("selected_report_path") and row.get("final_report_confidence") in {"Low", "None"}):
        return "Needs review"
    return "Ready"


def resolve_document(project: dict, relative_path: str) -> Path:
    return DOCUMENT_ROOT / project["storage_folder"] / relative_path


def display_pdf(path: Path) -> None:
    """Display a PDF, falling back to page images when Streamlit's PDF extra is unavailable."""
    if hasattr(st, "pdf"):
        try:
            st.pdf(path.read_bytes(), height=850)
            return
        except Exception:
            # st.pdf exists in recent Streamlit versions even when the optional
            # streamlit-pdf dependency is not installed. In that case it raises
            # StreamlitAPIException. The image fallback below keeps the app usable.
            pass

    try:
        with fitz.open(path) as document:
            page_count = document.page_count
            if page_count < 1:
                st.warning("This PDF contains no viewable pages.")
                return

            st.info(
                "The native PDF viewer is unavailable, so this report is being "
                "shown one page at a time. The complete PDF is available from "
                "the download button below."
            )
            page_number = st.number_input(
                "Page",
                min_value=1,
                max_value=page_count,
                value=1,
                step=1,
                key=f"pdf-page-{path.as_posix()}",
            )
            page = document.load_page(int(page_number) - 1)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            st.image(
                pixmap.tobytes("png"),
                caption=f"Page {int(page_number)} of {page_count}",
                width="stretch",
            )
    except Exception as exc:
        st.warning(
            "The PDF preview could not be generated. Use the download button "
            f"below to open the report. Details: {exc}"
        )


page = st.sidebar.radio("Navigation", ["Explore projects", "Review queue", "Admin imports", "Import history"])
st.sidebar.caption(f"Database: {DB_PATH.name}")

if page == "Explore projects":
    st.title("Grant Insights Explorer")
    st.caption("Search all imported batches as one collection. Normal viewers never need Python or the original ZIP files.")

    projects = list_projects(DB_PATH)
    if not projects:
        st.info("No projects have been imported. An administrator can add one or more ZIP batches from **Admin imports**.")
        st.stop()

    rows = []
    for project in projects:
        rows.append(
            {
                "Project ID": project["project_id"],
                "Title": project["title"],
                "Category": project["category"],
                "Program": project["program"],
                "Academic year": project["academic_year"],
                "Funding": project["funding_amount"],
                "PI": project["principal_investigator"],
                "College": project["pi_college"],
                "Updated": project["updated_at"],
            }
        )
    frame = pd.DataFrame(rows)

    with st.sidebar:
        st.header("Filters")
        search = st.text_input("Search")
        categories = sorted(value for value in frame["Category"].dropna().unique() if value)
        selected_categories = st.multiselect("Category", categories)
        programs = sorted(value for value in frame["Program"].dropna().unique() if value)
        selected_programs = st.multiselect("Program", programs)
        years = sorted(value for value in frame["Academic year"].dropna().unique() if value)
        selected_years = st.multiselect("Academic year", years)

    filtered = frame.copy()
    if search:
        needle = search.casefold()
        matched = []
        for project in projects:
            blob = "\n".join(
                str(project.get(key, ""))
                for key in (
                    "project_id", "title", "category", "program", "principal_investigator", "pi_college",
                    "community_partners", "community_need", "community_impact", "publications",
                    "summary_text", "highlight_text", "project_note_text",
                )
            ).casefold()
            if needle in blob:
                matched.append(project["project_id"])
        filtered = filtered[filtered["Project ID"].isin(matched)]
    if selected_categories:
        filtered = filtered[filtered["Category"].isin(selected_categories)]
    if selected_programs:
        filtered = filtered[filtered["Program"].isin(selected_programs)]
    if selected_years:
        filtered = filtered[filtered["Academic year"].isin(selected_years)]

    total_funding = sum(money_number(value) for value in frame["Funding"])
    c1, c2, c3 = st.columns(3)
    c1.metric("Projects shown", len(filtered))
    c2.metric("Total projects", len(frame))
    c3.metric("Recorded funding", f"${total_funding:,.0f}")

    st.subheader("Project directory")
    event = st.dataframe(
        filtered,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
    )
    if filtered.empty:
        st.warning("No projects match the selected filters.")
        st.stop()
    selected_id = filtered.iloc[event.selection.rows[0] if event.selection.rows else 0]["Project ID"]
    project = get_project(DB_PATH, selected_id)
    assert project is not None
    files = get_source_files(DB_PATH, selected_id)

    st.divider()
    st.header(f"{project['project_id']} — {project['title'] or project['folder_name']}")
    st.caption(
        f"Source batch: {project['source_batch']} · Updated: {project['updated_at']}"
    )

    overview, insights, evidence, report_tab, files_tab = st.tabs(
        ["Overview", "Insights", "Source text", "Final report", "Files"]
    )
    with overview:
        left, right = st.columns(2)
        with left:
            show_field("Category", project["category"])
            show_field("Program", project["program"])
            show_field("Academic year", project["academic_year"])
            show_field("Funding", project["funding_amount"])
            show_field("Principal investigator", project["principal_investigator"])
            show_field("PI college / department", project["pi_college"])
        with right:
            show_field("Community partners", project["community_partners"])
            show_field("Student involvement", project["student_involvement"])
            show_field("Students involved", project["number_of_students"])
            show_field("CEL classification", project["cel_classification"])

    with insights:
        show_field("Community need", project["community_need"])
        show_field("Community impact", project["community_impact"])
        show_field("Publications / products", project["publications"])
        show_field("Brief assessment", project["brief_explanation"])
        if project["summary_text"]:
            with st.expander("Full summary", expanded=True):
                st.markdown(project["summary_text"])

    with evidence:
        for heading, value in (
            ("Highlight", project["highlight_text"]),
            ("Project note", project["project_note_text"]),
        ):
            with st.expander(heading, expanded=heading == "Highlight"):
                st.text(value or "Not available")

    with report_tab:
        relative_report = project["effective_report_path"]
        if relative_report:
            report_path = resolve_document(project, relative_report)
            if report_path.exists():
                st.write(f"Selected file: **{report_path.name}**")
                display_pdf(report_path)
                st.download_button(
                    "Download selected report", report_path.read_bytes(), file_name=report_path.name,
                    mime="application/pdf", key=f"report-download-{selected_id}",
                )
            else:
                st.error("The database points to a report that is missing from document storage.")
        else:
            st.warning("No final report has been selected.")
    with files_tab:
        for item in files:
            path = resolve_document(project, item["relative_path"])
            c1, c2, c3 = st.columns([5, 1, 1])
            c1.write(f"📄 {item['relative_path']}")
            c2.caption(human_size(item["size_bytes"]))
            if path.exists():
                c3.download_button(
                    "Download", path.read_bytes(), file_name=item["filename"],
                    key=f"source-{selected_id}-{item['id']}",
                )

    st.download_button(
        "Export filtered index as CSV", filtered.to_csv(index=False).encode("utf-8"),
        file_name="grant_project_index.csv", mime="text/csv",
    )

elif page == "Review queue":
    st.title("Review queue")
    st.caption("Select the correct final report for projects that need manual review.")
    if not admin_allowed():
        st.error("Enter the administrator password to continue.")
        st.stop()

    projects = [project for project in list_projects(DB_PATH) if project_quality(project) == "Needs review"]
    if not projects:
        st.success("No projects currently require review.")
        st.stop()

    options = {f"{project['project_id']} — {project['title'] or project['folder_name']}": project for project in projects}
    label = st.selectbox("Project", list(options))
    project = options[label]
    candidates = get_pdf_candidates(DB_PATH, project["project_id"])
    if not candidates:
        st.error("No PDF candidates are available for this project.")
        st.stop()

    candidate_map = {item["filename"]: item["relative_path"] for item in candidates}
    current = project["effective_report_path"]
    current_name = next((name for name, path in candidate_map.items() if path == current), list(candidate_map)[0])
    selected_name = st.selectbox(
        "Correct final report", list(candidate_map), index=list(candidate_map).index(current_name)
    )
    preview_path = resolve_document(project, candidate_map[selected_name])
    if preview_path.exists():
        display_pdf(preview_path)
    c1, c2 = st.columns(2)
    if c1.button("Save override", type="primary"):
        set_report_override(DB_PATH, project["project_id"], candidate_map[selected_name])
        st.success("Saved. This file will now be shown as the selected final report.")
        st.rerun()
    if c2.button("Return to automatic selection"):
        set_report_override(DB_PATH, project["project_id"], None)
        st.success("Manual override removed.")
        st.rerun()

elif page == "Admin imports":
    st.title("Admin imports")
    st.caption("Upload several smaller ZIP batches. They are merged into one database by project ID and fingerprint.")
    if not admin_allowed():
        st.error("Enter the administrator password to continue.")
        st.stop()

    uploads = st.file_uploader(
        "Select one or more ZIP batches",
        type=["zip"],
        accept_multiple_files=True,
        help="A useful starting point is 25–50 project folders per ZIP.",
    )
    if uploads and st.button("Import selected batches", type="primary"):
        combined_results = []
        for upload_index, upload in enumerate(uploads, start=1):
            st.subheader(f"Batch {upload_index}: {upload.name}")
            progress_bar = st.progress(0.0)
            status_box = st.empty()

            def progress(current: int, total: int, project_id: str) -> None:
                progress_bar.progress(current / max(total, 1))
                status_box.write(f"Processing {current} of {total}: **{project_id}**")

            result = import_zip_bytes(
                upload.getvalue(), batch_name=upload.name, db_path=DB_PATH,
                document_root=DOCUMENT_ROOT, progress=progress,
            )
            combined_results.append(result)
            progress_bar.progress(1.0)
            status_box.write(f"Finished: **{result['status']}**")
            st.json(result)
        st.success("Selected batches were processed. Open Explore projects or Review queue to inspect the results.")

    st.divider()
    st.subheader("Optional server-path import")
    st.caption("Useful when a batch is too large for browser upload. The ZIP must already be accessible to the server.")
    local_path = st.text_input("Server ZIP path", placeholder="/data/incoming/batch_04.zip")
    if st.button("Import server ZIP"):
        path = Path(local_path).expanduser().resolve()
        if not path.exists() or path.suffix.lower() != ".zip":
            st.error("Enter an existing .zip path on the server.")
        else:
            progress_bar = st.progress(0.0)
            status_box = st.empty()

            def local_progress(current: int, total: int, project_id: str) -> None:
                progress_bar.progress(current / max(total, 1))
                status_box.write(f"Processing {current} of {total}: **{project_id}**")

            result = import_zip_path(
                path, batch_name=path.name, db_path=DB_PATH,
                document_root=DOCUMENT_ROOT, progress=local_progress,
            )
            st.json(result)

elif page == "Import history":
    st.title("Import history")
    runs = list_import_runs(DB_PATH)
    if not runs:
        st.info("No imports have run yet.")
        st.stop()
    frame = pd.DataFrame(runs)
    st.dataframe(
        frame[[
            "id", "batch_name", "started_at", "completed_at", "status", "detected_count",
            "new_count", "updated_count", "skipped_count", "review_count", "error_count",
        ]],
        hide_index=True,
        width="stretch",
    )
    run_id = st.selectbox("Show project-level results", [int(row["id"]) for row in runs])
    items = list_import_items(DB_PATH, run_id)
    st.dataframe(pd.DataFrame(items), hide_index=True, width="stretch")
