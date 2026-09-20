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
