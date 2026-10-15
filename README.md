# Bulk Certificate Generator

Submit many recipients in one request; the API validates each recipient, a background worker generates one PDF certificate per valid recipient, and the client tracks progress and downloads the results.

**Stack:** Python 3.14, FastAPI, SQLAlchemy 2, PostgreSQL 16, Jinja2 + WeasyPrint, pytest, Docker Compose.

## Run

```bash
docker compose up -d --build
```

Starts `db` (Postgres), `api` (port 8000) and `worker`. API docs: http://127.0.0.1:8000/docs, health check (includes the database): http://127.0.0.1:8000/health

More workers can be added at any time: `docker compose up -d --scale worker=3`.

<details>
<summary>Without Docker for the app</summary>

Needs Python 3.14 and Pango (`sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0`).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
docker compose up -d db
uvicorn app.main:app --reload     # terminal 1
python -m app.worker              # terminal 2
```
</details>

## Test

Tests run on the host, so first do the venv setup from "Without Docker for the app" above (Python 3.14, Pango, `pip install -r requirements-dev.txt`). Then:

```bash
docker compose up -d db
pytest
```

The tests use a real Postgres database (`certs_test`, created automatically) and never touch the main `certs` database. CI runs ruff and the tests on every push to `main` and on pull requests.

## Use

**Submit a job** (returns `202` and a `Location` header):

```bash
curl -X POST http://127.0.0.1:8000/api/v1/certificate-jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "certificate": {"course_name": "Drone Mapping 101", "issued_on": "2026-10-01", "issuer": "Aereo Academy"},
    "recipients": [
      {"name": "Asha Rao", "email": "asha@example.com"},
      {"name": "", "email": "not-an-email"}
    ]
  }'
```

```json
{"id": "b669dbc6-...", "status": "PENDING", "total_count": 2, "accepted_count": 1, "rejected_count": 1}
```

Rules: `course_name` 1 to 200 characters, `issued_on` a date, `issuer` optional; 1 to 1000 recipients, each with a `name` of 1 to 100 characters and a valid `email`. A malformed request (for example a missing `certificate` or an empty or oversized list) is rejected with `422` and nothing is stored. An invalid recipient only fails its own row.

**Track and retrieve:**

| Endpoint | Returns |
|---|---|
| `GET /api/v1/certificate-jobs/{id}` | Status and progress (`succeeded`, `failed`, `pending`, ...) |
| `GET /api/v1/certificate-jobs/{id}/certificates?status=FAILED&limit=50&offset=0` | Certificates with failure reasons, in submission order (`limit` 1 to 100) |
| `GET /api/v1/certificate-jobs/{id}/download` | ZIP of all generated PDFs |
| `GET /api/v1/certificates/{id}` | One certificate's details |
| `GET /api/v1/certificates/{id}/pdf` | One PDF |
| `POST /api/v1/certificate-jobs/{id}/retry` | Requeue certificates that failed with `GENERATION_ERROR` |

A job ends as `COMPLETED`, `PARTIALLY_FAILED` or `FAILED`. Failed certificates carry an `error_code`: `VALIDATION_ERROR` or `DUPLICATE_IN_JOB` (bad input, not retryable) or `GENERATION_ERROR` (server-side, retryable). Downloads and retries return `409` while the job is still running, or when there is nothing to download or retry.

**Safe retries of a submission:** send an `Idempotency-Key` header (for example a UUID). Repeating the request with the same key returns the original job (with `Idempotent-Replayed: true`) instead of creating a duplicate; reusing the key with a different body returns `422`.

## Design decisions

- **Background worker, not synchronous.** Rendering takes roughly 0.1 s per PDF (about 80 s for 1000 recipients with one worker, about 45 s with three), which is too long for one HTTP request, so the API returns `202` at once and a separate worker process does the work. A separate process (not FastAPI `BackgroundTasks`) survives API restarts and scales on its own.
- **Postgres as the queue.** Workers claim rows with `FOR UPDATE SKIP LOCKED`, so several workers never pick the same certificate. No extra broker needed at this scale.
- **One failure never blocks others.** Each recipient is validated separately and invalid rows are stored as `FAILED` with a reason. Each certificate is generated in its own transaction, so a rendering error fails only that certificate.
- **Crash recovery.** Certificates stuck in `PROCESSING` for 5 minutes (dead worker) go back to `PENDING`, and are marked `FAILED` after 3 attempts.
- **Progress is computed** with a `GROUP BY` on an indexed `(job_id, status)`, so there are no counters to drift.
- **Certificate fields** (not defined in the brief): name, course, issue date, optional issuer and a unique certificate number. `issued_on` comes from the client because it is the completion date, not the generation time.
- **Emails are lowercased** before the duplicate check.
- **Idempotent submission.** The key is stored on the job with a UNIQUE constraint and a hash of the request body. If two identical requests race, the database rejects the second insert and the API returns the first job.

## Limitations

- Tables are created with `create_all`, which never alters existing tables; production would use Alembic migrations.
- Idempotency keys are global and never expire; with authentication they would be scoped per client and cleaned up after some time.
- PDFs are on local disk; at scale they would go to object storage (S3).
- No authentication.
