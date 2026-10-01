import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.models import RoleUpgradeStatus, User, UserRole
from app.auth.schemas import (
    ApplyResearcherIn,
    AssignRoleIn,
    LoginIn,
    RefreshIn,
    RegisterIn,
    ReviewUpgradeRequestIn,
    RoleUpgradeRequestAdminOut,
    RoleUpgradeRequestOut,
    TokenOut,
    UserOut,
)
from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_current_user, require_role

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
admin_router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


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


@router.post("/apply-researcher", status_code=201)
async def apply_researcher(
    payload: ApplyResearcherIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    request = await service.apply_for_researcher(db, current_user, payload)
    await db.commit()
    return {"success": True, "data": RoleUpgradeRequestOut.model_validate(request)}


@router.get("/my-application-status")
async def my_application_status(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    request = await service.get_latest_application(db, current_user)
    data = RoleUpgradeRequestOut.model_validate(request) if request is not None else None
    return {"success": True, "data": data}


@admin_router.get("/upgrade-requests")
async def list_upgrade_requests(
    status: RoleUpgradeStatus | None = Query(default=None),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    rows = await service.list_upgrade_requests(db, status)
    data = [
        RoleUpgradeRequestAdminOut(
            **RoleUpgradeRequestOut.model_validate(request).model_dump(),
            applicant_email=applicant.email,
            applicant_full_name=applicant.full_name,
        )
        for request, applicant in rows
    ]
    return {"success": True, "data": data}


@admin_router.post("/upgrade-requests/{request_id}/review")
async def review_upgrade_request(
    request_id: uuid.UUID,
    payload: ReviewUpgradeRequestIn,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    request = await service.get_upgrade_request_or_404(db, request_id)
    request = await service.review_upgrade_request(db, request, current_user, payload.action, payload.review_notes)
    await db.commit()
    return {"success": True, "data": RoleUpgradeRequestOut.model_validate(request)}


@admin_router.get("/users")
async def list_users(
    current_user: User = Depends(require_role(UserRole.ADMIN)), db: AsyncSession = Depends(get_db)
):
    users = await service.list_all_users(db)
    return {"success": True, "data": [UserOut.model_validate(u) for u in users]}


@admin_router.patch("/users/{user_id}/role")
async def assign_role(
    user_id: uuid.UUID,
    payload: AssignRoleIn,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Direct override — an ADMIN can set any user to any role here, no
    application or approval needed. Distinct from POST /admin/upgrade-
    requests/{id}/review, which only ever promotes VIEWER -> RESEARCHER
    against a specific application on file."""
    user = await service.get_user_or_404(db, user_id)
    user = await service.assign_role(db, user, payload.role)
    await db.commit()
    return {"success": True, "data": UserOut.model_validate(user)}
