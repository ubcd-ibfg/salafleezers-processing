"""Authentication and principal resolution.

Three modes, in increasing order of capability:

1. **Local (default).** ``SFZ_AUTH_TOKEN`` unset: every request resolves to a
   single anonymous local principal. Today's single-user behavior, unchanged.

2. **Shared secret.** ``SFZ_AUTH_TOKEN`` set: a bearer-token gate. Everyone
   presenting the token is the *same* principal, so this authenticates but
   does not identify -- adequate for "keep strangers out of my lab's box",
   not for isolating colleagues from each other.

3. **Proxy-supplied identity.** ``SFZ_TRUSTED_USER_HEADER`` set (e.g.
   ``X-Auth-Request-Email``): ``user_id`` is read from that header, which an
   authenticating reverse proxy -- oauth2-proxy, Authelia, Cloudflare Access
   -- is expected to set and to strip from client requests. This is what makes
   the per-user isolation in ``sessions.get_owned`` and ``UserScopedStore``
   actually isolate real, distinct people, without any identity-provider code
   living in this app.

   The header is honored **only** when that env var is explicitly set. A
   client-settable header trusted by default would be a one-line auth bypass,
   so the deployer has to opt in, and is responsible for ensuring the proxy
   overwrites rather than forwards it.

WebSocket note: browsers cannot set request headers on a WS handshake, so
socket auth goes through short-lived single-use tickets (:func:`issue_ticket` /
:func:`consume_ticket`) minted by an authenticated REST call. A long-lived
token passed as a query parameter would end up in access logs and proxy
history; a one-shot ticket that expires in seconds does not.
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

ANONYMOUS_USER_ID = "local"
SHARED_USER_ID = "shared"

# Long enough to cover a page load issuing a ticket then opening the socket;
# short enough that a leaked ticket in a log is worthless by the time it's read.
_TICKET_TTL_SECONDS = 30.0


@dataclass(frozen=True)
class Principal:
    """The resolved caller of a request. Used to namespace sessions and uploads."""
    user_id: str


def _configured_token() -> str | None:
    # `or None` treats an empty string the same as "unset" -- e.g. Compose's
    # `${SFZ_AUTH_TOKEN:-}` sets the var to "" rather than leaving it absent.
    return os.environ.get("SFZ_AUTH_TOKEN") or None


def _trusted_user_header() -> str | None:
    return os.environ.get("SFZ_TRUSTED_USER_HEADER") or None


def _sanitize_user_id(raw: str) -> str:
    """Reduce a proxy-supplied identity to a safe single path segment.

    ``user_id`` becomes a directory name under the sessions and uploads roots
    (see storage.py / workspace.py). Those modules re-validate, but sanitizing
    at the boundary means a hostile or merely awkward identity (an email with
    a slash, a Windows-style name) can never reach them.
    """
    cleaned = "".join(c if c.isalnum() or c in "-_.@" else "_" for c in raw.strip())
    cleaned = cleaned.lstrip(".")
    return cleaned[:128] or "unknown"


async def get_current_principal(request: Request) -> Principal:
    """FastAPI dependency resolving the calling principal.

    Takes the raw ``Request`` rather than named ``Header(...)`` parameters
    because ``SFZ_TRUSTED_USER_HEADER`` is deployer-configurable to an
    arbitrary header name -- declaring a fixed set of named headers could
    never generalize to whatever the deployer's proxy actually sends.
    """
    return resolve_principal_from_headers(request.headers)


def resolve_principal_from_headers(headers) -> Principal:
    """Resolve a principal from a case-insensitive header mapping.

    Shared by the HTTP dependency and the WebSocket handshake, which has no
    dependency-injection path of its own.
    """
    def get(name: str) -> str | None:
        try:
            return headers.get(name) or headers.get(name.lower())
        except AttributeError:
            return None

    token = _configured_token()
    if token is not None:
        authorization = get("authorization")
        if authorization is None or not authorization.startswith("Bearer "):
            logger.warning("Rejected request with missing/malformed bearer token")
            raise HTTPException(status_code=401, detail="Missing bearer token")

        presented = authorization.removeprefix("Bearer ")
        if not hmac.compare_digest(presented, token):
            logger.warning("Rejected request with invalid bearer token")
            raise HTTPException(status_code=401, detail="Invalid token")

    header_name = _trusted_user_header()
    if header_name is not None:
        raw_identity = get(header_name)
        if not raw_identity:
            # The deployer asked for proxy identity, so a request without it
            # either bypassed the proxy or the proxy is misconfigured. Failing
            # closed is the only safe reading -- falling back to a shared
            # principal would silently merge everyone's workspaces.
            logger.warning(
                "SFZ_TRUSTED_USER_HEADER=%s is configured but absent from the request",
                header_name,
            )
            raise HTTPException(status_code=401, detail="Missing identity header")
        return Principal(user_id=_sanitize_user_id(raw_identity))

    if token is not None:
        return Principal(user_id=SHARED_USER_ID)
    return Principal(user_id=ANONYMOUS_USER_ID)


# ---------------------------------------------------------------------------
# WebSocket tickets
# ---------------------------------------------------------------------------

# In-process only, like the rate limiter and session manager. A multi-worker
# deployment would need these in the shared session store -- noted alongside
# the other Tier 2 items rather than pretended away.
_tickets: dict[str, tuple[str, float]] = {}


def issue_ticket(user_id: str) -> tuple[str, float]:
    """Mint a single-use WebSocket ticket for *user_id*.

    Returns ``(ticket, ttl_seconds)``.
    """
    _purge_expired_tickets()
    ticket = secrets.token_urlsafe(32)
    _tickets[ticket] = (user_id, time.monotonic() + _TICKET_TTL_SECONDS)
    return ticket, _TICKET_TTL_SECONDS


def consume_ticket(ticket: str) -> str | None:
    """Redeem a ticket, returning its ``user_id`` or ``None`` if invalid.

    Single-use: the ticket is removed whether or not it had expired, so a
    replay always fails even within the TTL window.
    """
    _purge_expired_tickets()
    entry = _tickets.pop(ticket, None)
    if entry is None:
        return None
    user_id, expires_at = entry
    if time.monotonic() > expires_at:
        return None
    return user_id


def _purge_expired_tickets() -> None:
    now = time.monotonic()
    for ticket in [t for t, (_, exp) in _tickets.items() if now > exp]:
        _tickets.pop(ticket, None)


def auth_required() -> bool:
    """Whether any authentication is configured (used by the SPA to prompt)."""
    return _configured_token() is not None or _trusted_user_header() is not None
