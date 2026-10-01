# Email Extractor — Backend

A **FastAPI** backend that extracts publicly displayed email addresses from
company profile pages on publicly accessible websites.

> **Scope:** MVP demo — processes 2–3 URLs per request.  
> **Not included:** authentication, database, AI features, background workers.

---

## Project Structure

```
backend/
├── app/
│   ├── main.py                  ← FastAPI application entry point
│   ├── routes/
│   │   └── scraper.py           ← API endpoints
│   ├── services/
│   │   └── email_extractor.py   ← HTML parsing & email extraction logic
│   ├── models/
│   │   └── schemas.py           ← Pydantic request / response models
│   └── utils/
│       └── validators.py        ← URL & email validation helpers
├── tests/
│   └── test_extractor.py        ← pytest test suite
├── sample_data/                 ← Fictional HTML pages for local testing
│   ├── company_1.html
│   ├── company_2.html           ← No email (tests graceful handling)
│   └── company_3.html
├── output/                      ← CSV exports land here (created on demand)
├── requirements.txt
├── .env.example
└── README.md  ← you are here
```

---

## Prerequisites

| Tool    | Version  |
|---------|----------|
| Python  | ≥ 3.11   |
| pip     | ≥ 23     |

---

## Installation

```bash
# 1. Navigate to the backend directory
cd backend

# 2. Create and activate a virtual environment
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. (Optional) Copy and customise environment variables
copy .env.example .env    # Windows
# cp .env.example .env    # macOS / Linux
```

---

## Starting the Server

```bash
# From the backend/ directory, with the venv activated:
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at:

| URL                            | Purpose             |
|-------------------------------|---------------------|
| http://localhost:8000/         | API metadata        |
| http://localhost:8000/docs     | Swagger UI          |
| http://localhost:8000/redoc    | ReDoc documentation |

---

## API Endpoints

### `GET /api/scraper/health`

Liveness check — confirms the backend is running.

**Response:**
```json
{
  "status": "ok",
  "message": "Email Extractor backend is running.",
  "version": "1.0.0"
}
```

---

### `POST /api/scraper/extract`

Extract email addresses from a list of public URLs (max 3 per request by
default).

**Request body:**
```json
{
  "urls": [
    "https://example.com/company/1",
    "https://example.com/company/2"
  ]
}
```

**Response:**
```json
{
  "total_pages": 2,
  "processed_pages": 2,
  "total_emails": 2,
  "results": [
    {
      "email": "contact@example.com",
      "source_url": "https://example.com/company/1",
      "status": "success"
    },
    {
      "email": "info@example.com",
      "source_url": "https://example.com/company/2",
      "status": "success"
    }
  ],
  "errors": null
}
```

---

### `POST /api/scraper/export`

Accept a list of extraction results and return a downloadable CSV file.

**Request body:**
```json
{
  "results": [
    {
      "email": "contact@example.com",
      "source_url": "https://example.com/company/1",
      "status": "success"
    }
  ]
}
```

**Response:** `text/csv` download — `email_extraction_results.csv`

---

## Local Testing with Sample HTML Files

The `sample_data/` directory contains three fictional company pages.  To test
extraction against them **without hitting any real website**, serve the files
with Python's built-in HTTP server:

```bash
# From the backend/ directory:
python -m http.server 9000 --directory sample_data
```

Then call the extract endpoint:

```bash
curl -X POST http://localhost:8000/api/scraper/extract \
  -H "Content-Type: application/json" \
  -d '{
    "urls": [
      "http://localhost:9000/company_1.html",
      "http://localhost:9000/company_2.html",
      "http://localhost:9000/company_3.html"
    ]
  }'
```

Expected behaviour:
- `company_1.html` → 3 email addresses extracted.
- `company_2.html` → 4 email addresses extracted.
- `company_3.html` → 0 email addresses (gracefully handled).

---

## Running the Tests

```bash
# From the backend/ directory, with the venv activated:
pytest tests/ -v
```

All external HTTP requests are mocked — no network access required.

---

## Environment Variables

See `.env.example` for all configurable options.

| Variable                  | Default                                      | Description                           |
|--------------------------|----------------------------------------------|---------------------------------------|
| `ALLOWED_ORIGINS`         | `http://localhost:5173,http://127.0.0.1:5173` | CORS allowed origins                  |
| `REQUEST_TIMEOUT`         | `10`                                         | HTTP request timeout (seconds)        |
| `MAX_URLS_PER_BATCH`      | `3`                                          | Max URLs per `/extract` request       |
| `DELAY_BETWEEN_REQUESTS`  | `1.0`                                        | Polite crawl delay between requests   |

---

## Extending to ~1,000 Pages

When you are ready to process larger batches (subject to site permissions and
rate limits):

1. Increase `MAX_URLS_PER_BATCH` and introduce pagination in the frontend.
2. Increase `DELAY_BETWEEN_REQUESTS` (e.g., 2–5 s) to be respectful.
3. Add a background task queue (e.g., Celery + Redis) for long-running jobs.
4. Store results in a database (e.g., PostgreSQL via SQLAlchemy).
5. Implement proper logging and monitoring.

---

## Ethical Usage

This tool is designed to extract **only publicly displayed** contact information.

- Do **not** use it to bypass CAPTCHA, authentication, paywalls, or access controls.
- Always comply with the target website's `robots.txt` and Terms of Service.
- Obtain explicit permission before scraping any commercial website at scale.
