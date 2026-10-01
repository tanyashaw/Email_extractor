"""
Email extraction service.

Responsibilities
----------------
- Fetch publicly accessible HTML pages via *requests*.
- Parse the HTML with BeautifulSoup.
- Extract email addresses from:
    * Visible page text (regex scan).
    * ``mailto:`` anchor href attributes.
- Deduplicate (case-insensitive) within each page.
- Preserve source URL provenance for every extracted address.
- Return structured, JSON-compatible results.
- Handle network errors and pages with no addresses gracefully.

What this service intentionally does NOT do
--------------------------------------------
- Bypass CAPTCHA, authentication, paywalls, or any access restriction.
- Follow redirects beyond the standard requests default (allow_redirects=True).
- Store any data persistently.
"""

import re
import time
import logging
from typing import List, Dict, Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.utils.validators import EMAIL_REGEX, is_valid_url
from app.models.schemas import EmailResult, ExtractionStatus, PageError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_from_text(text: str) -> List[str]:
    """
    Scan *text* with the shared EMAIL_REGEX and return all unique matches,
    normalised to lowercase.
    """
    raw_matches: List[str] = EMAIL_REGEX.findall(text)
    return list({m.lower() for m in raw_matches})


def _extract_from_mailto(soup: BeautifulSoup) -> List[str]:
    """
    Find all ``<a href="mailto:…">`` anchors and return the email addresses,
    normalised to lowercase.
    """
    emails: set = set()
    for anchor in soup.find_all("a", href=True):
        href: str = anchor["href"]
        if href.lower().startswith("mailto:"):
            # Strip the scheme and any query-string parameters (subject=, body=…)
            raw: str = href[len("mailto:"):].split("?")[0].strip()
            # A single mailto: can technically contain multiple comma-separated
            # addresses; handle each one individually.
            for part in raw.split(","):
                part = part.strip().lower()
                if part and EMAIL_REGEX.fullmatch(part):
                    emails.add(part)
    return list(emails)


def _deduplicate(emails: List[str]) -> List[str]:
    """Return *emails* with duplicates removed while preserving order."""
    seen: set = set()
    result: List[str] = []
    for email in emails:
        if email not in seen:
            seen.add(email)
            result.append(email)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_emails_from_html(html: str, source_url: str) -> List[EmailResult]:
    """
    Parse *html* and return a list of :class:`EmailResult` objects.

    Parameters
    ----------
    html:
        Raw HTML string to parse.
    source_url:
        The URL from which *html* was retrieved; stored on each result for
        provenance.

    Returns
    -------
    list[EmailResult]
        One entry per unique email address found.  Returns an empty list when
        no addresses are present — this is not treated as an error.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:  # pragma: no cover – BS4 rarely raises
        logger.warning("Failed to parse HTML for %s: %s", source_url, exc)
        return []

    # Gather emails from both sources.
    visible_text: str = soup.get_text(separator=" ")
    text_emails: List[str] = _extract_from_text(visible_text)
    mailto_emails: List[str] = _extract_from_mailto(soup)

    # Merge and deduplicate.
    all_emails: List[str] = _deduplicate(text_emails + mailto_emails)

    results: List[EmailResult] = [
        EmailResult(
            email=email,
            source_url=source_url,
            status=ExtractionStatus.SUCCESS,
        )
        for email in all_emails
    ]

    if not results:
        logger.debug("No emails found on %s", source_url)

    return results


def fetch_and_extract(
    url: str,
    *,
    timeout: int = 10,
    headers: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    """
    Fetch *url* over HTTP and extract email addresses from the response HTML.

    Parameters
    ----------
    url:
        Target URL (must be a public HTTP/HTTPS page).
    timeout:
        Seconds before the HTTP request times out.
    headers:
        Optional extra HTTP request headers.

    Returns
    -------
    dict with keys:
        ``url``          – the original URL.
        ``results``      – list of :class:`EmailResult` (may be empty).
        ``error``        – error message string, or ``None`` on success.
        ``http_status``  – integer HTTP status code, or ``None`` on error.
    """
    default_headers: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; EmailExtractorBot/1.0; "
            "+https://github.com/example/email-extractor)"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    if headers:
        default_headers.update(headers)

    try:
        response = requests.get(
            url,
            headers=default_headers,
            timeout=timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        logger.warning("Request timed out for %s", url)
        return {"url": url, "results": [], "error": "Request timed out.", "http_status": None}
    except requests.exceptions.TooManyRedirects:
        logger.warning("Too many redirects for %s", url)
        return {"url": url, "results": [], "error": "Too many redirects.", "http_status": None}
    except requests.exceptions.HTTPError as exc:
        status_code: int = exc.response.status_code if exc.response is not None else 0
        logger.warning("HTTP %s error for %s", status_code, url)
        return {
            "url": url,
            "results": [],
            "error": f"HTTP error {status_code}.",
            "http_status": status_code,
        }
    except requests.exceptions.ConnectionError:
        logger.warning("Connection error for %s", url)
        return {"url": url, "results": [], "error": "Connection error.", "http_status": None}
    except requests.exceptions.RequestException as exc:
        logger.warning("Request failed for %s: %s", url, exc)
        return {"url": url, "results": [], "error": str(exc), "http_status": None}

    html: str = response.text
    email_results: List[EmailResult] = extract_emails_from_html(html, source_url=url)

    return {
        "url": url,
        "results": email_results,
        "error": None,
        "http_status": response.status_code,
    }


def process_urls(
    urls: List[str],
    *,
    timeout: int = 10,
    delay_seconds: float = 1.0,
) -> Dict[str, Any]:
    """
    Process a batch of URLs sequentially, respecting a polite crawl delay.

    Parameters
    ----------
    urls:
        List of public URLs to process.
    timeout:
        Per-request timeout in seconds.
    delay_seconds:
        Minimum seconds to wait between consecutive HTTP requests.

    Returns
    -------
    dict with keys:
        ``total_pages``     – number of URLs submitted.
        ``processed_pages`` – number of URLs attempted (all of them).
        ``total_emails``    – total unique email addresses found.
        ``results``         – flat list of :class:`EmailResult` objects.
        ``errors``          – list of :class:`PageError` objects for failed URLs.
    """
    all_results: List[EmailResult] = []
    errors: List[PageError] = []

    for index, url in enumerate(urls):
        logger.info("Processing URL %d/%d: %s", index + 1, len(urls), url)

        fetch_result = fetch_and_extract(url, timeout=timeout)

        if fetch_result["error"]:
            errors.append(PageError(url=url, error=fetch_result["error"]))
        else:
            page_emails: List[EmailResult] = fetch_result["results"]
            all_results.extend(page_emails)
            logger.info(
                "Found %d email(s) on %s", len(page_emails), url
            )

        # Polite delay between requests (skip after the last URL).
        if index < len(urls) - 1:
            time.sleep(delay_seconds)

    return {
        "total_pages": len(urls),
        "processed_pages": len(urls),
        "total_emails": len(all_results),
        "results": all_results,
        "errors": errors,
    }
