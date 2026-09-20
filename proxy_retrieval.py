"""Read exact CCR originals from the bundle's local request-compression engine."""

from http.client import HTTPException
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


PROXY_ORIGIN = "http://127.0.0.1:8789"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
HEALTH_RESPONSE_BYTES = 64 * 1024
HTTP_TIMEOUT_SECONDS = 3


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def _read_json(opener, path: str, limit: int, *, original: bool = False) -> dict:
    request = Request(PROXY_ORIGIN + path, headers={"Accept": "application/json"})
    try:
        with opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise RuntimeError("The local Headroom service returned an unexpected status.")
            media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if media_type != "application/json":
                raise RuntimeError("The local Headroom service returned an invalid response format.")
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > limit:
                raise RuntimeError("The Headroom original exceeds the retrieval response size limit.")
            body = response.read(limit + 1)
            if len(body) > limit:
                raise RuntimeError("The Headroom original exceeds the retrieval response size limit.")
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("The local Headroom service returned an invalid JSON object.")
        return payload
    except HTTPError as error:
        status = error.code
        error.close()
        if original and status == 404:
            raise LookupError(
                "Headroom original not found or expired. Re-read the source or rerun the "
                "original command only if needed and safe; do not retry this hash."
            ) from None
        raise RuntimeError("The local Headroom retrieval service is unavailable or refused the request.") from None
    except (URLError, OSError, HTTPException):
        raise RuntimeError("The local Headroom retrieval service is unavailable or timed out.") from None
    except (UnicodeError, ValueError):
        raise RuntimeError("The local Headroom service returned malformed original-content data.") from None


def read_proxy_original(content_hash: str) -> str:
    """Return full original text without normalizing it or recording local savings.

    The endpoint is fixed and never obtained from a hash, environment variable,
    or tool argument. Compression readiness is not required to retrieve an
    existing original, but the listener must identify as the Headroom service.
    Each HTTP operation has a three-second socket timeout and a bounded body.
    """
    if not isinstance(content_hash, str) or re.fullmatch(r"[0-9a-f]{12}", content_hash) is None:
        raise ValueError("Proxy content_hash must be a 12-character lowercase hexadecimal reference.")
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    health = _read_json(opener, "/health", HEALTH_RESPONSE_BYTES)
    if health.get("service") != "headroom-proxy" or health.get("status") != "healthy":
        raise RuntimeError("The local listener is not the expected healthy Headroom service.")
    payload = _read_json(
        opener, f"/v1/retrieve/{content_hash}", MAX_RESPONSE_BYTES, original=True
    )
    original = payload.get("original_content")
    if payload.get("hash") != content_hash or not isinstance(original, str):
        raise RuntimeError("Headroom returned an invalid or mismatched original-content reference.")
    return original
