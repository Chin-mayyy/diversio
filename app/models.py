"""Domain models for the HRIS import preview.

Nothing in this module imports FastAPI, request objects, or template
machinery, so the whole import pipeline (parsing -> validation -> hierarchy)
can be driven directly from plain pytest tests.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class IssueType(str, Enum):
    """Machine-readable categories for row-level problems.

    ``MISSING_*`` / ``DUPLICATE_*`` issues invalidate a row's *identity*;
    ``MANAGER_*`` issues invalidate only the reporting relationship while the
    employee itself stays accepted.
    """

    MISSING_EMPLOYEE_ID = "missing_employee_id"
    MISSING_EMAIL = "missing_email"
    DUPLICATE_EMPLOYEE_ID = "duplicate_employee_id"
    DUPLICATE_EMAIL = "duplicate_email"
    MANAGER_NOT_FOUND = "manager_not_found"
    MANAGER_CONFLICT = "manager_conflict"
    SELF_MANAGED = "self_managed"


class RawRow(BaseModel):
    """One CSV data row straight from the parser, before normalization."""

    # Physical line number of the record in the uploaded file; the header is
    # line 1, so the first data row is normally line 2.
    row_number: int
    employee_id: str | None = None
    employee_name: str | None = None
    email: str | None = None
    manager_id: str | None = None
    manager_email: str | None = None
    department: str | None = None


class ParsedRow(BaseModel):
    """One CSV data row after normalization.

    Optional reference fields are ``None`` when the cell was blank (or only
    whitespace) after trimming.
    """

    row_number: int
    employee_id: str | None
    employee_name: str = ""
    email: str | None
    manager_id: str | None = None
    manager_email: str | None = None
    department: str = ""


class Employee(BaseModel):
    """An accepted employee record together with its manager references.

    ``manager_id`` / ``manager_email`` are the normalized references as
    supplied in the CSV; whether they actually resolve to another employee is
    determined later by :func:`app.services.resolve_managers`.
    """

    employee_id: str  # case-sensitive
    name: str = ""
    email: str  # lowercased during normalization
    department: str = ""
    manager_id: str | None = None
    manager_email: str | None = None
    source_row: int  # CSV line the record came from


class RowError(BaseModel):
    """A row-level validation problem, traceable to its source CSV line."""

    row_number: int
    error_type: IssueType
    message: str
    employee_id: str | None = None
    email: str | None = None


class ManagerDirectReports(BaseModel):
    """A manager together with the employees reporting directly to them."""

    manager: Employee
    count: int
    reports: list[Employee]


class ImportPreview(BaseModel):
    """Full result of analyzing one uploaded HRIS CSV."""

    total_source_rows: int
    accepted_employees: list[Employee]
    identity_errors: list[RowError]
    manager_errors: list[RowError]
    roots: list[Employee]
    direct_reports: list[ManagerDirectReports]
    cyclic_employees: list[Employee]

    @property
    def accepted_count(self) -> int:
        return len(self.accepted_employees)

    @property
    def error_count(self) -> int:
        return len(self.identity_errors) + len(self.manager_errors)

    @property
    def has_problems(self) -> bool:
        return self.error_count > 0
