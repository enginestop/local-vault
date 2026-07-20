import unicodedata
from urllib.parse import urlparse, urlunparse

import idna

from .models import nfkc_casefold


def norm_username(username: str | None) -> str:
    """IMP-012: trim, NFKC, casefold. Empty/None -> ''."""
    if not username:
        return ""
    return nfkc_casefold(username.strip())


def norm_url(url: str | None) -> str:
    """IMP-012 normalization for duplicate detection.

    - trim
    - add https:// if no scheme (for comparison only)
    - lowercase scheme/host
    - IDNA host
    - remove fragment and default port
    - keep query
    - root empty path -> '/'
    On parse failure, return NFKC+casefold of trimmed string.
    """
    if not url:
        return ""
    s = url.strip()
    if not s:
        return ""
    try:
        # ensure a scheme for parsing
        work = s
        if "://" not in work:
            work = "https://" + work
        parsed = urlparse(work)
        scheme = parsed.scheme.lower()
        host = parsed.netloc.lower()
        if not host:
            raise ValueError("no host")
        try:
            host = idna.encode(host).decode("ascii").lower()
        except Exception:
            host = host.lower()
        # strip default port
        if ":" in host:
            h, p = host.split(":", 1)
            if (scheme == "https" and p == "443") or (scheme == "http" and p == "80"):
                host = h
        path = parsed.path or "/"
        query = parsed.query
        rebuilt = urlunparse((scheme, host, path, "", query, ""))
        return rebuilt
    except Exception:
        return nfkc_casefold(s)
