import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    PLANNER = "PLANNER"
    RESEARCHER = "RESEARCHER"
    # Renamed from POLICY_VIEWER (migration 0015) — same slot in the enum,
    # now also the default role every self-registered account starts on
    # (see app/auth/service.py's register_user), not just an invited role.
    VIEWER = "VIEWER"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), default=UserRole.VIEWER
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RoleUpgradeStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RoleUpgradeRequest(Base):
    """A VIEWER's self-service application to be promoted to RESEARCHER —
    reviewed by an ADMIN (app/auth/service.py's review_upgrade_request()).
    Only RESEARCHER is offered as a target today (PLANNER/ADMIN stay
    invite-only, set directly on the user record), so target_role reuses
    the same `user_role` enum rather than inventing a second one."""

    __tablename__ = "role_upgrade_requests"
    __table_args__ = (
        # BR-style invariant: a user can't stack multiple PENDING
        # applications — same partial-unique-index technique as
        # parameter_sets' "one VALIDATED set per habitation" (app/parameters/
        # models.py), enforced in the database, not just checked in service.py.
        Index(
            "uq_one_pending_upgrade_request_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
        CheckConstraint("length(reason) >= 20", name="ck_role_upgrade_requests_reason_min_length"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    target_role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), default=UserRole.RESEARCHER)
    reason: Mapped[str] = mapped_column(Text)
    institution_or_department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[RoleUpgradeStatus] = mapped_column(
        Enum(RoleUpgradeStatus, name="role_upgrade_status"), default=RoleUpgradeStatus.PENDING
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
