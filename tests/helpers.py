"""Shared helpers for building CSV payloads in tests."""

from __future__ import annotations

import csv
import io

HEADER = ["employee_id", "employee_name", "email", "manager_id", "manager_email", "department"]


def make_csv(
    rows: list[list[str | None]],
    header: list[str] | None = None,
    encoding: str = "utf-8",
) -> bytes:
    """Build CSV file bytes from raw cell values (None becomes an empty cell)."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(header if header is not None else HEADER)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    return buf.getvalue().encode(encoding)


def employee_ids(employees) -> list[str]:
    return [employee.employee_id for employee in employees]


def error_types(errors) -> set:
    return {error.error_type for error in errors}
