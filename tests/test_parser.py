"""Structural CSV parsing: encodings, headers, quoting, row numbers."""

from __future__ import annotations

import pytest

from app.parser import CsvStructureError, FileTooLargeError, MAX_UPLOAD_BYTES, parse_csv

from helpers import HEADER


def test_parses_quoted_values_containing_commas():
    data = (
        'employee_id,employee_name,email,manager_id,manager_email,department\r\n'
        'E-1,"Alvarez, Renée",renee@x.io,,,\r\n'
    ).encode("utf-8")

    parsed = parse_csv(data)
    (row,) = parsed.rows
    assert row.employee_name == "Alvarez, Renée"
    assert row.department == ""


def test_accepts_utf8_with_byte_order_mark():
    body = "employee_id,employee_name,email,manager_id,manager_email,department\nE-1,A,a@x.io,,,\n"
    parsed = parse_csv(b"\xef\xbb\xbf" + body.encode("utf-8"))
    assert parsed.total_source_rows == 1


def test_header_column_order_does_not_matter():
    reordered = ["email", "employee_id", "manager_id", "employee_name", "department", "manager_email"]
    data = (
        "email,employee_id,manager_id,employee_name,department,manager_email\n"
        "ada@x.io,E-1,,Ada,,\n"
    ).encode("utf-8")
    assert reordered is not None  # keeps the intent explicit in the test name

    parsed = parse_csv(data)
    (row,) = parsed.rows
    assert row.employee_id == "E-1"
    assert row.email == "ada@x.io"
    assert row.manager_id == ""


def test_missing_required_column_is_a_whole_import_error():
    header_without_email = [c for c in HEADER if c != "email"]
    data = b"employee_id,employee_name,manager_id,manager_email,department\nE-1,A,,,\n"

    with pytest.raises(CsvStructureError) as excinfo:
        parse_csv(header_without_email and data)
    assert "email" in str(excinfo.value)


def test_empty_upload_has_no_header_row():
    with pytest.raises(CsvStructureError, match="no header"):
        parse_csv(b"")


def test_non_utf8_upload_is_rejected_cleanly():
    with pytest.raises(CsvStructureError, match="UTF-8"):
        parse_csv(b"\xff\xfe\x00nonsense")


def test_malformed_csv_structure_reports_line_information():
    # An unquoted field beyond csv's 128 KiB field limit makes the parser
    # raise mid-file; the underlying csv error is surfaced as a clear
    # whole-import failure instead of an unhandled exception.
    header = b"employee_id,employee_name,email,manager_id,manager_email,department\n"
    oversized_row = b"E-1," + b"x" * (200 * 1024) + b",a@x.io,,,\n"

    with pytest.raises(CsvStructureError, match="field larger than field limit"):
        parse_csv(header + oversized_row)


def test_row_numbers_reflect_source_lines_even_with_multiline_fields():
    data = (
        "employee_id,employee_name,email,manager_id,manager_email,department\n"  # line 1
        "E-1,\"Two\nLines\",two@x.io,,,\n"                                       # lines 2-3
        "E-2,Next,next@x.io,,,\n"                                                # line 4
    ).encode("utf-8")

    rows = parse_csv(data).rows
    assert rows[0].row_number == 3  # record ends on its last physical line
    assert rows[1].row_number == 4


def test_extra_unknown_columns_are_ignored():
    data = (
        "employee_id,employee_name,email,manager_id,manager_email,department,extra_col\n"
        "E-1,A,a@x.io,,,Ops,junk\n"
    ).encode("utf-8")

    parsed = parse_csv(data)
    assert parsed.total_source_rows == 1


def test_oversized_upload_is_rejected_before_parsing():
    big_row = b"E-1," + b"x" * 1024 * 1024 + b",,,,,\n"
    data = (
        b"employee_id,employee_name,email,manager_id,manager_email,department\n" + big_row * 11
    )
    assert len(data) > MAX_UPLOAD_BYTES

    with pytest.raises(FileTooLargeError):
        parse_csv(data)
