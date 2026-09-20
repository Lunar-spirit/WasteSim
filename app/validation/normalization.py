"""Stage 1 of the pipeline: turn whatever a planner typed into a clean typed
value. Shared by the category PUT endpoints (clean on write) and the
/validate pipeline (re-check what is stored is still clean)."""

from decimal import Decimal
from typing import Any

from app.parameters.models import DataType


class NormalizationError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message


def normalize_value(raw: Any, data_type: DataType, normalization_rule: str | None = None) -> Any:
    if raw is None:
        return None

    if data_type in (DataType.INTEGER, DataType.NUMERIC):
        value = raw
        if isinstance(value, str):
            cleaned = value.strip().replace(",", "").rstrip("%")
            if cleaned == "":
                return None
            try:
                value = float(cleaned)
            except ValueError as exc:
                raise NormalizationError(f"'{raw}' is not a valid number") from exc
        elif isinstance(value, bool):
            raise NormalizationError(f"'{raw}' is not a valid number")
        elif isinstance(value, (int, float, Decimal)):
            value = float(value)
        else:
            raise NormalizationError(f"'{raw}' is not a valid number")

        if normalization_rule == "percent_from_fraction" and 0 <= value <= 1:
            value = value * 100

        return int(round(value)) if data_type == DataType.INTEGER else value

    if data_type == DataType.BOOLEAN:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            lowered = raw.strip().lower()
            if lowered in ("true", "yes", "1"):
                return True
            if lowered in ("false", "no", "0"):
                return False
        raise NormalizationError(f"'{raw}' is not a valid boolean")

    if data_type == DataType.STRING:
        return str(raw).strip()

    if data_type == DataType.JSON:
        # A JSON-body PUT already hands this a parsed dict — passed through
        # unchanged. A tabular (CSV/XLSX) upload cell can only ever be text,
        # so a composition value there arrives as a JSON-encoded string
        # (e.g. '{"organic": 55, "plastic": 12, ...}') and needs parsing
        # before Stage 3's composition-sum check can read it.
        if isinstance(raw, str):
            import json

            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise NormalizationError(f"'{raw}' is not valid JSON") from exc
        return raw

    return raw
