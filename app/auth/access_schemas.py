import uuid

from pydantic import BaseModel, ConfigDict

from app.auth.models import UserRole


class AssignPlannerIn(BaseModel):
    user_id: uuid.UUID
    habitation_id: uuid.UUID


class UnassignPlannerIn(BaseModel):
    user_id: uuid.UUID
    habitation_id: uuid.UUID


class RoleChangeIn(BaseModel):
    role: UserRole


class UserAccessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    # Habitations this user has a habitation_members row for — for a
    # PLANNER these are exactly the habitations they can write to.
    habitation_ids: list[uuid.UUID]
