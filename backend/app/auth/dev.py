"""
Dev-only auth helpers. These endpoints are 404 in production — they exist so
local testing doesn't require pulling a 256-char verification token out of the
container logs. In production, tokens are delivered by the (to-be-wired) mail
provider only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.db.models import User

from .users import (
    DEV_VERIFY_TOKENS,
    UserManager,
    current_active_user,
    get_user_manager,
)

router = APIRouter(prefix="/auth/dev", tags=["auth-dev"])


@router.get("/verification-token")
async def dev_verification_token(
    user: User = Depends(current_active_user),
    manager: UserManager = Depends(get_user_manager),
) -> dict:
    if get_settings().is_production:
        raise HTTPException(status_code=404, detail="not_found")
    if user.is_verified:
        return {"verified": True, "token": None}
    token = DEV_VERIFY_TOKENS.get(user.email)
    if token is None:
        # Cache empty (e.g., after a restart) — mint a fresh one; the hook
        # stores it as a side effect.
        await manager.request_verify(user)
        token = DEV_VERIFY_TOKENS.get(user.email)
    return {"verified": False, "token": token}
