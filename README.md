# Grant Insights Explorer

A starter Streamlit interface for a ZIP containing many project folders, typically named like `AVF 18.007 ...`.

## What it does

- Uploads one master ZIP.
- Safely extracts it and blocks ZIP path traversal.
- Finds project folders using IDs like `XXX 18.007`.
- Reads `summary*.docx`, `*highlight*.txt`, and `*project*note*.txt` case-insensitively.
- Scores every PDF to identify the most likely final report, even when the filename is inconsistent.
- Provides filters, an interactive project table, project details, a PDF viewer, source-file downloads, quality flags, and CSV export.

## Run locally for development

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Best deployment for non-Python users

Run the app once on an internal server and give users a browser URL. They install nothing.

```bash
docker build -t grant-insights .
docker run --rm -p 8501:8501 grant-insights
```

Then open `http://SERVER-NAME:8501`.

## Recommended production additions

1. Add organizational sign-in through your reverse proxy or identity provider.
2. Store the extracted documents in protected file/object storage rather than a temporary directory.
3. Store normalized metadata and manual report overrides in SQLite/PostgreSQL.
4. Run ingestion as an administrator-only action; make normal users read-only.
5. Add a review queue for low-confidence report matches and missing files.
6. Add full-text search over summaries, highlights, notes, and PDF text.
7. Log the source file and extraction date for every displayed value.

## Final-report scoring

The starter combines filename signals and PDF text signals. It boosts phrases such as `final report`, submission metadata, and final-report questionnaire language. It penalizes files containing `budget`, `application`, `proposal`, `worksheet`, or `interim`. Every candidate and reason is visible in the Quality Review tab.

## Important security notes

- Do not deploy sensitive grant documents to a public hosting service.
- Keep the app behind your organization’s authentication/VPN.
- Add malware scanning and upload-size limits before broad production use.
- Treat uploaded filenames and document text as untrusted input.
