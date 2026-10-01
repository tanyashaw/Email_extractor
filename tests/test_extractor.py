"""
Test suite for the Email Extractor backend.

Coverage
--------
- extract_emails_from_html: visible text, mailto links, duplicates, empty pages,
  malformed HTML.
- fetch_and_extract: network errors (timeout, connection, HTTP 4xx/5xx).
- FastAPI endpoints: health, extract (valid input, too many URLs, invalid URLs),
  export (valid results, empty list).

All external HTTP requests are mocked with ``unittest.mock`` so that no real
network calls are made during tests.
"""

import io
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.email_extractor import (
    extract_emails_from_html,
    fetch_and_extract,
)
from app.models.schemas import ExtractionStatus

# ---------------------------------------------------------------------------
# Test client fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    """Return a synchronous TestClient wrapping the FastAPI app."""
    with TestClient(app) as c:
        yield c


# ===========================================================================
# Unit tests — extract_emails_from_html
# ===========================================================================

class TestExtractEmailsFromHtml:
    """Tests for the core HTML-parsing / email-extraction logic."""

    def test_extracts_email_from_visible_text(self):
        html = "<html><body><p>Contact us at hello@example.com for more info.</p></body></html>"
        results = extract_emails_from_html(html, source_url="https://example.com/1")

        assert len(results) == 1
        assert results[0].email == "hello@example.com"
        assert results[0].source_url == "https://example.com/1"
        assert results[0].status == ExtractionStatus.SUCCESS

    def test_extracts_email_from_mailto_link(self):
        html = '<html><body><a href="mailto:info@company.be">Email us</a></body></html>'
        results = extract_emails_from_html(html, source_url="https://company.be")

        assert len(results) == 1
        assert results[0].email == "info@company.be"

    def test_extracts_emails_from_both_text_and_mailto(self):
        html = (
            "<html><body>"
            "<p>Write to sales@company.be for quotes.</p>"
            '<a href="mailto:support@company.be">Support</a>'
            "</body></html>"
        )
        results = extract_emails_from_html(html, source_url="https://company.be")
        emails = {r.email for r in results}

        assert "sales@company.be" in emails
        assert "support@company.be" in emails

    def test_removes_duplicate_emails(self):
        html = (
            "<html><body>"
            "<p>info@acme.com</p>"
            "<p>INFO@ACME.COM</p>"
            '<a href="mailto:info@acme.com">Email</a>'
            "</body></html>"
        )
        results = extract_emails_from_html(html, source_url="https://acme.com")

        emails = [r.email for r in results]
        assert emails.count("info@acme.com") == 1

    def test_normalises_emails_to_lowercase(self):
        html = "<html><body><p>Contact: HELLO@EXAMPLE.COM</p></body></html>"
        results = extract_emails_from_html(html, source_url="https://example.com")

        assert results[0].email == "hello@example.com"

    def test_handles_page_with_no_emails(self):
        html = "<html><body><p>No contact details available here.</p></body></html>"
        results = extract_emails_from_html(html, source_url="https://example.com/empty")

        assert results == []

    def test_handles_empty_html_string(self):
        results = extract_emails_from_html("", source_url="https://example.com")
        assert results == []

    def test_handles_malformed_html(self):
        # BeautifulSoup is resilient; this should not raise.
        malformed = "<html><body><p>Email: broken@<b>example.com</p></body>"
        results = extract_emails_from_html(malformed, source_url="https://example.com")
        # The email spans across tags — we don't assert a specific count, only
        # that no exception is raised.
        assert isinstance(results, list)

    def test_multiple_emails_in_single_mailto(self):
        html = '<a href="mailto:a@x.com,b@x.com">Contact</a>'
        results = extract_emails_from_html(html, source_url="https://x.com")
        emails = {r.email for r in results}
        assert "a@x.com" in emails
        assert "b@x.com" in emails

    def test_mailto_with_query_params_stripped(self):
        html = '<a href="mailto:hello@example.com?subject=Hello&body=Hi">Email</a>'
        results = extract_emails_from_html(html, source_url="https://example.com")
        assert len(results) == 1
        assert results[0].email == "hello@example.com"

    def test_preserves_source_url(self):
        html = "<p>reach@us.com</p>"
        url = "https://us.com/profile/42"
        results = extract_emails_from_html(html, source_url=url)
        assert results[0].source_url == url


# ===========================================================================
# Unit tests — fetch_and_extract
# ===========================================================================

class TestFetchAndExtract:
    """Tests for the HTTP fetch + extraction pipeline."""

    def _mock_response(self, html: str, status_code: int = 200) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    @patch("app.services.email_extractor.requests.get")
    def test_successful_fetch_and_extract(self, mock_get):
        html = "<p>Contact: admin@site.com</p>"
        mock_get.return_value = self._mock_response(html)

        result = fetch_and_extract("https://site.com")

        assert result["error"] is None
        assert result["http_status"] == 200
        assert len(result["results"]) == 1
        assert result["results"][0].email == "admin@site.com"

    @patch("app.services.email_extractor.requests.get")
    def test_handles_request_timeout(self, mock_get):
        import requests as req_lib
        mock_get.side_effect = req_lib.exceptions.Timeout

        result = fetch_and_extract("https://slow-site.com")

        assert result["error"] == "Request timed out."
        assert result["results"] == []
        assert result["http_status"] is None

    @patch("app.services.email_extractor.requests.get")
    def test_handles_connection_error(self, mock_get):
        import requests as req_lib
        mock_get.side_effect = req_lib.exceptions.ConnectionError

        result = fetch_and_extract("https://unreachable.com")

        assert result["error"] == "Connection error."
        assert result["results"] == []

    @patch("app.services.email_extractor.requests.get")
    def test_handles_http_404(self, mock_get):
        import requests as req_lib
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        http_error = req_lib.exceptions.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp
        mock_resp.raise_for_status.side_effect = http_error

        result = fetch_and_extract("https://example.com/missing")

        assert "404" in result["error"]
        assert result["results"] == []

    @patch("app.services.email_extractor.requests.get")
    def test_handles_http_500(self, mock_get):
        import requests as req_lib
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        http_error = req_lib.exceptions.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp
        mock_resp.raise_for_status.side_effect = http_error

        result = fetch_and_extract("https://broken-server.com")

        assert "500" in result["error"]

    @patch("app.services.email_extractor.requests.get")
    def test_page_with_no_emails_returns_empty_results(self, mock_get):
        html = "<p>We have no email listed here.</p>"
        mock_get.return_value = self._mock_response(html)

        result = fetch_and_extract("https://no-email.com")

        assert result["error"] is None
        assert result["results"] == []


# ===========================================================================
# Integration tests — FastAPI endpoints
# ===========================================================================

class TestHealthEndpoint:
    """Tests for GET /api/scraper/health."""

    def test_health_returns_200(self, client):
        response = client.get("/api/scraper/health")
        assert response.status_code == 200

    def test_health_returns_ok_status(self, client):
        data = client.get("/api/scraper/health").json()
        assert data["status"] == "ok"

    def test_health_includes_version(self, client):
        data = client.get("/api/scraper/health").json()
        assert "version" in data

    def test_health_includes_message(self, client):
        data = client.get("/api/scraper/health").json()
        assert "message" in data


class TestExtractEndpoint:
    """Tests for POST /api/scraper/extract."""

    @patch("app.services.email_extractor.requests.get")
    def test_extract_returns_200_for_valid_urls(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<p>hello@test.com</p>"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        response = client.post(
            "/api/scraper/extract",
            json={"urls": ["https://test.com/company/1"]},
        )
        assert response.status_code == 200

    @patch("app.services.email_extractor.requests.get")
    def test_extract_returns_emails_in_results(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<p>contact@acme.com</p>"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        data = client.post(
            "/api/scraper/extract",
            json={"urls": ["https://acme.com"]},
        ).json()

        assert data["total_emails"] == 1
        assert data["results"][0]["email"] == "contact@acme.com"

    @patch("app.services.email_extractor.requests.get")
    def test_extract_handles_page_with_no_emails(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<p>No emails here.</p>"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        data = client.post(
            "/api/scraper/extract",
            json={"urls": ["https://empty.com"]},
        ).json()

        assert data["total_emails"] == 0
        assert data["results"] == []

    def test_extract_rejects_empty_url_list(self, client):
        response = client.post("/api/scraper/extract", json={"urls": []})
        assert response.status_code == 422

    def test_extract_rejects_invalid_url(self, client):
        response = client.post(
            "/api/scraper/extract",
            json={"urls": ["not-a-url"]},
        )
        assert response.status_code == 422

    def test_extract_rejects_too_many_urls(self, client):
        urls = [f"https://example.com/company/{i}" for i in range(10)]
        response = client.post("/api/scraper/extract", json={"urls": urls})
        assert response.status_code == 422

    @patch("app.services.email_extractor.requests.get")
    def test_extract_processes_multiple_urls(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<p>user@site.com</p>"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        data = client.post(
            "/api/scraper/extract",
            json={
                "urls": [
                    "https://site.com/1",
                    "https://site.com/2",
                ]
            },
        ).json()

        assert data["total_pages"] == 2
        assert data["processed_pages"] == 2

    @patch("app.services.email_extractor.requests.get")
    def test_extract_includes_errors_for_failed_urls(self, mock_get, client):
        import requests as req_lib
        mock_get.side_effect = req_lib.exceptions.ConnectionError

        data = client.post(
            "/api/scraper/extract",
            json={"urls": ["https://unreachable.com"]},
        ).json()

        assert data["total_emails"] == 0
        assert data["errors"] is not None
        assert len(data["errors"]) == 1


class TestExportEndpoint:
    """Tests for POST /api/scraper/export."""

    def test_export_returns_csv_content_type(self, client):
        payload = {
            "results": [
                {
                    "email": "test@example.com",
                    "source_url": "https://example.com",
                    "status": "success",
                }
            ]
        }
        response = client.post("/api/scraper/export", json=payload)
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]

    def test_export_csv_contains_header_row(self, client):
        payload = {
            "results": [
                {
                    "email": "a@b.com",
                    "source_url": "https://b.com",
                    "status": "success",
                }
            ]
        }
        response = client.post("/api/scraper/export", json=payload)
        content = response.content.decode("utf-8")
        assert "email" in content
        assert "source_url" in content
        assert "status" in content

    def test_export_csv_contains_email_data(self, client):
        payload = {
            "results": [
                {
                    "email": "export@test.com",
                    "source_url": "https://test.com",
                    "status": "success",
                }
            ]
        }
        response = client.post("/api/scraper/export", json=payload)
        content = response.content.decode("utf-8")
        assert "export@test.com" in content

    def test_export_rejects_empty_results(self, client):
        payload = {"results": []}
        response = client.post("/api/scraper/export", json=payload)
        assert response.status_code == 422

    def test_export_attachment_header_present(self, client):
        payload = {
            "results": [
                {
                    "email": "x@y.com",
                    "source_url": "https://y.com",
                    "status": "success",
                }
            ]
        }
        response = client.post("/api/scraper/export", json=payload)
        disposition = response.headers.get("content-disposition", "")
        assert "attachment" in disposition
        assert ".csv" in disposition


class TestRootEndpoint:
    """Tests for GET /."""

    def test_root_returns_200(self, client):
        response = client.get("/")
        assert response.status_code == 200

    def test_root_includes_api_name(self, client):
        data = client.get("/").json()
        assert "Email Extractor" in data.get("name", "")
