"""
Pydantic models (schemas) for request and response validation.
"""

from typing import List, Optional
from pydantic import BaseModel, HttpUrl, field_validator, model_validator
from enum import Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ExtractionStatus(str, Enum):
    """Status of an individual URL extraction attempt."""
    SUCCESS = "success"
    NO_EMAILS = "no_emails"
    ERROR = "error"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------

class ExtractionRequest(BaseModel):
    """
    Request body for POST /api/scraper/extract.

    Accepts a list of public company profile URLs to scrape for email
    addresses.  The list is capped at MAX_URLS_PER_BATCH (default 3).
    """

    urls: List[HttpUrl]

    @field_validator("urls")
    @classmethod
    def urls_must_not_be_empty(cls, v: List[HttpUrl]) -> List[HttpUrl]:
        if not v:
            raise ValueError("At least one URL must be provided.")
        return v

    model_config = {
        "json_schema_extra": {
            "example": {
                "urls": [
                    "https://example.com/company/1",
                    "https://example.com/company/2",
                ]
            }
        }
    }


class ExportRequest(BaseModel):
    """
    Request body for POST /api/scraper/export.

    Accepts a list of email extraction results to be exported as a CSV file.
    """

    results: List["EmailResult"]

    @field_validator("results")
    @classmethod
    def results_must_not_be_empty(cls, v: List["EmailResult"]) -> List["EmailResult"]:
        if not v:
            raise ValueError("At least one result is required for export.")
        return v

    model_config = {
        "json_schema_extra": {
            "example": {
                "results": [
                    {
                        "email": "contact@example.com",
                        "source_url": "https://example.com/company/1",
                        "status": "success",
                    }
                ]
            }
        }
    }


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------

class EmailResult(BaseModel):
    """
    Represents a single extracted email address together with its provenance.
    """

    email: str
    source_url: str
    status: ExtractionStatus

    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "contact@example.com",
                "source_url": "https://example.com/company/1",
                "status": "success",
            }
        }
    }


class PageError(BaseModel):
    """Details about a URL that could not be processed successfully."""

    url: str
    error: str


class ExtractionSummary(BaseModel):
    """
    Top-level response for POST /api/scraper/extract.

    Provides aggregate statistics and a flat list of all email results across
    all submitted URLs.
    """

    total_pages: int
    processed_pages: int
    total_emails: int
    results: List[EmailResult]
    errors: Optional[List[PageError]] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "total_pages": 2,
                "processed_pages": 2,
                "total_emails": 2,
                "results": [
                    {
                        "email": "contact@example.com",
                        "source_url": "https://example.com/company/1",
                        "status": "success",
                    },
                    {
                        "email": "info@example.com",
                        "source_url": "https://example.com/company/2",
                        "status": "success",
                    },
                ],
                "errors": [],
            }
        }
    }


class HealthResponse(BaseModel):
    """Response for GET /api/scraper/health."""

    status: str
    message: str
    version: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "ok",
                "message": "Email Extractor backend is running.",
                "version": "1.0.0",
            }
        }
    }


# Allow forward references to resolve (ExportRequest references EmailResult).
ExportRequest.model_rebuild()
