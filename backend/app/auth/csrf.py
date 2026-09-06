"""
CSRF defense for cookie-authenticated mutating routes (user_model_spec §1.2):
SameSite=Lax on the session cookie plus a required custom header. A browser
will not attach a custom header on a cross-site form/navigation, and this JSON
API has no form posts, so requiring X-Requested-With blocks cross-site forgery
without a token round-trip. Applied to our POST/DELETE routes (not to the
fastapi-users auth routes, which use their own flows).
"""

from __future__ import annotations

from fastapi import Header, HTTPException


async def require_csrf_header(
    x_requested_with: str | None = Header(default=None, alias="X-Requested-With"),
) -> None:
    if not x_requested_with:
        raise HTTPException(status_code=403, detail="missing_csrf_header")
