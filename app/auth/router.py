from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.models import User
from app.auth.schemas import LoginIn, RefreshIn, RegisterIn, TokenOut, UserOut
from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_current_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", status_code=201)
async def register(payload: RegisterIn, db: AsyncSession = Depends(get_db)):
    user = await service.register_user(db, payload)
    await db.commit()
    return {"success": True, "data": UserOut.model_validate(user)}


@router.post("/login")
async def login(payload: LoginIn, db: AsyncSession = Depends(get_db)):
    user = await service.authenticate_user(db, payload.email, payload.password)
    access, refresh = await service.issue_tokens(db, user)
    await db.commit()
    token = TokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )
    return {"success": True, "data": token}


@router.post("/refresh")
async def refresh(payload: RefreshIn, db: AsyncSession = Depends(get_db)):
    access, refresh_token = await service.rotate_refresh_token(db, payload.refresh_token)
    await db.commit()
    token = TokenOut(
        access_token=access,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )
    return {"success": True, "data": token}


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    return {"success": True, "data": UserOut.model_validate(current_user)}


@router.post("/logout")
async def logout(
    payload: LogoutIn | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if payload and payload.refresh_token:
        await service.revoke_refresh_token(db, payload.refresh_token)
    else:
        await service.revoke_all_user_tokens(db, current_user.id)
    await db.commit()
    return {"success": True, "data": {"status": "logged_out"}}


users_router = APIRouter(prefix="/api/v1/users", tags=["users"])


@users_router.get("")
async def list_users_endpoint(
    role: UserRole | None = None,
    is_active: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    admin: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if admin.role != UserRole.ADMIN:
        from app.core.errors import AppError
        raise AppError("FORBIDDEN_ROLE", "Requires ADMIN role", 403)
    users = await service.list_users(db, role=role, is_active=is_active, limit=limit, offset=offset)
    return {"success": True, "data": [UserOut.model_validate(u) for u in users]}


@users_router.patch("/{user_id}/role")
async def update_role_endpoint(
    user_id: uuid.UUID,
    payload: UserRoleUpdate,
    admin: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if admin.role != UserRole.ADMIN:
        from app.core.errors import AppError
        raise AppError("FORBIDDEN_ROLE", "Requires ADMIN role", 403)
    user = await service.update_user_role(db, user_id, payload.role, admin.id)
    await db.commit()
    return {"success": True, "data": UserOut.model_validate(user)}


@users_router.patch("/{user_id}/status")
async def update_status_endpoint(
    user_id: uuid.UUID,
    payload: UserStatusUpdate,
    admin: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if admin.role != UserRole.ADMIN:
        from app.core.errors import AppError
        raise AppError("FORBIDDEN_ROLE", "Requires ADMIN role", 403)
    user = await service.update_user_status(db, user_id, payload.is_active, admin.id)
    await db.commit()
    return {"success": True, "data": UserOut.model_validate(user)}


@users_router.get("/{user_id}/habitations")
async def get_user_habitations_endpoint(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != UserRole.ADMIN and current_user.id != user_id:
        from app.core.errors import AppError
        raise AppError("FORBIDDEN_RESOURCE", "Cannot view habitations for another user", 403)
    habitations = await service.get_user_habitations(db, user_id)
    return {"success": True, "data": habitations}

