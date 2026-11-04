"""Platform sign-in: accept the SportLens core JWT and scope matches to the caller's facilities.

The core API (futsal backend) owns users and facilities. Instead of sharing its database, padel asks
it which facilities a token belongs to (GET /api/v1/facilities, the caller's memberships only) and
caches the answer briefly. Matches and cameras carry a facility_id; requests only see their own.
"""
from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import json
import secrets
import threading
import time

import requests

from .settings import AUTH_CACHE_S, AUTH_URL, MEDIA_SECRET, MEDIA_TOKEN_TTL_S

_MEDIA_KEY = (MEDIA_SECRET or secrets.token_hex(32)).encode()
MEDIA_PREFIX = "m1."

# None = no platform scoping for this request (no auth configured, or the service token was used)
ALLOWED: contextvars.ContextVar[frozenset[str] | None] = contextvars.ContextVar("padel_allowed", default=None)

_cache: dict[str, tuple[float, frozenset[str] | None]] = {}
_lock = threading.Lock()
_MAX_CACHE = 2048


def facilities(token: str) -> frozenset[str] | None:
    """Facility ids the token's user belongs to; None when the core API rejects the token."""
    key = hashlib.sha256(token.encode()).hexdigest()
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    try:
        r = requests.get(f"{AUTH_URL}/api/v1/facilities", headers={"Authorization": f"Bearer {token}"}, timeout=5)
    except requests.RequestException:
        return None  # core API unreachable: fail closed, do not cache
    result = frozenset(str(f["id"]) for f in r.json()) if r.status_code == 200 else None
    with _lock:
        if len(_cache) >= _MAX_CACHE:
            _cache.clear()
        # rejections are cached briefly too, so a bad token cannot hammer the core API
        _cache[key] = (now + (AUTH_CACHE_S if result is not None else 5), result)
    return result


def allowed() -> frozenset[str] | None:
    return ALLOWED.get()


def can_see(facility_id: str | None) -> bool:
    scope = ALLOWED.get()
    return scope is None or (facility_id is not None and facility_id in scope)


def pick_facility(requested: str) -> str | None:
    """Facility a new match / camera is filed under; raises PermissionError when not allowed."""
    scope = ALLOWED.get()
    if scope is None:
        return requested or None
    if requested:
        if requested not in scope:
            raise PermissionError(requested)
        return requested
    if len(scope) == 1:
        return next(iter(scope))
    raise PermissionError("facility_id is required")


def media_token(scope: frozenset[str] | None) -> dict:
    """Read-only token for media URLs, carrying the caller's facility scope (None = unrestricted)."""
    exp = int(time.time()) + MEDIA_TOKEN_TTL_S
    body = base64.urlsafe_b64encode(json.dumps({"f": sorted(scope) if scope is not None else None, "e": exp},
                                               separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(_MEDIA_KEY, body.encode(), hashlib.sha256).hexdigest()
    return {"token": f"{MEDIA_PREFIX}{body}.{sig}", "expires_at": exp}


def verify_media(token: str) -> tuple[bool, frozenset[str] | None]:
    """(valid, scope) for a media token."""
    try:
        body, sig = token[len(MEDIA_PREFIX):].rsplit(".", 1)
        if not hmac.compare_digest(sig, hmac.new(_MEDIA_KEY, body.encode(), hashlib.sha256).hexdigest()):
            return False, None
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (ValueError, json.JSONDecodeError):
        return False, None
    if data["e"] < time.time():
        return False, None
    return True, frozenset(data["f"]) if data["f"] is not None else None
