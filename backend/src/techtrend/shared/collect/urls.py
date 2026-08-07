"""URL canonicalisation -- the first line of duplicate defence.

Syndication and tracking params make one article look like many URLs.
Canonicalise before hashing; Group (stage 3) is the backstop for what
this misses.
"""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Parameters that never change which article a URL points at.
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_EXACT = {
    "fbclid",
    "gclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "ref",
    "ref_src",
    "referrer",
    "source",
    "cmpid",
    "ncid",
    "sh",
    "smid",
    "ocid",
    "partner",
    "guccounter",
    "guce_referrer",
    "guce_referrer_sig",
}

_DEFAULT_PORTS = {"http": "80", "https": "443"}


def canonical(url: str) -> str:
    """Lower-case scheme/host, drop default ports, fragments and tracking params.

    Deliberately conservative: path and meaningful query params pass through
    untouched. A canonicaliser that is too clever merges distinct articles,
    which is the unrecoverable direction.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = parts.hostname.lower() if parts.hostname else ""
    if parts.port is not None and str(parts.port) != _DEFAULT_PORTS.get(scheme):
        host = f"{host}:{parts.port}"

    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.lower() in _TRACKING_EXACT or k.lower().startswith(_TRACKING_PREFIXES))
    ]
    path = parts.path or "/"
    return urlunsplit((scheme, host, path, urlencode(kept), ""))


def url_hash(url: str) -> bytes:
    """The `articles.url_hash` unique key -- sha256 of the canonical form."""
    return hashlib.sha256(canonical(url).encode()).digest()
