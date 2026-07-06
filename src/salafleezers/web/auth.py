"""Minimal auth stub for optional shared-server deployment.

Local-first default: with ``SFZ_AUTH_TOKEN`` unset, every request resolves to
a single anonymous local principal — today's single-user behavior, unchanged.
Setting ``SFZ_AUTH_TOKEN`` enables a shared-secret bearer-token gate: anyone
presenting the token is treated as one shared principal. This is intentionally
simple — a seam for a small shared-lab deployment behind a reverse proxy, not
a full multi-user identity provider. Swap ``get_current_principal`` for a
real auth backend later without touching session/storage business logic.
"""

from __future__ import annotations

import hmac
import logging
import os
from dataclasses import dataclass

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

ANONYMOUS_USER_ID = "local"
SHARED_USER_ID = "shared"


@dataclass(frozen=True)
class Principal:
    """The resolved caller of a request. Used to namespace stored sessions."""
    user_id: str


def _configured_token() -> str | None:
    # `or None` treats an empty string the same as "unset" -- e.g. Compose's
    # `${SFZ_AUTH_TOKEN:-}` sets the var to "" rather than leaving it absent.
    return os.environ.get("SFZ_AUTH_TOKEN") or None


async def get_current_principal(
    authorization: str | None = Header(default=None),
) -> Principal:
    """FastAPI dependency resolving the calling principal.

    - ``SFZ_AUTH_TOKEN`` unset (default): anonymous local principal, no check.
    - ``SFZ_AUTH_TOKEN`` set: requires ``Authorization: Bearer <token>``
      matching it; raises 401 otherwise.
    """
    token = _configured_token()
    if token is None:
        return Principal(user_id=ANONYMOUS_USER_ID)

    if authorization is None or not authorization.startswith("Bearer "):
        logger.warning("Rejected request with missing/malformed bearer token")
        raise HTTPException(status_code=401, detail="Missing bearer token")

    presented = authorization.removeprefix("Bearer ")
    if not hmac.compare_digest(presented, token):
        logger.warning("Rejected request with invalid bearer token")
        raise HTTPException(status_code=401, detail="Invalid token")

    return Principal(user_id=SHARED_USER_ID)
