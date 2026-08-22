"""Manager reference resolution: by ID, by email, both, missing, conflicts."""

from __future__ import annotations

from app.models import IssueType
from app.services import build_import_preview

from helpers import employee_ids, make_csv


def test_blank_manager_fields_make_a_root():
    preview = build_import_preview(
        make_csv([["E-1", "Ada", "ada@x.io", "", "", "Eng"]])
    )

    assert employee_ids(preview.roots) == ["E-1"]
    assert preview.manager_errors == []
    assert preview.direct_reports == []


def test_manager_lookup_by_id_when_manager_row_appears_later():
    preview = build_import_preview(
        make_csv(
            [
                ["E-2", "Report", "report@x.io", "E-1", "", ""],
                ["E-1", "Boss", "boss@x.io", "", "", ""],  # manager comes after
                ["E-3", "Second Report", "sr@x.io", "E-1", "", ""],
            ]
        )
    )

    assert employee_ids(preview.roots) == ["E-1"]
    entry = next(d for d in preview.direct_reports if d.manager.employee_id == "E-1")
    assert employee_ids(entry.reports) == ["E-2", "E-3"]
    assert entry.count == 2
    assert preview.manager_errors == []


def test_manager_lookup_by_email_only():
    preview = build_import_preview(
        make_csv(
            [
                ["E-2", "Report", "report@x.io", "", "BOSS@x.io", ""],
                ["E-1", "Boss", "boss@x.io", "", "", ""],
            ]
        )
    )

    assert employee_ids(preview.roots) == ["E-1"]
    (entry,) = preview.direct_reports
    assert entry.manager.employee_id == "E-1"
    assert employee_ids(entry.reports) == ["E-2"]


def test_manager_id_and_email_supplied_and_agreeing_resolve_to_one_relationship():
    preview = build_import_preview(
        make_csv(
            [
                ["E-1", "Boss", "boss@x.io", "", "", ""],
                ["E-2", "Report", "report@x.io", "E-1", "boss@x.io", ""],
            ]
        )
    )

    assert preview.manager_errors == []
    (entry,) = preview.direct_reports
    assert entry.count == 1
    assert employee_ids(preview.roots) == ["E-1"]


def test_manager_id_and_email_disagreeing_is_reported_and_relationship_dropped():
    preview = build_import_preview(
        make_csv(
            [
                ["E-1", "Boss", "boss@x.io", "", "", ""],
                ["E-3", "Other", "other@x.io", "", "", ""],
                ["E-2", "Confused", "confused@x.io", "E-1", "other@x.io", ""],
            ]
        )
    )

    # Employee stays accepted...
    assert employee_ids(preview.accepted_employees) == ["E-1", "E-2", "E-3"]

    (error,) = preview.manager_errors
    assert error.error_type is IssueType.MANAGER_CONFLICT
    assert error.employee_id == "E-2"
    assert error.row_number == 4
    assert "E-1" in error.message and "other@x.io" in error.message

    # E-2 is not a root; the genuine roots (blank manager fields) are unaffected.
    assert employee_ids(preview.roots) == ["E-1", "E-3"]
    assert all(e.manager.employee_id != "E-2" for e in preview.direct_reports)
    assert preview.direct_reports == []


def test_unknown_manager_id_keeps_employee_but_drops_relationship():
    preview = build_import_preview(
        make_csv([["E-1", "Orphan", "orphan@x.io", "GHOST", "", "Ops"]])
    )

    assert employee_ids(preview.accepted_employees) == ["E-1"]

    (error,) = preview.manager_errors
    assert error.error_type.value == "manager_not_found"
    assert "'GHOST'" in error.message
    assert preview.roots == []  # not a root: it *tried* to name a manager
    assert preview.direct_reports == []


def test_unknown_manager_email_keeps_employee_but_drops_relationship():
    preview = build_import_preview(
        make_csv([["E-1", "Orphan", "orphan@x.io", "", "ghost@x.io", "Ops"]])
    )

    assert employee_ids(preview.accepted_employees) == ["E-1"]
    (error,) = preview.manager_errors
    assert "'ghost@x.io'" in error.message
    assert preview.roots == []


def test_employee_managing_themselves_is_an_error():
    by_id = build_import_preview(
        make_csv([["E-1", "Self", "self@x.io", "E-1", "", ""]])
    )
    (error,) = by_id.manager_errors
    assert error.error_type is IssueType.SELF_MANAGED
    assert by_id.accepted_count == 1
    assert by_id.roots == []

    by_email = build_import_preview(
        make_csv([["E-1", "Self", "self@x.io", "", "SELF@x.IO", ""]])
    )
    (error,) = by_email.manager_errors
    assert error.error_type is IssueType.SELF_MANAGED


def test_manager_reference_pointing_at_invalid_identity_row_does_not_resolve():
    # E-2's email is duplicated with E-3, so neither identity survives; the
    # email-based reference from E-1 must therefore fail.
    preview = build_import_preview(
        make_csv(
            [
                ["E-1", "Reporter", "r@x.io", "", "dupe@x.io", ""],
                ["E-2", "Dup A", "dupe@x.io", "", "", ""],
                ["E-3", "Dup B", "DUPE@x.io", "", "", ""],
            ]
        )
    )

    assert employee_ids(preview.accepted_employees) == ["E-1"]
    (error,) = preview.manager_errors
    assert error.error_type.value == "manager_not_found"
