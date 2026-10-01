"""
FastAPI application entry point.

Responsibilities
----------------
- Create and configure the FastAPI application instance.
- Register CORS middleware (allow React dev server on http://localhost:5173).
- Mount the scraper router.
- Provide a root endpoint with API metadata.
- Add global exception handling for unhandled errors.
- Propagate runtime configuration from environment variables to app.state so
  that route handlers can pick it up without importing settings directly.
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routes.scraper import router as scraper_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment / configuration
# ---------------------------------------------------------------------------

load_dotenv()  # Load .env file if present (silently ignored if absent).

# Allowed origins for CORS.  The React dev server runs on port 5173 by default.
_raw_origins: str = os.getenv(
    "ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
)
ALLOWED_ORIGINS: list[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]

REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "10"))
MAX_URLS_PER_BATCH: int = int(os.getenv("MAX_URLS_PER_BATCH", "3"))
DELAY_BETWEEN_REQUESTS: float = float(os.getenv("DELAY_BETWEEN_REQUESTS", "1.0"))

APP_VERSION: str = "1.0.0"


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown hooks)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """Store runtime config on app.state so routes can access it."""
    app.state.request_timeout = REQUEST_TIMEOUT
    app.state.max_urls_per_batch = MAX_URLS_PER_BATCH
    app.state.delay_between_requests = DELAY_BETWEEN_REQUESTS

    logger.info(
        "Email Extractor backend v%s starting — "
        "max_urls=%d, timeout=%ds, delay=%.1fs",
        APP_VERSION,
        MAX_URLS_PER_BATCH,
        REQUEST_TIMEOUT,
        DELAY_BETWEEN_REQUESTS,
    )
    yield
    logger.info("Email Extractor backend shutting down.")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Email Extractor API",
    description=(
        "A FastAPI backend that extracts publicly displayed email addresses "
        "from company profile pages.  Built for demonstration purposes; "
        "does NOT bypass any access restrictions."
    ),
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(scraper_router)

# ---------------------------------------------------------------------------
# Root endpoint
# ---------------------------------------------------------------------------

@app.get("/", tags=["root"], summary="API root")
async def root() -> dict:
    """Returns basic metadata about the API."""
    return {
        "name": "Email Extractor API",
        "version": APP_VERSION,
        "docs": "/docs",
        "health": "/api/scraper/health",
        "endpoints": {
            "extract": "POST /api/scraper/extract",
            "export": "POST /api/scraper/export",
            "health": "GET  /api/scraper/health",
        },
    }


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for any unhandled exception; returns a generic 500 response."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected error occurred.  Please try again later.",
            "path": str(request.url),
        },
    )
