import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.parameters.models import CATEGORY_MODELS, ParameterDefinition, WasteBaseline
from app.validation.normalization import NormalizationError, normalize_value
from app.validation.models import Severity

ALL_CATEGORIES = {**CATEGORY_MODELS, "waste_baseline": WasteBaseline}
COMPOSITION_TOLERANCE_PCT = 0.5


@dataclass
class Issue:
    severity: Severity
    code: str
    field_path: str
    message: str
    observed_value: str | None = None
    expected_range: str | None = None
    suggested_fix: str | None = None
    category: str | None = None
    # 1-based row number in a tabular upload; None for a JSON API call or a
    # rule (like the composition sum) that isn't tied to one row.
    row_number: int | None = None


@dataclass
class PipelineResult:
    issues: list[Issue] = field(default_factory=list)
    completeness_pct: float = 0.0
    # {"DEMOGRAPHY": 100.0, "TERRAIN": 57.1, ...} — mirrors
    # validation_reports.completeness_by_category.
    completeness_by_category: dict[str, float] = field(default_factory=dict)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.WARNING)


async def run_pipeline(db: AsyncSession, psid: uuid.UUID) -> PipelineResult:
    result = PipelineResult()

    rows: dict[str, Any] = {}
    for category, model in ALL_CATEGORIES.items():
        rows[category] = await db.get(model, psid)

    definitions = list(await db.scalars(select(ParameterDefinition)))

    _stage0_structural(rows, result)
    _stage1_normalization(rows, definitions, result)
    _stage2_range_checks(rows, definitions, result)
    _stage3_cross_field(rows, result)
    _stage5_completeness(rows, definitions, result)

    return result


def _stage0_structural(rows: dict[str, Any], result: PipelineResult) -> None:
    baseline = rows.get("waste_baseline")
    if baseline is not None and baseline.composition is not None and not isinstance(
        baseline.composition, dict
    ):
        result.issues.append(
            Issue(
                Severity.ERROR,
                "STRUCTURAL_INVALID",
                "waste_baseline.composition",
                "composition must be a JSON object of fraction name to percentage",
                observed_value=str(baseline.composition),
                category="WASTE_BASELINE",
            )
        )


def _stage1_normalization(
    rows: dict[str, Any], definitions: list[ParameterDefinition], result: PipelineResult
) -> None:
    for definition in definitions:
        row = rows.get(definition.category)
        if row is None or not hasattr(row, definition.param_key):
            continue
        value = getattr(row, definition.param_key)
        if value is None:
            continue
        try:
            normalize_value(value, definition.data_type, definition.normalization_rule)
        except NormalizationError as exc:
            result.issues.append(
                Issue(
                    Severity.ERROR,
                    "NORMALIZATION_FAILED",
                    f"{definition.category}.{definition.param_key}",
                    exc.message,
                    observed_value=str(value),
                    category=definition.category.upper(),
                )
            )


def _stage2_range_checks(
    rows: dict[str, Any], definitions: list[ParameterDefinition], result: PipelineResult
) -> None:
    for definition in definitions:
        row = rows.get(definition.category)
        if row is None or not hasattr(row, definition.param_key):
            continue
        value = getattr(row, definition.param_key)
        if value is None:
            continue

        # A field with a fixed vocabulary (allowed_values, e.g.
        # terrain.soil_type) is checked by membership, not by numeric range —
        # the two are mutually exclusive for any one field.
        if definition.allowed_values:
            _enum_check(result, definition, value)
            continue

        try:
            num_val = float(value)
        except (ValueError, TypeError):
            continue

        severity = Severity(definition.severity_on_fail)
        if definition.min_value is not None and num_val < float(definition.min_value):
            _range_issue(result, definition, value, severity)
        elif definition.max_value is not None and num_val > float(definition.max_value):
            _range_issue(result, definition, value, severity)
        # Soft (warn_min/warn_max) bounds only matter once the hard bounds
        # already passed: a value can't be both out of range and merely
        # "outside the typical range".
        elif definition.warn_min is not None and num_val < float(definition.warn_min):
            _warn_range_issue(result, definition, value)
        elif definition.warn_max is not None and num_val > float(definition.warn_max):
            _warn_range_issue(result, definition, value)


def _range_issue(
    result: PipelineResult, definition: ParameterDefinition, value: Any, severity: Severity = Severity.ERROR
) -> None:
    lo = definition.min_value if definition.min_value is not None else "-inf"
    hi = definition.max_value if definition.max_value is not None else "+inf"
    result.issues.append(
        Issue(
            severity,
            "VALUE_OUT_OF_RANGE",
            f"{definition.category}.{definition.param_key}",
            f"{definition.display_label} must be between {lo} and {hi}",
            observed_value=str(value),
            expected_range=f"[{lo}, {hi}]",
            suggested_fix=definition.help_text
            or f"Set {definition.category}.{definition.param_key} between {lo} and {hi}",
            category=definition.category.upper(),
        )
    )


def _warn_range_issue(result: PipelineResult, definition: ParameterDefinition, value: Any) -> None:
    """Outside the *typical* range but still inside the hard min/max — legal,
    still worth a planner's second look. Never blocks commit (only ERROR
    issues count toward error_count)."""
    result.issues.append(
        Issue(
            Severity.WARNING,
            "VALUE_OUTSIDE_TYPICAL_RANGE",
            f"{definition.category}.{definition.param_key}",
            f"{definition.display_label} of {value} is outside the typical range "
            f"[{definition.warn_min}, {definition.warn_max}], though still a valid value",
            observed_value=str(value),
            expected_range=f"[{definition.warn_min}, {definition.warn_max}]",
            suggested_fix=definition.help_text,
            category=definition.category.upper(),
        )
    )


def _enum_check(result: PipelineResult, definition: ParameterDefinition, value: Any) -> None:
    allowed = definition.allowed_values or []
    if str(value).upper() not in {str(v).upper() for v in allowed}:
        result.issues.append(
            Issue(
                Severity(definition.severity_on_fail),
                "ENUM_NOT_ALLOWED",
                f"{definition.category}.{definition.param_key}",
                f"{definition.display_label} must be one of {allowed}",
                observed_value=str(value),
                expected_range=str(allowed),
                suggested_fix=definition.help_text or f"Choose one of {allowed}",
                category=definition.category.upper(),
            )
        )


def _stage3_cross_field(rows: dict[str, Any], result: PipelineResult) -> None:
    baseline = rows.get("waste_baseline")
    if baseline is None or not baseline.composition:
        return
    total = sum(float(v) for v in baseline.composition.values())
    if abs(total - 100.0) > COMPOSITION_TOLERANCE_PCT:
        result.issues.append(
            Issue(
                Severity.ERROR,
                "COMPOSITION_SUM_MISMATCH",
                "waste_baseline.composition",
                f"Composition fractions sum to {total:.2f}%, expected 100% (+/- {COMPOSITION_TOLERANCE_PCT}%)",
                observed_value=f"{total:.2f}",
                expected_range="[99.5, 100.5]",
                suggested_fix="Adjust composition fractions so they sum to 100%",
                category="WASTE_BASELINE",
            )
        )


def _stage5_completeness(
    rows: dict[str, Any], definitions: list[ParameterDefinition], result: PipelineResult
) -> None:
    required = [d for d in definitions if d.is_required]
    if not required:
        result.completeness_pct = 100.0
        return

    present = 0
    by_category: dict[str, list[bool]] = {}
    for definition in required:
        row = rows.get(definition.category)
        value = getattr(row, definition.param_key, None) if row is not None else None
        is_present = value is not None
        by_category.setdefault(definition.category.upper(), []).append(is_present)
        if is_present:
            present += 1
        else:
            result.issues.append(
                Issue(
                    Severity.ERROR,
                    "REQUIRED_FIELD_MISSING",
                    f"{definition.category}.{definition.param_key}",
                    f"{definition.display_label} is required",
                    suggested_fix=f"Provide a value for {definition.category}.{definition.param_key}",
                    category=definition.category.upper(),
                )
            )

    result.completeness_pct = round(present / len(required) * 100, 3)
    result.completeness_by_category = {
        category: round(sum(flags) / len(flags) * 100, 3) for category, flags in by_category.items()
    }


def validate_and_normalize_field(
    definition: ParameterDefinition, raw_value: Any, row_number: int | None = None
) -> tuple[Any, list[Issue]]:
    """Stage 1 + Stage 2 for exactly one (category, param_key, raw_value)
    triple — what one row of a tabular PARAMETERS upload actually is (see
    app/ingestion/parsers.py's docstring for why a row is one field, not one
    habitation). Reuses the exact same range/warn/enum logic and issue codes
    as the JSON-body path above, just entered per-value instead of per
    already-persisted ORM row, so a planner and a spreadsheet uploader see
    identically-worded problems for the identically-shaped mistake.

    Returns the normalized value (None if normalization itself failed) and
    the issues raised, each carrying `row_number` for BR-18.
    """
    issues: list[Issue] = []
    if raw_value is None or (isinstance(raw_value, str) and raw_value.strip() == ""):
        return None, issues

    try:
        value = normalize_value(raw_value, definition.data_type, definition.normalization_rule)
    except NormalizationError as exc:
        issues.append(
            Issue(
                Severity.ERROR,
                "NORMALIZATION_FAILED",
                f"{definition.category}.{definition.param_key}",
                exc.message,
                observed_value=str(raw_value),
                category=definition.category.upper(),
                row_number=row_number,
            )
        )
        return None, issues

    probe = PipelineResult()
    if definition.allowed_values:
        _enum_check(probe, definition, value)
    elif isinstance(value, (int, float)):
        severity = Severity(definition.severity_on_fail)
        if definition.min_value is not None and value < float(definition.min_value):
            _range_issue(probe, definition, value, severity)
        elif definition.max_value is not None and value > float(definition.max_value):
            _range_issue(probe, definition, value, severity)
        elif definition.warn_min is not None and value < float(definition.warn_min):
            _warn_range_issue(probe, definition, value)
        elif definition.warn_max is not None and value > float(definition.warn_max):
            _warn_range_issue(probe, definition, value)

    for issue in probe.issues:
        issue.row_number = row_number
    issues.extend(probe.issues)
    return value, issues
