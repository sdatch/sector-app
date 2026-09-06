"""
fastapi-users wiring (user_model_spec §1.3): argon2 hashing, cookie/JWT
transport, registration with required consent, email verification hard gate.

Cookie transport (not bearer) is forced by the SSE design: EventSource cannot
attach custom headers, but cookies flow automatically. CSRF exposure is covered
by SameSite=Lax plus an X-Requested-With check on mutating routes (see
app/auth/csrf.py).

Note (simplification vs spec §1.2): v1 uses a single httpOnly session cookie
(JWT) rather than a short access + rotating refresh pair. The rotation is a
security hardening deferred without changing the cookie transport or any route.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin, exceptions
from fastapi_users.authentication import (
    AuthenticationBackend,
    CookieTransport,
    JWTStrategy,
)
from fastapi_users.password import PasswordHelper
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_async_session
from app.db.models import User

_settings = get_settings()
_password_helper = PasswordHelper(PasswordHash((Argon2Hasher(),)))

# Dev-only: the latest verification / reset token per email, so local testing
# doesn't require digging a 256-char token out of the logs. Never populated in
# production (see the guards in the hooks below), and the endpoint that reads it
# is 404 in production.
DEV_VERIFY_TOKENS: dict[str, str] = {}
DEV_RESET_TOKENS: dict[str, str] = {}


async def get_user_db(
    session: AsyncSession = Depends(get_async_session),
) -> AsyncGenerator[SQLAlchemyUserDatabase, None]:
    yield SQLAlchemyUserDatabase(session, User)


class ConsentRequired(exceptions.FastAPIUsersException):
    """Registration attempted without affirmative consent."""


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = _settings.jwt_secret
    verification_token_secret = _settings.jwt_secret

    async def create(self, user_create, safe: bool = False, request=None) -> User:
        # Hard requirement: no account without consent (PRD FR-7).
        if not getattr(user_create, "consent", False):
            raise ConsentRequired()

        await self.validate_password(user_create.password, user_create)
        existing = await self.user_db.get_by_email(user_create.email)
        if existing is not None:
            raise exceptions.UserAlreadyExists()

        user_dict = (
            user_create.create_update_dict()
            if safe
            else user_create.create_update_dict_superuser()
        )
        password = user_dict.pop("password")
        user_dict["hashed_password"] = self.password_helper.hash(password)
        user_dict.pop("consent", None)
        user_dict["consented_at"] = datetime.now(timezone.utc)

        created = await self.user_db.create(user_dict)
        await self.on_after_register(created, request)
        return created

    async def on_after_register(self, user: User, request: Request | None = None):
        # Verification is hard-gated before the first comparison, so kick off
        # the verification flow immediately on registration.
        try:
            await self.request_verify(user, request)
        except exceptions.UserInactive:
            pass

    async def on_after_request_verify(
        self, user: User, token: str, request: Request | None = None
    ):
        # No mail server yet — emit the token to logs, and (dev only) stash it
        # so the /verify page can auto-complete without manual copying.
        print(f"[verify] user={user.email} token={token}")
        if not _settings.is_production:
            DEV_VERIFY_TOKENS[user.email] = token

    async def on_after_forgot_password(
        self, user: User, token: str, request: Request | None = None
    ):
        print(f"[reset] user={user.email} token={token}")
        if not _settings.is_production:
            DEV_RESET_TOKENS[user.email] = token


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    yield UserManager(user_db, _password_helper)


cookie_transport = CookieTransport(
    cookie_name="sectorinsight",
    cookie_max_age=_settings.refresh_token_ttl_s,
    cookie_secure=_settings.cookie_secure,
    cookie_httponly=True,
    cookie_samesite=_settings.cookie_samesite,
)


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(
        secret=_settings.jwt_secret,
        lifetime_seconds=_settings.refresh_token_ttl_s,
    )


auth_backend = AuthenticationBackend(
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

# Dependencies used by routers:
current_active_user = fastapi_users.current_user(active=True)
# Comparisons are hard-gated on verification (403 if unverified).
current_verified_user = fastapi_users.current_user(active=True, verified=True)
