import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import RefreshToken, User, UserRole
from app.auth.schemas import RegisterIn
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
        role=UserRole.RESEARCHER,  # forced regardless of what the client sent
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


async def revoke_refresh_token(db: AsyncSession, refresh_token: str) -> None:
    token_hash = hash_token(refresh_token)
    stored = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = datetime.now(timezone.utc)


async def revoke_all_user_tokens(db: AsyncSession, user_id: uuid.UUID) -> None:
    tokens = await db.scalars(
        select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
    )
    now = datetime.now(timezone.utc)
    for t in tokens:
        t.revoked_at = now


async def list_users(
    db: AsyncSession,
    role: UserRole | None = None,
    is_active: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[User]:
    stmt = select(User).where(User.deleted_at.is_(None))
    if role is not None:
        stmt = stmt.where(User.role == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    stmt = stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)
    result = await db.scalars(stmt)
    return list(result)


async def get_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise AppError("USER_NOT_FOUND", "User not found", 404)
    return user


async def update_user_role(db: AsyncSession, user_id: uuid.UUID, new_role: UserRole, actor_id: uuid.UUID) -> User:
    user = await get_user_or_404(db, user_id)
    old_role = user.role.value
    user.role = new_role
    await db.flush()
    return user


async def update_user_status(db: AsyncSession, user_id: uuid.UUID, is_active: bool, actor_id: uuid.UUID) -> User:
    user = await get_user_or_404(db, user_id)
    user.is_active = is_active
    if not is_active:
        await revoke_all_user_tokens(db, user.id)
    await db.flush()
    return user


async def get_user_habitations(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    from app.habitation.models import Habitation, HabitationMember

    stmt = (
        select(Habitation, HabitationMember.access_level)
        .join(HabitationMember, Habitation.id == HabitationMember.habitation_id)
        .where(HabitationMember.user_id == user_id, Habitation.deleted_at.is_(None))
    )
    rows = await db.execute(stmt)
    habitations = []
    for hab, access in rows:
        habitations.append({
            "id": hab.id,
            "name": hab.name,
            "habitation_type": hab.habitation_type.value,
            "state": hab.state,
            "district": hab.district,
            "status": hab.status.value,
            "access_level": access.value if access else None,
        })
    return habitations

