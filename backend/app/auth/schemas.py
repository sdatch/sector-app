"""User read/create/update schemas. Registration carries an explicit `consent`
flag (PRD FR-7): the account is created only on affirmative consent, and the
timestamp is recorded server-side in users.consented_at."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi_users import schemas
from pydantic import Field


class UserRead(schemas.BaseUser[uuid.UUID]):
    consented_at: datetime
    created_at: datetime


class UserCreate(schemas.BaseUserCreate):
    consent: bool = Field(
        description="Must be true — affirmative consent to the educational-use "
        "disclaimer (PRD §13). The account is not created otherwise."
    )


class UserUpdate(schemas.BaseUserUpdate):
    pass
