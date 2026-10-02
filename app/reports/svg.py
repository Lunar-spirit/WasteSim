"""Hand-built SVG chart rendering for the PDF/HTML report — no matplotlib/
seaborn (not in this project's approved stack, section 4 of CLAUDE.md).
WeasyPrint renders inline `<svg>` natively, so these functions just return
an SVG string to splice straight into the report's HTML template; nothing
here touches a file or a display backend.

Every function takes plain dicts/numbers (the same `rows` shape
app/reports/service.py already builds from simulation_yearly), not ORM
objects — consistent with how the rest of this module keeps rendering
logic free of persistence concerns.
"""

from __future__ import annotations

import math
from typing import Any

FONT = "font-family:Helvetica,Arial,sans-serif;"

COMPOSITION_COLOURS: dict[str, str] = {
    "organic": "#16a34a",
    "plastic": "#0ea5e9",
    "paper": "#f59e0b",
    "metal": "#64748b",
    "glass": "#06b6d4",
    "textile": "#a855f7",
    "inert": "#78716c",
    "ewaste": "#ef4444",
    "other": "#eab308",
}


def _empty_svg(width: int, height: int, message: str) -> str:
    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
        f'<text x="{width / 2}" y="{height / 2}" text-anchor="middle" style="{FONT}" '
        f'font-size="11" fill="#94a3b8">{message}</text></svg>'
    )


def trajectory_chart_svg(yearly: list[dict[str, Any]], findings: list[dict[str, Any]]) -> str:
    """Dual-axis line chart: Annual Waste Generated & cumulative Landfill
    Accumulation (left axis, tonnes) vs. Diversion Rate (right axis, %),
    with a dashed vertical marker at any LANDFILL_EXHAUSTION_YEAR /
    TREATMENT_SATURATION_YEAR finding."""
    width, height = 640, 300
    margin = {"top": 24, "right": 50, "bottom": 32, "left": 60}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    if not yearly:
        return _empty_svg(width, height, "No yearly results")

    years = [r["year_index"] for r in yearly]
    generated = [float(r["waste_total_tpy"]) for r in yearly]
    landfill_cum: list[float] = []
    running = 0.0
    for r in yearly:
        running += float(r["landfilled_tpy"])
        landfill_cum.append(running)
    diversion = [float(r["recovery_rate_pct"]) for r in yearly]

    max_tonnes = max([*generated, *landfill_cum, 1.0])
    n = len(years)

    def x(i: int) -> float:
        return margin["left"] + (i / max(n - 1, 1)) * plot_w

    def y_tonnes(v: float) -> float:
        return margin["top"] + plot_h - (v / max_tonnes) * plot_h

    def y_pct(v: float) -> float:
        return margin["top"] + plot_h - (v / 100) * plot_h

    def polyline(points: list[tuple[float, float]], colour: str) -> str:
        pts = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
        return f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="2" />'

    parts = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" style="{FONT}">']

    # Milestone markers, drawn first so the trend lines sit on top.
    for f in findings:
        if f.get("code") not in ("LANDFILL_EXHAUSTION_YEAR", "TREATMENT_SATURATION_YEAR"):
            continue
        year = f.get("year_index")
        if year is None or not (1 <= year <= n):
            continue
        colour = "#dc2626" if f["code"] == "LANDFILL_EXHAUSTION_YEAR" else "#f59e0b"
        px = x(year - 1)
        label = "Landfill exhausted" if f["code"] == "LANDFILL_EXHAUSTION_YEAR" else "Treatment saturated"
        parts.append(
            f'<line x1="{px:.1f}" y1="{margin["top"]}" x2="{px:.1f}" y2="{margin["top"] + plot_h}" '
            f'stroke="{colour}" stroke-width="1" stroke-dasharray="4,3" />'
            f'<text x="{px:.1f}" y="{margin["top"] - 6}" font-size="7" fill="{colour}" text-anchor="middle">{label}</text>'
        )

    # Axes.
    parts.append(
        f'<line x1="{margin["left"]}" y1="{margin["top"] + plot_h}" x2="{margin["left"] + plot_w}" '
        f'y2="{margin["top"] + plot_h}" stroke="#94a3b8" stroke-width="1" />'
    )
    tick_stride = max(1, n // 10)
    for i, year in enumerate(years):
        if i % tick_stride != 0 and i != n - 1:
            continue
        parts.append(
            f'<text x="{x(i):.1f}" y="{margin["top"] + plot_h + 14}" font-size="8" '
            f'text-anchor="middle" fill="#64748b">Y{year}</text>'
        )

    parts.append(polyline([(x(i), y_tonnes(v)) for i, v in enumerate(generated)], "#0ea5e9"))
    parts.append(polyline([(x(i), y_tonnes(v)) for i, v in enumerate(landfill_cum)], "#dc2626"))
    parts.append(polyline([(x(i), y_pct(v)) for i, v in enumerate(diversion)], "#16a34a"))

    legend_items = [("#0ea5e9", "Annual Waste Generated (t/yr)"), ("#dc2626", "Landfill Accumulation (cum. t)"), ("#16a34a", "Diversion Rate (%)")]
    lx = margin["left"]
    for colour, label in legend_items:
        parts.append(f'<rect x="{lx}" y="2" width="8" height="8" fill="{colour}" />')
        parts.append(f'<text x="{lx + 11}" y="10" font-size="8" fill="#334155">{label}</text>')
        lx += 18 + len(label) * 4.3

    parts.append("</svg>")
    return "".join(parts)


def composition_donut_svg(composition: dict[str, float]) -> str:
    """Donut of the 9 canonical waste fractions — `composition` is a
    fraction-name -> percentage dict (e.g. one month's organic_pct/
    plastic_pct/... from simulation_results, or a waste_baseline's own
    composition JSON)."""
    # The viewBox is noticeably bigger than the donut itself — labels sit
    # outside r_outer, and a slice near the 3/9 o'clock position needs real
    # margin for its text or it clips against the SVG's own edge (found by
    # actually rendering a PDF and reading it back: "organic 55%" got cut
    # down to "org").
    size = 340
    cx = cy = size / 2
    r_outer, r_inner = 95, 52

    total = sum(v for v in composition.values() if v and v > 0)
    if total <= 0:
        return _empty_svg(size, size, "No composition data")

    parts = [f'<svg viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg" style="{FONT}">']
    angle = -90.0
    for fraction, pct in composition.items():
        if not pct or pct <= 0:
            continue
        sweep = pct / total * 360.0
        parts.append(_donut_slice(cx, cy, r_outer, r_inner, angle, angle + sweep, COMPOSITION_COLOURS.get(fraction, "#94a3b8")))
        mid_rad = math.radians(angle + sweep / 2)
        lx = cx + (r_outer + 16) * math.cos(mid_rad)
        ly = cy + (r_outer + 16) * math.sin(mid_rad)
        anchor = "start" if math.cos(mid_rad) >= 0 else "end"
        parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="8" text-anchor="{anchor}" fill="#334155">{fraction} {pct:.0f}%</text>')
        angle += sweep
    parts.append("</svg>")
    return "".join(parts)


def _donut_slice(cx: float, cy: float, r_outer: float, r_inner: float, a0: float, a1: float, colour: str) -> str:
    a0r, a1r = math.radians(a0), math.radians(a1)
    large_arc = 1 if (a1 - a0) > 180 else 0
    x0o, y0o = cx + r_outer * math.cos(a0r), cy + r_outer * math.sin(a0r)
    x1o, y1o = cx + r_outer * math.cos(a1r), cy + r_outer * math.sin(a1r)
    x1i, y1i = cx + r_inner * math.cos(a1r), cy + r_inner * math.sin(a1r)
    x0i, y0i = cx + r_inner * math.cos(a0r), cy + r_inner * math.sin(a0r)
    d = (
        f"M {x0o:.2f},{y0o:.2f} "
        f"A {r_outer},{r_outer} 0 {large_arc} 1 {x1o:.2f},{y1o:.2f} "
        f"L {x1i:.2f},{y1i:.2f} "
        f"A {r_inner},{r_inner} 0 {large_arc} 0 {x0i:.2f},{y0i:.2f} Z"
    )
    return f'<path d="{d}" fill="{colour}" stroke="#ffffff" stroke-width="1.5" />'


def cost_curve_svg(yearly: list[dict[str, Any]]) -> str:
    """Cumulative Capex vs. Opex, as stacked bars per year (a stacked-area
    fill drawn as one polygon per series is harder to get right with hand-
    rolled SVG than a bar per year, and reads just as clearly for a yearly
    series)."""
    width, height = 640, 280
    margin = {"top": 24, "right": 20, "bottom": 32, "left": 80}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    if not yearly:
        return _empty_svg(width, height, "No budget data")

    n = len(yearly)
    capex_cum: list[float] = []
    opex_cum: list[float] = []
    rc = ro = 0.0
    for r in yearly:
        rc += float(r["capex_inr"])
        ro += float(r["opex_inr"])
        capex_cum.append(rc)
        opex_cum.append(ro)
    totals = [c + o for c, o in zip(capex_cum, opex_cum, strict=True)]
    max_total = max([*totals, 1.0])

    gap = plot_w / n
    bar_w = gap * 0.65
    base_y = margin["top"] + plot_h

    parts = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" style="{FONT}">']
    parts.append(f'<line x1="{margin["left"]}" y1="{base_y}" x2="{margin["left"] + plot_w}" y2="{base_y}" stroke="#94a3b8" />')

    tick_stride = max(1, n // 10)
    for i, row in enumerate(yearly):
        bx = margin["left"] + i * gap + (gap - bar_w) / 2
        capex_h = capex_cum[i] / max_total * plot_h
        opex_h = opex_cum[i] / max_total * plot_h
        parts.append(f'<rect x="{bx:.1f}" y="{base_y - capex_h:.1f}" width="{bar_w:.1f}" height="{capex_h:.1f}" fill="#0ea5e9" />')
        parts.append(
            f'<rect x="{bx:.1f}" y="{base_y - capex_h - opex_h:.1f}" width="{bar_w:.1f}" height="{opex_h:.1f}" fill="#f59e0b" />'
        )
        if i % tick_stride == 0 or i == n - 1:
            parts.append(
                f'<text x="{bx + bar_w / 2:.1f}" y="{base_y + 14}" font-size="8" text-anchor="middle" fill="#64748b">Y{row["year_index"]}</text>'
            )

    legend_items = [("#0ea5e9", "Cumulative Capex"), ("#f59e0b", "Cumulative Opex")]
    lx = margin["left"]
    for colour, label in legend_items:
        parts.append(f'<rect x="{lx}" y="2" width="8" height="8" fill="{colour}" />')
        parts.append(f'<text x="{lx + 11}" y="10" font-size="8" fill="#334155">{label}</text>')
        lx += 18 + len(label) * 4.3

    parts.append("</svg>")
    return "".join(parts)


def masked_chart_svg(width: int, height: int, message: str = "Restricted to Researcher accounts and above") -> str:
    """VIEWER-role placeholder in place of the financial cost curve —
    mirrors the frontend's own Lock-icon masking (SimulationPage's
    BudgetTab, ReportCharts' FinancialOverviewChart) rather than a blank
    gap in the PDF."""
    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" style="{FONT}">'
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#f8fafc" stroke="#e2e8f0" />'
        f'<text x="{width / 2}" y="{height / 2 - 6}" text-anchor="middle" font-size="12" fill="#94a3b8">🔒 Researcher Access Required</text>'
        f'<text x="{width / 2}" y="{height / 2 + 12}" text-anchor="middle" font-size="9" fill="#cbd5e1">{message}</text>'
        f"</svg>"
    )
