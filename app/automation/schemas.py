import uuid

from pydantic import BaseModel


class AutoPopulateIn(BaseModel):
    parameter_set_id: uuid.UUID | None = None


class AutoPopulateOut(BaseModel):
    parameter_set_id: str
    automated_categories: list[str]
    skipped_categories: list[dict[str, str]]
    derived_fields: list[str]
    manual_fields_remaining: list[str]
    gis_layer_id: str | None = None
