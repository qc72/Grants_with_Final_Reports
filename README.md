# Grant Insights Explorer — Batch Edition

A working starter for a large collection of grant-project folders. Administrators upload several smaller ZIP batches; every batch is merged into one persistent database. Nontechnical users open a browser URL and search the combined collection.


## PDF viewer dependency

The app installs Streamlit with its PDF extra (`streamlit[pdf]`). If that optional viewer cannot load on a deployment, the app automatically renders the selected PDF one page at a time with PyMuPDF and still provides the original file for download.

## Included workflow

1. An administrator creates ZIP batches, ideally about 25–50 project folders each.
2. Each project folder is detected by an ID such as `AVF 18.007`.
3. The importer reads `summary*.docx`, `*highlight*.txt`, and `*project*note*.txt` case-insensitively.
4. Every PDF is scored using filename and document-content signals to find the likely final report.
5. A SHA-256 project fingerprint determines whether the project is new, changed, or unchanged.
6. New projects are inserted, changed projects are updated, and unchanged projects are skipped.
7. Users browse all batches together through the Streamlit interface.

## Main pages

- **Explore projects:** searchable directory, standardized insights, source text, PDF viewer, and downloads.
- **Review queue:** administrator correction of uncertain final-report choices.
- **Admin imports:** multiple browser ZIP uploads or one server-path ZIP import.
- **Import history:** run totals and project-level errors/warnings.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open the local URL shown by Streamlit, normally `http://localhost:8501`.

The included demo batch can be imported from the Admin page or from the command line:

```bash
python cli_ingest.py demo/AVF_18_007_batch.zip --batch-name "Demo batch"
```

## Run with Docker

Change the admin password in `docker-compose.yml`, then run:

```bash
docker compose up --build -d
```

Open `http://localhost:8501` or the corresponding server address.

The Docker volume preserves the SQLite database and imported documents across restarts. ZIP files placed in `./incoming` are mounted read-only at `/incoming` and can be imported through the server-path control.

## Batch structure

```text
batch_01.zip
├── AVF 18.001 - Project title/
│   ├── AVF 18.001 Summary.docx
│   ├── AVF_18.001_highlight.txt
│   ├── AVF_18.001_PROJECT_NOTE.txt
│   └── report-with-any-name.pdf
├── AVF 18.002 - Another title/
└── ...
```

The folders may be nested under year/program folders. The importer searches recursively.

## Database behavior

`project_id` is the unique project key. For each incoming project:

- no existing ID → **new**
- existing ID with a different fingerprint → **updated**
- existing ID with the same fingerprint → **skipped**

A saved manual final-report override is retained when a project is updated.

## Data folders

By default:

```text
data/
├── grants.db
└── documents/
    └── AVF_18_007/
```

Set `GRANT_INSIGHTS_HOME` to move all persistent data. You can separately set `GRANT_INSIGHTS_DB` and `GRANT_INSIGHTS_DOCUMENTS`.

## Security and production checklist

- Set `GRANT_INSIGHTS_ADMIN_PASSWORD`.
- Put the app behind your organization’s SSO, VPN, or authenticated reverse proxy.
- Keep sensitive documents off public hosting.
- Add antivirus/malware scanning if uploads come from untrusted users.
- Back up the data directory regularly.
- Restrict the server-path importer to trusted administrators.
- Keep batches under the configured upload size; use the server-path importer for larger ZIPs.
- Review low-confidence report matches before broad publication.

The importer validates ZIP paths, expanded size, entry count, and suspicious compression ratios before extraction. Python’s ZIP documentation specifically warns callers to validate filenames to prevent path traversal; the checks are implemented in `importer.py`.

## Scaling beyond SQLite

SQLite is appropriate for a single internal app and modest concurrent use. Move to PostgreSQL when you need multiple app instances, many simultaneous writers, enterprise audit controls, or advanced full-text search. The document folders can later move to S3, Azure Blob Storage, Google Cloud Storage, SharePoint, or another controlled repository.

## Metadata normalization

- `Category` is derived from the first three characters of the canonical project ID.
- Academic years are displayed as `YYYY-YYYY`; parenthetical activity notes are ignored.
