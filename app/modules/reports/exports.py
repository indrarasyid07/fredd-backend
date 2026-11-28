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


# --- Report downloads (roadmap 5.4) -------------------------------------------------------------

_REPORT_HEADERS = ["Nomor", "Penyuluh", "Diterima", "Wilayah", "Lengkap", "Perlu ditinjau"]
_GPS_HEADERS = ["Lintang", "Bujur", "Akurasi GPS (m)"]
_SHEET_FORBIDDEN = re.compile(r"[\[\]:*?/\\]")


@dataclass(frozen=True)
class ReportSheetRow:
    """One report as a download row. No phone number of the worker, ever (dashboard.md)."""

    code: str
    worker: str
    received_at: datetime  # already in the workspace's timezone
    region: str | None
    complete: bool
    needs_review: bool
    lat: float | None
    lng: float | None
    accuracy_m: float | None
    photo_count: int
    answers: dict[str, Any]


def report_columns(definitions: list[FormDefinition], *, gps: bool) -> list[FieldDefinition]:
    """Like `columns`, and location answers go when coordinates are left out."""
    return [f for f in columns(definitions) if gps or f.type != "location"]


def _number(value: float | int | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def report_table(
    fields: list[FieldDefinition], rows: list[ReportSheetRow], *, gps: bool, photos: bool
) -> list[list[Cell]]:
    head: list[Cell] = [*_REPORT_HEADERS]
    if gps:
        head += _GPS_HEADERS
    if photos:
        head.append("Jumlah foto")
    out: list[list[Cell]] = [[*head, *(header(f) for f in fields)]]
    for r in rows:
        line: list[Cell] = [
            r.code,
            r.worker,
            r.received_at,
            r.region,
            "Ya" if r.complete else "Tidak",
            "Ya" if r.needs_review else "Tidak",
        ]
        if gps:
            line += [_number(r.lat), _number(r.lng), _number(r.accuracy_m)]
        if photos:
            line.append(_number(r.photo_count))
        out.append([*line, *(cell(f, r.answers.get(f.key)) for f in fields)])
    return out


def sheet_title(name: str, used: set[str]) -> str:
    """Excel sheet names: at most 31 characters, no `[]:*?/\\`, unique in the workbook."""
    base = _SHEET_FORBIDDEN.sub(" ", name).strip()[:31] or "Struktur"
    title, n = base, 2
    while title.lower() in used:
        suffix = f" ({n})"
        title, n = f"{base[: 31 - len(suffix)]}{suffix}", n + 1
    used.add(title.lower())
    return title


def write_sheets(sheets: list[tuple[str, list[list[Cell]]]]) -> bytes:
    """One sheet per structure; an empty download still has one sheet with the headers."""
    book = Workbook(write_only=True)
    for title, cells in sheets:
        sheet = book.create_sheet(title)
        for row in cells:
            sheet.append([_excel(c) for c in row])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def report_filename(scope: str | None, day: datetime, fmt: ExportFormat) -> str:
    ascii_name = unicodedata.normalize("NFKD", scope or "").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:60] or "semua"
    return f"laporan-{slug}-{day:%Y%m%d}.{fmt}"
