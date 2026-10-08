# Bulk Certificate Generator

A backend API (FastAPI + SQLAlchemy + SQLite + ReportLab) that accepts a list of recipients in **one request**, generates a PDF certificate for each from a single predefined template, tracks progress, and lets the client download the results.

## Setup

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

- API: http://localhost:8000  
- Interactive docs (Swagger): http://localhost:8000/docs

Tables are created automatically on startup. Optional environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./certificates.db` | Any SQLAlchemy URL (e.g. PostgreSQL) |
| `CERT_STORAGE_DIR` | `./generated_certificates` | Where PDFs are written |
| `MAX_RECIPIENTS` | `1000` | Max recipients per request |

## Run tests

```bash
python -m pytest
```
Tests use a throw-away temp database and temp storage folder; nothing in your real data is touched.

## API

### 1. Submit a generation request — `POST /api/jobs/`

```bash
curl -X POST http://localhost:8000/api/jobs/ \
  -H "Content-Type: application/json" \
  -d '{
    "course_title": "Python for Beginners",
    "issuer_name": "Acme Academy",
    "issue_date": "2026-10-01",
    "recipients": [
      {"name": "Asha Verma", "email": "asha@example.com"},
      {"name": "Rahul Singh", "email": "rahul@example.com"},
      {"name": "", "email": "broken"}
    ]
  }'
```
`issuer_name` and `issue_date` are optional (default: "Certificate Authority" / today).

Response `202 Accepted` (returned immediately; generation continues in the background):
```json
{
  "id": "9f1c...", "status": "PENDING", "course_title": "Python for Beginners",
  "issuer_name": "Acme Academy", "issue_date": "2026-10-01",
  "total": 3, "succeeded": 0, "failed": 1, "pending": 2, "progress": 0.3333,
  "created_at": "...", "completed_at": null
}
```
Note the invalid third recipient is already counted as `failed`.

### 2. Check progress — `GET /api/jobs/{job_id}/`
Poll this. `progress` is `(succeeded + failed) / total`.

Job `status` values:

| Status | Meaning |
|---|---|
| `PENDING` | Accepted, worker not started |
| `PROCESSING` | Worker running |
| `COMPLETED` | Every certificate succeeded |
| `COMPLETED_WITH_ERRORS` | Some succeeded, some failed |
| `FAILED` | Nothing succeeded |

### 3. List certificates — `GET /api/jobs/{job_id}/certificates/`
Query params: `status=PENDING|COMPLETED|FAILED`, `limit` (1-500, default 100), `offset`.

```json
{
  "total": 3, "limit": 100, "offset": 0,
  "items": [
    {"id": "ab12...", "index": 0, "recipient_name": "Asha Verma", "recipient_email": "asha@example.com",
     "status": "COMPLETED", "error": null, "download_url": "/api/certificates/ab12.../download/"},
    {"id": "cd34...", "index": 2, "recipient_name": null, "recipient_email": "broken",
     "status": "FAILED", "error": "name: String should have at least 1 character; email: value error, invalid email address",
     "download_url": null}
  ]
}
```
`index` is the recipient's position in the original request, so failures can be mapped back to input rows.

### 4. Download
- One certificate: `GET /api/certificates/{certificate_id}/download/` → `application/pdf`  
  (`409` if that certificate failed / isn't ready, `404` if unknown)
- Whole job: `GET /api/jobs/{job_id}/download/` → zip of all *successful* PDFs (`409` if none yet)

```bash
curl -OJ http://localhost:8000/api/jobs/<job_id>/download/
```

## Design decisions

**Background processing (not synchronous).** A request may contain hundreds of recipients; rendering them inside the HTTP request would risk timeouts and tie up the client. `POST` therefore validates, stores everything, returns `202` with a job id, and generation runs via FastAPI `BackgroundTasks`. The client polls the status endpoint. A sync `def` task runs in a threadpool, so the API stays responsive while a job runs (verified with a 300-recipient job).
- *Alternative considered:* Celery/RQ + Redis. It's the right choice for production (survives restarts, scales across workers, retries) but adds infrastructure that isn't justified for this scope. The processing logic lives in `services.process_job(job_id)`, which takes only a job id, so moving it to a Celery task is a ~3 line change.
- *Known limitation:* if the server process dies mid-job, that job stays `PROCESSING` and its unprocessed certificates stay `PENDING`. A queue with persistence (or a startup sweep that re-queues `PENDING` jobs) would fix that.

**Two levels of validation.**
1. *Request level* (FastAPI/Pydantic → `422`): missing course title, bad date, empty list, more than `MAX_RECIPIENTS`. These make the whole request meaningless, so it is rejected.
2. *Recipient level* (stored as `FAILED` with a reason): missing/blank name, invalid email, non-object entries, duplicate email within the job. One bad row must not block the others, so the job is still accepted and the client sees exactly which rows failed and why. Recipients are typed `list[Any]` at request level on purpose and validated one-by-one in `services.create_job`.

**Failure isolation.** Each certificate is generated inside its own `try/except` and committed individually. A failure marks only that certificate `FAILED` (with the error) and processing continues. Per-certificate commits also give live progress. A top-level guard ensures that even a worker crash never leaves a job stuck in `PROCESSING`.

**Atomic file writes.** The PDF is written to a `.tmp` file then `os.replace`d, so a crash can't leave a corrupt PDF at the final path.

**Storage.** Jobs and certificates are rows in a relational DB (SQLite by default; any SQLAlchemy DB via `DATABASE_URL`). PDFs live on disk under `CERT_STORAGE_DIR/<job_id>/<certificate_id>.pdf`; the DB stores the path. Counts for status are computed with a `GROUP BY` query rather than stored counters, so they can never drift from reality.

**Template.** One hard-coded landscape A4 template in `app/generator.py` (ReportLab). Long names/course titles auto-shrink to fit. Built-in PDF fonts are used, so characters outside Latin-1 (e.g. Devanagari, CJK) are not rendered. Supporting them means registering a Unicode TTF font.

**Duplicates.** A duplicate email *within one job* is rejected (almost always a data-entry mistake). The same email in *different* jobs is allowed.

**Not included (deliberately):** authentication, email delivery, retries, multiple templates.

## Project layout

```
app/
  main.py        FastAPI app, startup (creates tables)
  api.py         HTTP endpoints
  services.py    create_job (validation) + process_job (background worker)
  generator.py   PDF template rendering
  models.py      Job, Certificate tables
  schemas.py     Request/response models and recipient validation
  database.py    Engine / session
  config.py      Env-based settings
tests/           27 tests: job creation, validation, generation, status/progress, failure isolation, retrieval
```
