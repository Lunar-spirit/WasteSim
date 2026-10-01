import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import RefreshToken, RoleUpgradeRequest, RoleUpgradeStatus, User, UserRole
from app.auth.schemas import ApplyResearcherIn, RegisterIn
from app.core.errors import AppError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)


async def register_user(db: AsyncSession, payload: RegisterIn) -> User:
    existing = await db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise AppError("EMAIL_TAKEN", "An account with this email already exists", 409)

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=UserRole.VIEWER,  # forced — RegisterIn has no `role` field to override this with
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
    if user is None or not verify_password(password, user.hashed_password):
        raise AppError("INVALID_CREDENTIALS", "Incorrect email or password", 401)
    if not user.is_active:
        raise AppError("ACCOUNT_DISABLED", "This account has been disabled", 401)
    return user


async def issue_tokens(db: AsyncSession, user: User) -> tuple[str, str]:
    access = create_access_token(user.id, user.role.value)
    refresh, expires_at = create_refresh_token(user.id)
    db.add(RefreshToken(user_id=user.id, token_hash=hash_token(refresh), expires_at=expires_at))
    await db.flush()
    return access, refresh


async def rotate_refresh_token(db: AsyncSession, refresh_token: str) -> tuple[str, str]:
    from app.core.security import decode_token

    try:
        payload = decode_token(refresh_token)
    except ValueError as exc:
        raise AppError("INVALID_TOKEN", "Refresh token is invalid or expired", 401) from exc
    if payload.get("type") != "refresh":
        raise AppError("INVALID_TOKEN", "Not a refresh token", 401)

    token_hash = hash_token(refresh_token)
    stored = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if stored is None or stored.revoked_at is not None:
        raise AppError("INVALID_TOKEN", "Refresh token is invalid or expired", 401)
    if stored.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise AppError("INVALID_TOKEN", "Refresh token is invalid or expired", 401)

    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise AppError("INVALID_TOKEN", "Refresh token is invalid or expired", 401)

    stored.revoked_at = datetime.now(timezone.utc)
    return await issue_tokens(db, user)


async def apply_for_researcher(db: AsyncSession, user: User, payload: ApplyResearcherIn) -> RoleUpgradeRequest:
    if user.role != UserRole.VIEWER:
        raise AppError(
            "NOT_A_VIEWER", "Only a VIEWER account can apply for the RESEARCHER role", 409
        )

    existing_pending = await db.scalar(
        select(RoleUpgradeRequest).where(
            RoleUpgradeRequest.user_id == user.id, RoleUpgradeRequest.status == RoleUpgradeStatus.PENDING
        )
    )
    if existing_pending is not None:
        raise AppError(
            "APPLICATION_ALREADY_PENDING", "You already have a pending RESEARCHER application", 409
        )

    request = RoleUpgradeRequest(
        user_id=user.id,
        target_role=UserRole.RESEARCHER,
        reason=payload.reason,
        institution_or_department=payload.institution_or_department,
    )
    db.add(request)
    await db.flush()
    return request


async def get_latest_application(db: AsyncSession, user: User) -> RoleUpgradeRequest | None:
    return await db.scalar(
        select(RoleUpgradeRequest)
        .where(RoleUpgradeRequest.user_id == user.id)
        .order_by(RoleUpgradeRequest.created_at.desc())
        .limit(1)
    )


async def list_upgrade_requests(
    db: AsyncSession, status_filter: RoleUpgradeStatus | None
) -> list[tuple[RoleUpgradeRequest, User]]:
    stmt = select(RoleUpgradeRequest, User).join(User, User.id == RoleUpgradeRequest.user_id)
    if status_filter is not None:
        stmt = stmt.where(RoleUpgradeRequest.status == status_filter)
    stmt = stmt.order_by(RoleUpgradeRequest.created_at.desc())
    return list((await db.execute(stmt)).all())


async def get_upgrade_request_or_404(db: AsyncSession, request_id: uuid.UUID) -> RoleUpgradeRequest:
    request = await db.get(RoleUpgradeRequest, request_id)
    if request is None:
        raise AppError("UPGRADE_REQUEST_NOT_FOUND", "Role upgrade request not found", 404)
    return request


async def review_upgrade_request(
    db: AsyncSession,
    request: RoleUpgradeRequest,
    reviewer: User,
    action: str,
    review_notes: str | None,
) -> RoleUpgradeRequest:
    if request.status != RoleUpgradeStatus.PENDING:
        raise AppError(
            "UPGRADE_REQUEST_ALREADY_REVIEWED", f"This application is already {request.status.value}", 409
        )

    applicant = await db.get(User, request.user_id)
    if applicant is None:
        raise AppError("USER_NOT_FOUND", "The applicant's account no longer exists", 404)

    request.review_notes = review_notes
    request.reviewed_by = reviewer.id
    request.reviewed_at = datetime.now(timezone.utc)

    if action == "APPROVE":
        request.status = RoleUpgradeStatus.APPROVED
        applicant.role = request.target_role
    else:
        request.status = RoleUpgradeStatus.REJECTED

    await db.flush()
    return request


async def list_all_users(db: AsyncSession) -> list[User]:
    stmt = select(User).where(User.deleted_at.is_(None)).order_by(User.created_at.desc())
    return list(await db.scalars(stmt))


async def get_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise AppError("USER_NOT_FOUND", "User not found", 404)
    return user


async def assign_role(db: AsyncSession, user: User, role: UserRole) -> User:
    """Direct admin override, no application/approval needed — separate
    from the VIEWER->RESEARCHER moderated workflow above. Leaves any
    pending role_upgrade_requests row for this user untouched (still
    PENDING); an admin reviewing it afterward just approves/rejects
    against whatever the user's role already is by then."""
    user.role = role
    await db.flush()
    return user
