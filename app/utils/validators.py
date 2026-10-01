"""
URL validation utilities.

Provides helpers for checking whether a URL is well-formed and uses an
accepted scheme, so that the scraper layer never attempts to reach
unintended targets.
"""

import re
from urllib.parse import urlparse
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_SCHEMES: frozenset = frozenset({"http", "https"})

# Very basic email pattern used by the service layer; defined here so it can
# be imported and reused by the extractor service without circular imports.
EMAIL_REGEX: re.Pattern = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def is_valid_url(url: str) -> bool:
    """
    Return True if *url* is a well-formed HTTP/HTTPS URL.

    Checks:
    - The scheme is http or https.
    - A non-empty network location (hostname) is present.
    - The URL can be parsed without raising an exception.
    """
    try:
        parsed = urlparse(url)
        return parsed.scheme in ALLOWED_SCHEMES and bool(parsed.netloc)
    except Exception:
        return False


def validate_urls(urls: List[str]) -> Tuple[List[str], List[str]]:
    """
    Partition *urls* into valid and invalid lists.

    Returns
    -------
    valid_urls : list[str]
        URLs that pass ``is_valid_url``.
    invalid_urls : list[str]
        URLs that fail validation.
    """
    valid: List[str] = []
    invalid: List[str] = []

    for url in urls:
        if is_valid_url(str(url)):
            valid.append(str(url))
        else:
            invalid.append(str(url))

    return valid, invalid


# ---------------------------------------------------------------------------
# Email helpers (thin wrappers kept here to avoid duplication)
# ---------------------------------------------------------------------------

def is_valid_email(email: str) -> bool:
    """Return True if *email* looks like a syntactically valid address."""
    return bool(EMAIL_REGEX.fullmatch(email.strip()))
