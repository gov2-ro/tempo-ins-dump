"""Shared rules for reading TEMPO-Online HTTP responses.

Used by the fetch scripts (3, 6, update-pipeline, fetch-ins-reference-cells).
Two TEMPO habits that a plain decode or a status check misses:

- The server declares UTF-8 but sometimes sends single Windows-1250 bytes
  (seen: 0xE2 "â" in JUS109B, 0xA0 no-break space). A strict or "replace"
  decode turns them into U+FFFD. `decode_body` decodes those bytes as cp1250.
- A failed query answers HTTP 200 with one sentence as the whole body (the
  "error envelope"). `is_error_envelope` detects it, so that a caller treats
  it as a retryable failure, not as an empty dataset.
"""
from __future__ import annotations

import codecs

_ERROR_HANDLER = "tempo-cp1250"


def _cp1250_fallback(err: UnicodeDecodeError) -> tuple[str, int]:
    bad = err.object[err.start:err.end]
    return bad.decode("cp1250", errors="replace"), err.end


codecs.register_error(_ERROR_HANDLER, _cp1250_fallback)


def decode_body(content: bytes) -> str:
    """Decode a TEMPO body as UTF-8; decode stray invalid bytes as Windows-1250."""
    return content.decode("utf-8", errors=_ERROR_HANDLER)


ERROR_ENVELOPE_MARKERS = (
    "results to your query could not be returned",
    "rezultatul solicitat nu poate fi returnat",
)
_ENVELOPE_MAX_CHARS = 2000  # a real answer with data rows is longer or has no marker


def is_error_envelope(text: str) -> bool:
    """True when the body is TEMPO's short "could not return results" message."""
    if not text or len(text) > _ENVELOPE_MAX_CHARS:
        return False
    low = text.lower()
    return any(m in low for m in ERROR_ENVELOPE_MARKERS)
