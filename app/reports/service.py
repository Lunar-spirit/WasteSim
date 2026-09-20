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

from app.auth.models import User
from app.comparison.models import RunComparison
from app.comparison.service import get_aligned_series, get_comparison_or_404
from app.core import storage
from app.core.errors import AppError
from app.habitation.models import Habitation
from app.reports.models import Report, ReportFormat, ReportStatus
from app.simulation.models import RunFinding, SimulationRun, SimulationYearly

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


def _render_run_pdf(habitation_name: str, run: SimulationRun, rows: list[dict[str, Any]], findings: list[RunFinding]) -> bytes:
    esc = html.escape
    findings_html = "".join(
        f"<tr><td>{esc(f.code)}</td><td>{esc(f.severity.value)}</td><td>{esc(f.message)}</td></tr>" for f in findings
    )
    header = "".join(f"<th>{esc(str(key))}</th>" for key in (rows[0].keys() if rows else []))
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(str(value))}</td>" for value in row.values()) + "</tr>" for row in rows
    )
    document = f"""
    <html><head><style>
      body {{ font-family: sans-serif; font-size: 10px; }}
      h1 {{ font-size: 18px; }} h2 {{ font-size: 14px; margin-top: 20px; }}
      table {{ border-collapse: collapse; width: 100%; }}
      th, td {{ border: 1px solid #ccc; padding: 3px 6px; text-align: right; }}
      th {{ background: #eee; }}
    </style></head><body>
      <h1>{esc(habitation_name)} — Simulation Report</h1>
      <p>Run: {esc(run.label or str(run.id))} · Type: {esc(run.run_type.value)} · Horizon: {run.horizon_years} years</p>
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
            data, content_type, ext = _render_run_pdf(habitation.name, run, rows, findings), "application/pdf", "pdf"
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
    return storage.get_presigned_url(report.storage_key, REPORT_EXPIRY_SECONDS)
