"""Pure-Python SVG rendering for the PDF report. WeasyPrint renders static
HTML/CSS to PDF and never executes JavaScript, so the Recharts components
the live app uses can't be reused here — these are plain <svg> markup
strings WeasyPrint embeds directly, with no extra dependency (matplotlib
isn't in the approved stack; this is small enough not to need it).
"""

from __future__ import annotations

CHART_WIDTH = 560
CHART_HEIGHT = 200
_PAD_LEFT = 55
_PAD_RIGHT = 15
_PAD_TOP = 12
_PAD_BOTTOM = 26
_PLOT_W = CHART_WIDTH - _PAD_LEFT - _PAD_RIGHT
_PLOT_H = CHART_HEIGHT - _PAD_TOP - _PAD_BOTTOM


def _lerp(values: list[float], lo: float, hi: float, out_lo: float, out_hi: float) -> list[float]:
    if hi == lo:
        return [(out_lo + out_hi) / 2 for _ in values]
    return [out_lo + (v - lo) / (hi - lo) * (out_hi - out_lo) for v in values]


def _x_positions(n: int) -> list[float]:
    if n <= 1:
        return [_PAD_LEFT + _PLOT_W / 2] * n
    return _lerp(list(range(n)), 0, n - 1, _PAD_LEFT, _PAD_LEFT + _PLOT_W)


def _axes_and_gridlines(y_lo: float, y_hi: float, y_format) -> list[str]:
    parts = [
        f'<line x1="{_PAD_LEFT}" y1="{_PAD_TOP}" x2="{_PAD_LEFT}" y2="{_PAD_TOP + _PLOT_H}" stroke="#cbd5e1"/>',
        f'<line x1="{_PAD_LEFT}" y1="{_PAD_TOP + _PLOT_H}" x2="{_PAD_LEFT + _PLOT_W}" '
        f'y2="{_PAD_TOP + _PLOT_H}" stroke="#cbd5e1"/>',
    ]
    for frac in (0.0, 0.5, 1.0):
        y_val = y_lo + frac * (y_hi - y_lo)
        y_px = _PAD_TOP + _PLOT_H - frac * _PLOT_H
        parts.append(
            f'<text x="{_PAD_LEFT - 6}" y="{y_px + 3}" font-size="8" fill="#64748b" '
            f'text-anchor="end">{y_format(y_val)}</text>'
        )
        if frac > 0:
            parts.append(f'<line x1="{_PAD_LEFT}" y1="{y_px}" x2="{_PAD_LEFT + _PLOT_W}" y2="{y_px}" stroke="#f1f5f9"/>')
    return parts


def _x_labels(x_labels: list[int], xs: list[float]) -> list[str]:
    n = len(x_labels)
    if n == 0:
        return []
    indices = sorted({0, n // 2, n - 1})
    return [
        f'<text x="{xs[i]:.1f}" y="{CHART_HEIGHT - 8}" font-size="8" fill="#64748b" '
        f'text-anchor="middle">Yr {x_labels[i]}</text>'
        for i in indices
    ]


def line_chart(series: dict[str, list[float]], x_labels: list[int], colors: dict[str, str], y_format=lambda v: f"{v:,.0f}") -> str:
    """One self-contained <svg> line chart: every named series shares one
    x-axis (x_labels — year_index) and one y-axis scaled to their combined
    min/max. Legend is rendered separately as plain HTML by the caller."""
    all_values = [v for values in series.values() for v in values]
    if not all_values or not x_labels:
        return f'<svg width="{CHART_WIDTH}" height="{CHART_HEIGHT}"></svg>'

    y_lo, y_hi = min(0.0, min(all_values)), max(all_values)
    if y_hi == y_lo:
        y_hi = y_lo + 1
    xs = _x_positions(len(x_labels))

    parts = [
        f'<svg width="{CHART_WIDTH}" height="{CHART_HEIGHT}" viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}" '
        f'xmlns="http://www.w3.org/2000/svg">'
    ]
    parts += _axes_and_gridlines(y_lo, y_hi, y_format)
    parts += _x_labels(x_labels, xs)
    for name, values in series.items():
        color = colors.get(name, "#334155")
        ys = _lerp(values, y_lo, y_hi, _PAD_TOP + _PLOT_H, _PAD_TOP)
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys, strict=True))
        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/>')
    parts.append("</svg>")
    return "".join(parts)


def bar_chart(
    values: list[float],
    x_labels: list[int],
    y_format=lambda v: f"{v:,.0f}",
    bar_color: str = "#0ea5e9",
    highlight_index: int | None = None,
    highlight_color: str = "#ef4444",
) -> str:
    """One self-contained <svg> bar chart — used for the landfill lifespan
    countdown, with the exhaustion year (if any) drawn in highlight_color."""
    if not values or not x_labels:
        return f'<svg width="{CHART_WIDTH}" height="{CHART_HEIGHT}"></svg>'

    y_lo, y_hi = 0.0, max(values) if max(values) > 0 else 1.0
    xs = _x_positions(len(x_labels))
    bar_w = max(2.0, (_PLOT_W / len(values)) * 0.6)

    parts = [
        f'<svg width="{CHART_WIDTH}" height="{CHART_HEIGHT}" viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}" '
        f'xmlns="http://www.w3.org/2000/svg">'
    ]
    parts += _axes_and_gridlines(y_lo, y_hi, y_format)
    parts += _x_labels(x_labels, xs)
    tops = _lerp(values, y_lo, y_hi, _PAD_TOP + _PLOT_H, _PAD_TOP)
    for i, (x, top) in enumerate(zip(xs, tops, strict=True)):
        color = highlight_color if i == highlight_index else bar_color
        height = (_PAD_TOP + _PLOT_H) - top
        parts.append(f'<rect x="{x - bar_w / 2:.1f}" y="{top:.1f}" width="{bar_w:.1f}" height="{height:.1f}" fill="{color}"/>')
    parts.append("</svg>")
    return "".join(parts)


def boundary_outline(coordinates: list, bbox: list[float]) -> str:
    """A schematic vector outline of a MultiPolygon/Polygon's outer ring(s)
    — not a real basemap snapshot (no map tiles/headless browser in the
    approved stack), just the boundary shape itself, scaled into a small
    square SVG. Latitude increases upward but SVG y increases downward, so
    each y is flipped during projection."""
    size = 220
    pad = 10
    xmin, ymin, xmax, ymax = bbox
    span_x, span_y = max(xmax - xmin, 1e-9), max(ymax - ymin, 1e-9)
    scale = (size - 2 * pad) / max(span_x, span_y)

    def project(lon: float, lat: float) -> tuple[float, float]:
        x = pad + (lon - xmin) * scale
        y = pad + (ymax - lat) * scale  # flipped: north stays up
        return x, y

    # MultiPolygon: [[ [ [lon,lat], ... ] ]] (rings, polygons); Polygon has
    # one fewer nesting level — normalise to "list of polygons of rings".
    polygons = coordinates if isinstance(coordinates[0][0][0], list) else [coordinates]

    parts = [f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg">']
    for polygon in polygons:
        outer_ring = polygon[0]
        points = " ".join(f"{px:.1f},{py:.1f}" for px, py in (project(lon, lat) for lon, lat in outer_ring))
        parts.append(f'<polygon points="{points}" fill="#d1fae5" stroke="#10b981" stroke-width="1.5"/>')
    parts.append("</svg>")
    return "".join(parts)
