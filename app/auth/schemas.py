import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.auth.models import RoleUpgradeStatus, UserRole


class RegisterIn(BaseModel):
    # extra="forbid": a `role` key in the request body is rejected outright
    # (422), not silently dropped — self-registration always lands on
    # VIEWER (app/auth/service.py's register_user); only an ADMIN can
    # elevate a user afterwards, or a VIEWER can apply for RESEARCHER via
    # POST /api/v1/auth/apply-researcher.
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class ApplyResearcherIn(BaseModel):
    reason: str = Field(min_length=20, max_length=2000)
    institution_or_department: str | None = Field(default=None, max_length=255)


class RoleUpgradeRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    target_role: UserRole
    reason: str
    institution_or_department: str | None
    status: RoleUpgradeStatus
    review_notes: str | None
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    created_at: datetime


class RoleUpgradeRequestAdminOut(RoleUpgradeRequestOut):
    """Same shape the applicant sees, plus who they are — admin-only
    (GET /api/v1/admin/upgrade-requests never returns this to the
    applicant themselves)."""

    applicant_email: str
    applicant_full_name: str


class ReviewUpgradeRequestIn(BaseModel):
    action: Literal["APPROVE", "REJECT"]
    review_notes: str | None = Field(default=None, max_length=2000)


class AssignRoleIn(BaseModel):
    """Direct admin override — distinct from the moderated VIEWER->RESEARCHER
    application flow above: an ADMIN can set ANY user to ANY role here,
    no application or justification required (design: "admin can change
    others' role... and assign roles to other[s] anyway")."""

    role: UserRole
