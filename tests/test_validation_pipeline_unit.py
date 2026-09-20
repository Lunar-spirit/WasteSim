"""Stage 2 (range checks) exercised directly against plain Python objects —
no database, no HTTP, no event loop. Fast tests for the warn-band and
allowed_values behaviour that the API-level tests don't otherwise cover.
"""

from types import SimpleNamespace

from app.parameters.models import DataType, ParameterDefinition
from app.validation.pipeline import PipelineResult, _stage2_range_checks


def _definition(**overrides):
    base = dict(
        category="demography",
        param_key="annual_growth_rate_pct",
        display_label="Annual growth rate",
        data_type=DataType.NUMERIC,
        min_value=-5,
        max_value=10,
        warn_min=None,
        warn_max=None,
        allowed_values=None,
        severity_on_fail="ERROR",
        help_text=None,
    )
    base.update(overrides)
    return ParameterDefinition(**base)


def test_value_inside_hard_range_but_outside_warn_band_is_a_warning_not_an_error():
    definition = _definition(warn_min=-1, warn_max=8)
    row = SimpleNamespace(annual_growth_rate_pct=9)  # inside [-5, 10], outside [-1, 8]

    result = PipelineResult()
    _stage2_range_checks({"demography": row}, [definition], result)

    assert result.error_count == 0
    assert result.warning_count == 1
    assert result.issues[0].code == "VALUE_OUTSIDE_TYPICAL_RANGE"


def test_value_inside_warn_band_produces_no_issue_at_all():
    definition = _definition(warn_min=-1, warn_max=8)
    row = SimpleNamespace(annual_growth_rate_pct=2)

    result = PipelineResult()
    _stage2_range_checks({"demography": row}, [definition], result)

    assert result.issues == []


def test_value_outside_hard_range_is_an_error_even_with_a_warn_band_set():
    definition = _definition(warn_min=-1, warn_max=8)
    row = SimpleNamespace(annual_growth_rate_pct=14)  # outside [-5, 10] entirely

    result = PipelineResult()
    _stage2_range_checks({"demography": row}, [definition], result)

    assert result.error_count == 1
    assert result.issues[0].code == "VALUE_OUT_OF_RANGE"


def test_enum_field_rejects_a_value_outside_the_allowed_list():
    definition = _definition(
        category="terrain",
        param_key="soil_type",
        min_value=None,
        max_value=None,
        allowed_values=["SANDY", "CLAY", "LOAMY"],
    )
    row = SimpleNamespace(soil_type="ROCKY")

    result = PipelineResult()
    _stage2_range_checks({"terrain": row}, [definition], result)

    assert result.error_count == 1
    assert result.issues[0].code == "ENUM_NOT_ALLOWED"


def test_enum_field_match_is_case_insensitive():
    definition = _definition(
        category="terrain",
        param_key="soil_type",
        min_value=None,
        max_value=None,
        allowed_values=["SANDY"],
    )
    row = SimpleNamespace(soil_type="sandy")

    result = PipelineResult()
    _stage2_range_checks({"terrain": row}, [definition], result)

    assert result.issues == []


def test_enum_field_uses_severity_on_fail_from_the_catalogue():
    definition = _definition(
        category="terrain",
        param_key="soil_type",
        min_value=None,
        max_value=None,
        allowed_values=["SANDY"],
        severity_on_fail="WARNING",
    )
    row = SimpleNamespace(soil_type="ROCKY")

    result = PipelineResult()
    _stage2_range_checks({"terrain": row}, [definition], result)

    assert result.error_count == 0
    assert result.warning_count == 1
