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
