"""Writing verified Voice Lab results as a CSV or Excel file (roadmap 12.6).

Pure functions: the service gathers the rows, these turn them into bytes. One row per report,
one column per field (the newest version's order first, then fields only older versions had),
after the report number, analyst, time received and supervisor. Media fields are left out:
a file in a cell means nothing to a spreadsheet or a LIS import.
"""

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from openpyxl import Workbook

from app.modules.forms.schemas import FieldDefinition, FormDefinition

ExportFormat = Literal["csv", "xlsx"]

MEDIA_TYPES: dict[ExportFormat, str] = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_SKIP_TYPES = {"photo", "video", "voice", "document", "signature"}
_HEADERS = ["Nomor", "Analis", "Diterima", "Diverifikasi oleh", "Waktu verifikasi"]

Cell = str | Decimal | datetime | None


@dataclass(frozen=True)
class ExportRow:
    code: str
    analyst: str
    received_at: datetime  # already in the workspace's timezone
    verified_by: str | None
    verified_at: datetime | None
    answers: dict[str, Any]


def columns(definitions: list[FormDefinition]) -> list[FieldDefinition]:
    """Fields to export, newest definition first; a key keeps its first (newest) label."""
    seen: set[str] = set()
    out: list[FieldDefinition] = []
    for definition in definitions:
        for f in definition.fields:
            if f.type in _SKIP_TYPES or f.key in seen:
                continue
            seen.add(f.key)
            out.append(f)
    return out


def header(f: FieldDefinition) -> str:
    return f"{f.label} ({f.unit})" if f.type == "number" and f.unit else f.label


def cell(f: FieldDefinition, value: Any) -> Cell:
    """A value as data: numbers stay numbers, choices read as their labels, skipped is empty."""
    if value is None or value == "" or value == []:
        return None
    if f.type == "number":
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return str(value)
    if f.type in ("single_choice", "multi_choice"):
        labels = {o.value: o.label for o in f.options}
        values = value if isinstance(value, list) else [value]
        return ", ".join(labels.get(v, str(v)) for v in values)
    if f.type == "location" and isinstance(value, dict):
        return f"{value.get('lat')}, {value.get('lng')}"
    return str(value)


def table(fields: list[FieldDefinition], rows: list[ExportRow]) -> list[list[Cell]]:
    out: list[list[Cell]] = [[*_HEADERS, *(header(f) for f in fields)]]
    for r in rows:
        meta: list[Cell] = [r.code, r.analyst, r.received_at, r.verified_by, r.verified_at]
        out.append([*meta, *(cell(f, r.answers.get(f.key)) for f in fields)])
    return out


def write(fmt: ExportFormat, cells: list[list[Cell]]) -> bytes:
    return _xlsx(cells) if fmt == "xlsx" else _csv(cells)


def _csv(cells: list[list[Cell]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in cells:
        writer.writerow([_text(c) for c in row])
    # The BOM lets Excel read the Indonesian text as UTF-8.
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def _text(value: Cell) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, Decimal):
        return f"{value.normalize():f}"
    return value


def _xlsx(cells: list[list[Cell]]) -> bytes:
    book = Workbook(write_only=True)
    sheet = book.create_sheet("Hasil Voice")
    for row in cells:
        sheet.append([_excel(c) for c in row])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _excel(value: Cell) -> str | float | datetime | None:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)  # Excel has no timezones; the value is local time.
    return value


def filename(form_name: str, day: datetime, fmt: ExportFormat) -> str:
    ascii_name = unicodedata.normalize("NFKD", form_name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:60] or "struktur"
    return f"voice-{slug}-{day:%Y%m%d}.{fmt}"
