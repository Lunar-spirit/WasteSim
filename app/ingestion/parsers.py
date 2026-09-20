"""Stage 0 (structural) for a tabular PARAMETERS upload: turn CSV/XLSX/JSON
bytes into a flat list of (category, param_key, raw_value) rows, each
carrying the 1-based row number BR-18 wants reported back to the uploader.

Design decision this session had to make, spelled out because the design
document (as excerpted) never shows the exact column layout of a PARAMETERS
CSV: a parameter_set holds exactly one row per category — there is no
repeating sub-entity for a "row" of a habitation's demography to mean. The
reading that is actually consistent with row-by-row acceptance, per-row
issue numbers, and a habitation-scoped upload endpoint is a *long* format:
one row per (category, param_key, value) triple — the same shape
parameter_definitions itself already uses. A form with one line per field,
not a table with one line per habitation. JSON accepts the same triples as
a list, or the more natural nested {"category": {"param_key": value}}.

Required CSV/XLSX columns: category, param_key, value (case-insensitive).
"""

from __future__ import annotations

import io
import json as _json
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.ingestion.models import FileFormat

REQUIRED_COLUMNS = {"category", "param_key", "value"}


class ParseError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message


@dataclass
class ParsedRow:
    row_number: int
    category: str
    param_key: str
    raw_value: Any


def parse_rows(data: bytes, file_format: FileFormat) -> list[ParsedRow]:
    if file_format == FileFormat.CSV:
        try:
            df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)
        except Exception as exc:  # pandas raises several different error types on a corrupt file
            raise ParseError(f"could not read CSV: {exc}") from exc
        return _rows_from_dataframe(df)

    if file_format == FileFormat.XLSX:
        try:
            df = pd.read_excel(io.BytesIO(data), dtype=str)
        except Exception as exc:
            raise ParseError(f"could not read XLSX: {exc}") from exc
        df = df.fillna("")
        return _rows_from_dataframe(df)

    if file_format == FileFormat.JSON:
        return _rows_from_json(data)

    raise ParseError(f"{file_format.value} is not a tabular PARAMETERS format")


def _rows_from_dataframe(df: pd.DataFrame) -> list[ParsedRow]:
    normalized_columns = {str(c).strip().lower() for c in df.columns}
    missing = REQUIRED_COLUMNS - normalized_columns
    if missing:
        raise ParseError(f"missing required column(s): {', '.join(sorted(missing))}")
    df.columns = [str(c).strip().lower() for c in df.columns]

    rows: list[ParsedRow] = []
    for i, record in enumerate(df.to_dict(orient="records"), start=1):
        rows.append(
            ParsedRow(
                row_number=i,
                category=str(record["category"]).strip().lower(),
                param_key=str(record["param_key"]).strip().lower(),
                raw_value=record["value"],
            )
        )
    return rows


def _rows_from_json(data: bytes) -> list[ParsedRow]:
    try:
        payload = _json.loads(data)
    except _json.JSONDecodeError as exc:
        raise ParseError(f"invalid JSON: {exc}") from exc

    rows: list[ParsedRow] = []

    if isinstance(payload, list):
        for i, record in enumerate(payload, start=1):
            if not isinstance(record, dict) or not REQUIRED_COLUMNS <= record.keys():
                raise ParseError(f"row {i}: expected an object with category, param_key, value")
            rows.append(
                ParsedRow(i, str(record["category"]).lower(), str(record["param_key"]).lower(), record["value"])
            )
        return rows

    if isinstance(payload, dict):
        i = 0
        for category, fields in payload.items():
            if not isinstance(fields, dict):
                raise ParseError(f"'{category}' must map param_key to value")
            for param_key, value in fields.items():
                i += 1
                rows.append(ParsedRow(i, str(category).lower(), str(param_key).lower(), value))
        return rows

    raise ParseError("JSON body must be a list of {category, param_key, value} rows, or a nested object")
