from datetime import date

from pydantic import BaseModel


class MovingAverageOut(BaseModel):
    window_days: int
    sample_days: int
    avg_total_collected_tpd: float | None
    avg_organic_tpd: float | None
    avg_dry_recyclable_tpd: float | None
    avg_vehicles_deployed: float | None
    avg_coverage_pct_observed: float | None


class VarianceMetricOut(BaseModel):
    label: str
    theoretical: float | None
    empirical: float | None
    variance_pct: float | None


class RecalibrationReportOut(BaseModel):
    habitation_id: str
    as_of: date
    logged_day_count_90d: int
    moving_average_30d: MovingAverageOut
    moving_average_90d: MovingAverageOut
    moving_average_annual: MovingAverageOut
    total_generation_variance: VarianceMetricOut
    per_capita_variance: VarianceMetricOut
    segregation_variance: VarianceMetricOut
    fleet_efficiency_variance: VarianceMetricOut
    derived_festival_multiplier: float | None
    notes: list[str]
