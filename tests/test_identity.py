"""Employee identity rules: required fields and duplicate detection."""

from __future__ import annotations

from app.models import IssueType
from app.services import build_import_preview

from helpers import employee_ids, error_types, make_csv


def test_valid_csv_produces_accepted_employees_without_errors():
    preview = build_import_preview(
        make_csv(
            [
                ["E-1", "Ada", "ada@x.io", "", "", "Eng"],
                ["E-2", "Bob", "bob@x.io", "E-1", "", "Eng"],
            ]
        )
    )

    assert preview.total_source_rows == 2
    assert preview.accepted_count == 2
    assert preview.identity_errors == []
    assert preview.manager_errors == []


def test_missing_employee_id_invalidates_only_that_row():
    preview = build_import_preview(
        make_csv(
            [
                ["", "No Id", "noid@x.io", "", "", ""],
                ["E-1", "Ok", "ok@x.io", "", "", ""],
            ]
        )
    )

    assert preview.total_source_rows == 2
    assert employee_ids(preview.accepted_employees) == ["E-1"]

    (error,) = preview.identity_errors
    assert error.error_type is IssueType.MISSING_EMPLOYEE_ID
    assert error.row_number == 2  # header is row 1


def test_missing_email_invalidates_only_that_row():
    preview = build_import_preview(
        make_csv(
            [
                ["E-1", "No Email", "", "", "", ""],
                ["E-2", "Ok", "ok@x.io", "E-1", "", ""],
            ]
        )
    )

    assert employee_ids(preview.accepted_employees) == ["E-2"]
    (error,) = preview.identity_errors
    assert error.error_type is IssueType.MISSING_EMAIL
    assert error.row_number == 2


def test_duplicate_employee_ids_invalidate_every_involved_row():
    preview = build_import_preview(
        make_csv(
            [
                ["D-1", "First", "first@x.io", "", "", ""],
                ["D-2", "Unaffected", "unaffected@x.io", "", "", ""],
                ["D-1", "Second", "second@x.io", "", "", ""],
            ]
        )
    )

    # Both rows sharing the ID are rejected; the unrelated row survives.
    assert employee_ids(preview.accepted_employees) == ["D-2"]

    dup_errors = [e for e in preview.identity_errors if e.error_type is IssueType.DUPLICATE_EMPLOYEE_ID]
    assert sorted(e.row_number for e in dup_errors) == [2, 4]
    for error in dup_errors:
        assert "D-1" in error.message


def test_duplicate_emails_after_lowercasing_invalidate_every_involved_row():
    preview = build_import_preview(
        make_csv(
            [
                ["A-1", "One", "shared@x.io", "", "", ""],
                ["A-2", "Two", "SHARED@x.io", "", "", ""],
                ["A-3", "Three", "Shared@X.io ", "", "", ""],
            ]
        )
    )

    assert preview.accepted_employees == []
    assert set(error_types(preview.identity_errors)) == {IssueType.DUPLICATE_EMAIL}
    assert sorted(e.row_number for e in preview.identity_errors) == [2, 3, 4]


def test_duplicate_ids_are_detected_per_exact_case():
    preview = build_import_preview(
        make_csv(
            [
                ["ID-1", "Upper", "upper@x.io", "", "", ""],
                ["id-1", "Lower", "lower@x.io", "", "", ""],
            ]
        )
    )

    # Different case => different employee_id => both accepted.
    assert preview.accepted_count == 2
    assert preview.identity_errors == []


def test_identity_error_rows_are_excluded_from_manager_lookup_and_hierarchy():
    preview = build_import_preview(
        make_csv(
            [
                ["GHOST-1", "One", "one@x.io", "", "", ""],
                ["GHOST-1", "Two", "two@x.io", "", "", ""],  # duplicate pair
                ["E-9", "Reporter", "rep@x.io", "GHOST-1", "", ""],
            ]
        )
    )

    # The duplicated rows are invalid identities, so they are not in the
    # employee index: the reference from E-9 cannot resolve.
    assert employee_ids(preview.accepted_employees) == ["E-9"]
    assert preview.roots == []  # has a (broken) manager ref, so not a root

    types = {e.error_type for e in preview.identity_errors}
    assert types == {IssueType.DUPLICATE_EMPLOYEE_ID}
    (manager_error,) = preview.manager_errors
    assert manager_error.error_type.value == "manager_not_found"
    assert preview.direct_reports == []
