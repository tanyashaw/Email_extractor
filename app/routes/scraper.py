"""
Scraper API routes.

Endpoints
---------
GET  /api/scraper/health   – Liveness check.
POST /api/scraper/extract  – Extract emails from a batch of URLs.
POST /api/scraper/export   – Export email results as a downloadable CSV.
"""

import io
import csv
import logging
import time
from typing import List

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.models.schemas import (
    ExtractionRequest,
    ExtractionSummary,
    ExportRequest,
    HealthResponse,
    EmailResult,
    ExtractionStatus,
    PageError,
)
from app.services.email_extractor import process_urls, extract_emails_from_html
from app.utils.validators import validate_urls

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scraper", tags=["scraper"])

# ---------------------------------------------------------------------------
# Configuration defaults (overridden by env-based settings in main.py)
# ---------------------------------------------------------------------------

MAX_URLS_PER_BATCH: int = 3       # Hard cap enforced at the route level.
REQUEST_TIMEOUT: int = 10         # Seconds per HTTP request.
DELAY_BETWEEN_REQUESTS: float = 1.0  # Conservative crawl delay.


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns a simple liveness signal confirming the backend is running.",
)
async def health_check() -> HealthResponse:
    """Liveness endpoint – no external dependencies required."""
    return HealthResponse(
        status="ok",
        message="Email Extractor backend is running.",
        version="1.0.0",
    )


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

@router.post(
    "/extract",
    response_model=ExtractionSummary,
    summary="Extract email addresses from company profile pages",
    description=(
        "Accepts up to 3 public company-profile URLs, fetches each page, "
        "and extracts all publicly displayed email addresses."
    ),
    status_code=status.HTTP_200_OK,
)
async def extract_emails(
    payload: ExtractionRequest,
    request: Request,
) -> ExtractionSummary:
    """
    Extract email addresses from a batch of public URLs.

    - Validates all submitted URLs.
    - Rejects the request if too many URLs are submitted.
    - Processes each URL sequentially with a polite crawl delay.
    - Returns structured results including per-page errors.
    """
    # Retrieve configurable limits from app state (set by main.py).
    max_urls: int = getattr(request.app.state, "max_urls_per_batch", MAX_URLS_PER_BATCH)
    timeout: int = getattr(request.app.state, "request_timeout", REQUEST_TIMEOUT)
    delay: float = getattr(request.app.state, "delay_between_requests", DELAY_BETWEEN_REQUESTS)

    raw_urls: List[str] = [str(u) for u in payload.urls]

    # Enforce batch size limit.
    if len(raw_urls) > max_urls:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Too many URLs submitted. Maximum allowed per request: {max_urls}. "
                f"Received: {len(raw_urls)}."
            ),
        )

    # Validate URL format.
    valid_urls, invalid_urls = validate_urls(raw_urls)

    if invalid_urls:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "One or more URLs are invalid.",
                "invalid_urls": invalid_urls,
            },
        )

    logger.info("Starting extraction for %d URL(s).", len(valid_urls))

    # Delegate to the service layer.
    outcome = process_urls(valid_urls, timeout=timeout, delay_seconds=delay)

    return ExtractionSummary(
        total_pages=outcome["total_pages"],
        processed_pages=outcome["processed_pages"],
        total_emails=outcome["total_emails"],
        results=outcome["results"],
        errors=outcome["errors"] if outcome["errors"] else None,
    )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@router.post(
    "/export",
    summary="Export extraction results as CSV",
    description=(
        "Accepts a list of email extraction results and streams a "
        "downloadable CSV file back to the caller."
    ),
    responses={
        200: {
            "content": {"text/csv": {}},
            "description": "CSV file containing email extraction results.",
        }
    },
)
async def export_results(payload: ExportRequest) -> StreamingResponse:
    """
    Convert extraction results to a CSV file and stream it as a download.

    CSV columns: email, source_url, status
    """
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["email", "source_url", "status"],
        lineterminator="\n",
    )
    writer.writeheader()

    for result in payload.results:
        writer.writerow(
            {
                "email": result.email,
                "source_url": result.source_url,
                "status": result.status.value,
            }
        )

    output.seek(0)
    csv_bytes = output.getvalue().encode("utf-8")

    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="email_extraction_results.csv"'
        },
    )
