"""Structural CSV parsing: raw bytes -> decoded text -> header check -> rows.

This layer knows nothing about identity rules or hierarchy; it only answers
"which rows does this file contain, and where are they?" Fatal structural
problems (non-UTF-8 bytes, oversized uploads, missing headers, malformed CSV)
raise :class:`CsvStructureError` so callers can fail the whole import with a
clear message instead of an unhandled exception.
"""

from __future__ import annotations

import csv
import io

from pydantic import BaseModel

from .models import RawRow

#: The CSV contract: all six columns must be present (in any order).
REQUIRED_COLUMNS: tuple[str, ...] = (
    "employee_id",
    "employee_name",
    "email",
    "manager_id",
    "manager_email",
    "department",
)

#: Guard rail so a runaway upload cannot exhaust memory. The spec targets
#: files around 100k rows; 10 MiB comfortably covers that.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class CsvStructureError(Exception):
    """The file cannot be parsed as an HRIS CSV at all (whole-import failure)."""


class FileTooLargeError(CsvStructureError):
    """The upload exceeds ``MAX_UPLOAD_BYTES``."""


class ParsedCsv(BaseModel):
    rows: list[RawRow]

    @property
    def total_source_rows(self) -> int:
        return len(self.rows)


def parse_csv(data: bytes) -> ParsedCsv:
    """Parse uploaded bytes into raw rows.

    Raises:
        FileTooLargeError: if the upload is bigger than the size limit.
        CsvStructureError: for undecodable, empty, or structurally broken files.
    """
    return _parse_text(_decode(data))


def _decode(data: bytes) -> str:
    if len(data) > MAX_UPLOAD_BYTES:
        mib = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise FileTooLargeError(f"Uploaded file is larger than the {mib} MiB limit.")
    try:
        # "utf-8-sig" transparently strips a leading byte-order mark when
        # present and behaves like plain UTF-8 otherwise.
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvStructureError("File could not be decoded as UTF-8 text.") from exc


def _parse_text(text: str) -> ParsedCsv:
    reader = csv.DictReader(io.StringIO(text, newline=""))

    fieldnames = reader.fieldnames
    if fieldnames is None:
        raise CsvStructureError("CSV appears to be empty: no header row was found.")

    # Header matching is case-insensitive after stripping; this tolerates
    # exports whose headers carry stray whitespace or different casing.
    stripped_headers = [name.strip().lower() for name in fieldnames]
    missing = [col for col in REQUIRED_COLUMNS if col not in stripped_headers]
    if missing:
        raise CsvStructureError(
            "CSV is missing required column(s): " + ", ".join(missing) + "."
        )

    column_source = {
        col: next(name for name in fieldnames if name.strip().lower() == col)
        for col in REQUIRED_COLUMNS
    }

    rows: list[RawRow] = []
    try:
        for record in reader:
            # DictReader skips fully blank lines automatically.
            rows.append(
                RawRow(
                    row_number=reader.line_num,
                    **{
                        col: _cell(record.get(column_source[col]))
                        for col in REQUIRED_COLUMNS
                    },
                )
            )
    except csv.Error as exc:
        # Structural damage (e.g. NUL byte, unterminated quote): the remaining
        # file cannot be trusted, so the whole import fails with a clear,
        # locatable message rather than crashing.
        raise CsvStructureError(
            f"Malformed CSV near line {reader.line_num}: {exc}"
        ) from exc

    return ParsedCsv(rows=rows)


def _cell(value: object) -> str | None:
    """Pass a cell through untouched; DictReader yields None on short rows."""
    if value is None:
        return None
    return str(value)
