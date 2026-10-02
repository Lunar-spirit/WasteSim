"""Module M14 (reports, design section 4.4 / BG-07). Renders a completed run
or a saved comparison to PDF, XLSX or CSV and stores the bytes in MinIO —
the numbers all come from simulation_yearly/run_findings (or, for a
comparison, from app.comparison.service's own aligned series), never
recomputed here.
"""

from __future__ import annotations

import csv
import html
import io
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from weasyprint import HTML

from app.auth.models import User, UserRole
from app.comparison.models import RunComparison
from app.comparison.service import get_aligned_series, get_comparison_or_404
from app.core import storage
from app.core.errors import AppError
from app.habitation.models import Habitation
from app.reports import svg
from app.reports.models import Report, ReportFormat, ReportStatus
from app.simulation.models import COMPOSITION_FRACTIONS, RunFinding, SimulationResult, SimulationRun, SimulationYearly

REPORT_EXPIRY_SECONDS = 24 * 60 * 60  # design: "Download links are time-limited"


async def create_report(db: AsyncSession, payload: Any, user: User) -> Report:
    if (payload.run_id is None) == (payload.comparison_id is None):
        raise AppError("REPORT_SUBJECT_REQUIRED", "Exactly one of run_id or comparison_id must be set", 400)

    if payload.run_id is not None:
        run = await db.get(SimulationRun, payload.run_id)
        if run is None:
            raise AppError("RUN_NOT_FOUND", "Run not found", 404)
        habitation_id = run.habitation_id
    else:
        comparison = await get_comparison_or_404(db, payload.comparison_id)
        habitation_id = comparison.habitation_id

    report = Report(
        habitation_id=habitation_id,
        run_id=payload.run_id,
        comparison_id=payload.comparison_id,
        format=payload.format,
        status=ReportStatus.QUEUED,
        created_by=user.id,
    )
    db.add(report)
    await db.flush()
    return report


async def get_report_or_404(db: AsyncSession, report_id: uuid.UUID) -> Report:
    report = await db.get(Report, report_id)
    if report is None:
        raise AppError("REPORT_NOT_FOUND", "Report not found", 404)
    return report


async def _run_report_rows(db: AsyncSession, run: SimulationRun) -> tuple[list[dict[str, Any]], list[RunFinding]]:
    yearly = list(
        await db.scalars(select(SimulationYearly).where(SimulationYearly.run_id == run.id).order_by(SimulationYearly.year_index))
    )
    findings = list(await db.scalars(select(RunFinding).where(RunFinding.run_id == run.id)))
    rows = [
        {c.name: getattr(y, c.name) for c in SimulationYearly.__table__.columns if c.name not in ("id", "run_id")}
        for y in yearly
    ]
    return rows, findings


async def _latest_composition(db: AsyncSession, run_id: uuid.UUID) -> dict[str, float]:
    """The composition donut's data source — simulation_yearly doesn't carry
    per-fraction columns (see app/simulation/models.py), only the monthly
    simulation_results table does. The engine doesn't drift composition
    month to month, so the most recent month represents the whole run."""
    latest = await db.scalar(
        select(SimulationResult).where(SimulationResult.run_id == run_id).order_by(SimulationResult.month_index.desc())
    )
    if latest is None:
        return {}
    return {fraction: float(getattr(latest, f"{fraction}_pct")) for fraction in COMPOSITION_FRACTIONS}


def _milestone_summary(findings: list[RunFinding], yearly: list[dict[str, Any]]) -> dict[str, Any]:
    by_code = {f.code: f for f in findings}
    peak_generation_row = max(yearly, key=lambda r: r["waste_total_tpy"], default=None)
    return {
        "landfill_exhaustion_year": by_code["LANDFILL_EXHAUSTION_YEAR"].year_index
        if "LANDFILL_EXHAUSTION_YEAR" in by_code
        else None,
        "peak_generation_year": peak_generation_row["year_index"] if peak_generation_row else None,
        "diversion_rate_pct_final": yearly[-1]["recovery_rate_pct"] if yearly else None,
    }


def _step_projection_rows(yearly: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Base, Y5, Y10, Y15, Y20 (or whatever the run's own horizon allows —
    a shorter run just shows fewer of these steps)."""
    by_year = {r["year_index"]: r for r in yearly}
    steps = []
    for year_index in (1, 5, 10, 15, 20):
        row = by_year.get(year_index)
        if row is not None:
            steps.append(row)
    return steps


def _render_run_pdf(
    habitation_name: str,
    run: SimulationRun,
    rows: list[dict[str, Any]],
    findings: list[RunFinding],
    composition: dict[str, float],
    is_viewer: bool,
) -> bytes:
    esc = html.escape
    generated_at = datetime.now(timezone.utc).strftime("%d %b %Y")

    findings_html = "".join(
        f"<tr><td>{esc(f.code)}</td><td>{esc(f.severity.value)}</td><td>{esc(f.message)}</td></tr>" for f in findings
    )
    header = "".join(f"<th>{esc(str(key))}</th>" for key in (rows[0].keys() if rows else []))
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(str(value))}</td>" for value in row.values()) + "</tr>" for row in rows
    )

    milestones = _milestone_summary(findings, rows)
    step_rows = _step_projection_rows(rows)
    step_header = "".join(f"<th>Y{r['year_index']}</th>" for r in step_rows)
    step_fields = [
        ("Population", "population_end", "{:,.0f}"),
        ("Waste Generated (t/yr)", "waste_total_tpy", "{:,.1f}"),
        ("Landfilled (t/yr)", "landfilled_tpy", "{:,.1f}"),
        ("Diversion Rate (%)", "recovery_rate_pct", "{:.1f}"),
        ("Total Cost (INR)", "total_cost_inr", "₹{:,.0f}"),
    ]
    step_body = "".join(
        f"<tr><td class='label'>{esc(label)}</td>"
        + "".join(f"<td>{fmt.format(float(r[field]))}</td>" for r in step_rows)
        + "</tr>"
        for label, field, fmt in step_fields
    )

    calibrated = run.meta.get("calibrated_from_daily_logs") if run.meta else False
    calibration_status = (
        f"Calibrated with Field Data ({run.meta.get('log_sample_count')} logs)" if calibrated else "Theoretical Parameter Baseline"
    )
    baseline_row = rows[0] if rows else None

    trajectory_svg = svg.trajectory_chart_svg(rows, [{"code": f.code, "year_index": f.year_index} for f in findings])
    composition_svg = svg.composition_donut_svg(composition)
    cost_svg = svg.masked_chart_svg(640, 280) if is_viewer else svg.cost_curve_svg(rows)

    document = f"""
    <html><head><style>
      @page {{
        size: A4;
        margin: 20mm;
        @top-left {{ content: "{esc(habitation_name)}"; font-size: 8px; color: #94a3b8; }}
        @top-right {{ content: "{generated_at}"; font-size: 8px; color: #94a3b8; }}
        @bottom-center {{ content: "Page " counter(page) " of " counter(pages); font-size: 8px; color: #94a3b8; }}
      }}
      body {{ font-family: Helvetica, Arial, sans-serif; font-size: 10px; color: #1e293b; }}
      h1 {{ font-size: 18px; margin-bottom: 2px; }}
      h2 {{ font-size: 13px; margin-top: 22px; margin-bottom: 8px; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }}
      .subtitle {{ color: #64748b; margin-top: 0; }}
      table {{ border-collapse: collapse; width: 100%; }}
      th, td {{ border: 1px solid #e2e8f0; padding: 4px 6px; text-align: right; }}
      td.label {{ text-align: left; font-weight: 600; color: #475569; }}
      th {{ background: #f1f5f9; }}
      .profile-card {{ display: flex; gap: 14px; }}
      .profile-stat {{ flex: 1; border: 1px solid #e2e8f0; border-radius: 6px; padding: 8px 10px; }}
      .profile-stat .value {{ font-size: 14px; font-weight: 700; color: #0f172a; }}
      .profile-stat .label {{ font-size: 8px; text-transform: uppercase; color: #94a3b8; letter-spacing: 0.04em; }}
      .charts {{ display: flex; flex-wrap: wrap; gap: 12px; justify-content: space-between; }}
      .chart-box {{ width: 100%; }}
      .chart-box.half {{ width: 48%; }}
      .badge {{ display: inline-block; border-radius: 10px; padding: 2px 8px; font-size: 8px; font-weight: 600; }}
      .badge.calibrated {{ background: #d1fae5; color: #065f46; }}
      .badge.baseline {{ background: #f1f5f9; color: #64748b; }}
    </style></head><body>
      <h1>{esc(habitation_name)} — Simulation Report</h1>
      <p class="subtitle">Run: {esc(run.label or str(run.id))} · Type: {esc(run.run_type.value)} · Horizon: {run.horizon_years} years</p>

      <h2>Habitation Profile</h2>
      <div class="profile-card">
        <div class="profile-stat"><div class="value">{f"{int(baseline_row['population_end']):,}" if baseline_row else "—"}</div><div class="label">Population (Year 1)</div></div>
        <div class="profile-stat"><div class="value">{f"{float(baseline_row['waste_total_tpy']):,.1f} t/yr" if baseline_row else "—"}</div><div class="label">Baseline Tonnage</div></div>
        <div class="profile-stat">
          <div class="value"><span class="badge {'calibrated' if calibrated else 'baseline'}">{esc(calibration_status)}</span></div>
          <div class="label">Data Calibration Status</div>
        </div>
      </div>

      <h2>Executive Milestone Summary</h2>
      <div class="profile-card">
        <div class="profile-stat"><div class="value">{milestones["landfill_exhaustion_year"] or "Not within horizon"}</div><div class="label">Landfill Lifespan (Year)</div></div>
        <div class="profile-stat"><div class="value">{milestones["peak_generation_year"] or "—"}</div><div class="label">Peak Generation Year</div></div>
        <div class="profile-stat"><div class="value">{f"{milestones['diversion_rate_pct_final']:.1f}%" if milestones["diversion_rate_pct_final"] is not None else "—"}</div><div class="label">Final-Year Diversion %</div></div>
      </div>

      <h2>Visual Projections</h2>
      <div class="charts">
        <div class="chart-box">{trajectory_svg}</div>
        <div class="chart-box half">{composition_svg}</div>
        <div class="chart-box half">{cost_svg}</div>
      </div>

      <h2>5-Year Step Projections</h2>
      <table><tr><th></th>{step_header}</tr>{step_body}</table>

      <h2>Findings</h2>
      <table><tr><th>Code</th><th>Severity</th><th>Message</th></tr>{findings_html}</table>

      <h2>Yearly Results</h2>
      <table><tr>{header}</tr>{body}</table>
    </body></html>
    """
    return HTML(string=document).write_pdf()


def _render_rows_xlsx(sheet_name: str, rows: list[dict[str, Any]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name[:31]
    if rows:
        ws.append(list(rows[0].keys()))
        for row in rows:
            ws.append(list(row.values()))
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _render_rows_csv(rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return buffer.getvalue().encode()


async def _comparison_rows(db: AsyncSession, comparison: RunComparison) -> list[dict[str, Any]]:
    aligned = await get_aligned_series(db, comparison)
    rows = []
    for indicator, points in aligned["series"].items():
        for point in points:
            row = {"indicator": indicator, "year_index": point["year_index"]}
            row.update(point["values"])
            rows.append(row)
    return rows


def _render_comparison_pdf(habitation_name: str, comparison: RunComparison, rows: list[dict[str, Any]]) -> bytes:
    esc = html.escape
    header = "".join(f"<th>{esc(str(key))}</th>" for key in (rows[0].keys() if rows else []))
    body = "".join("<tr>" + "".join(f"<td>{esc(str(v))}</td>" for v in row.values()) + "</tr>" for row in rows)
    document = f"""
    <html><head><style>
      body {{ font-family: sans-serif; font-size: 10px; }}
      table {{ border-collapse: collapse; width: 100%; }}
      th, td {{ border: 1px solid #ccc; padding: 3px 6px; text-align: right; }}
      th {{ background: #eee; }}
    </style></head><body>
      <h1>{esc(habitation_name)} — {esc(comparison.title or 'Run Comparison')}</h1>
      <p>Runs: {esc(', '.join(comparison.run_ids))}</p>
      <table><tr>{header}</tr>{body}</table>
    </body></html>
    """
    return HTML(string=document).write_pdf()


async def generate_report(db: AsyncSession, report: Report) -> None:
    report.status = ReportStatus.GENERATING
    await db.flush()

    habitation = await db.get(Habitation, report.habitation_id)

    if report.run_id is not None:
        run = await db.get(SimulationRun, report.run_id)
        rows, findings = await _run_report_rows(db, run)
        if report.format == ReportFormat.PDF:
            composition = await _latest_composition(db, run.id)
            # A PDF is a static artifact, generated once and possibly
            # downloaded by someone else later (anyone with read access to
            # the habitation) — so "mask the cost curve for VIEWER" is
            # decided once, from whoever requested the report, the same way
            # BudgetSummary masks fields for the CURRENT caller at read time
            # (app/budget/router.py) but baked in here instead, since a
            # rendered PDF can't re-check a role per download.
            creator = await db.get(User, report.created_by)
            is_viewer = creator is not None and creator.role == UserRole.VIEWER
            data, content_type, ext = (
                _render_run_pdf(habitation.name, run, rows, findings, composition, is_viewer),
                "application/pdf",
                "pdf",
            )
        elif report.format == ReportFormat.XLSX:
            data, content_type, ext = (
                _render_rows_xlsx("yearly", rows),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "xlsx",
            )
        else:
            data, content_type, ext = _render_rows_csv(rows), "text/csv", "csv"
    else:
        comparison = await db.get(RunComparison, report.comparison_id)
        rows = await _comparison_rows(db, comparison)
        if report.format == ReportFormat.PDF:
            data, content_type, ext = (
                _render_comparison_pdf(habitation.name, comparison, rows),
                "application/pdf",
                "pdf",
            )
        elif report.format == ReportFormat.XLSX:
            data, content_type, ext = (
                _render_rows_xlsx("comparison", rows),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "xlsx",
            )
        else:
            data, content_type, ext = _render_rows_csv(rows), "text/csv", "csv"

    key = f"reports/{report.id}.{ext}"
    storage.put_object(key, data, content_type)

    report.storage_key = key
    report.status = ReportStatus.READY
    report.expires_at = datetime.now(timezone.utc) + timedelta(seconds=REPORT_EXPIRY_SECONDS)
    await db.flush()


def get_download_url(report: Report) -> str:
    if report.status != ReportStatus.READY or report.storage_key is None:
        raise AppError("REPORT_NOT_READY", f"Report is {report.status.value}, not READY", 409)
    ext = report.storage_key.rsplit(".", 1)[-1]
    filename = f"SWMS_Report_{report.id}.{ext}"
    return storage.get_presigned_url(report.storage_key, REPORT_EXPIRY_SECONDS, download_filename=filename)
