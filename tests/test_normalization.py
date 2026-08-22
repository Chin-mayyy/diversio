"""Normalization rules: trimming, email lowercasing, case-sensitive IDs."""

from __future__ import annotations

from app.services import build_import_preview, normalize_email, normalize_optional

from helpers import employee_ids, make_csv


def test_whitespace_is_trimmed_from_every_value():
    preview = build_import_preview(
        make_csv(
            [
                ["  DIV-1  ", "  Ada Lovelace ", "  ADA@X.IO ", "   ", "", "  Engineering  "],
                [" DIV-2 ", "Bob", "bob@x.io", "  DIV-1  ", "", ""],
            ]
        )
    )

    assert preview.identity_errors == []
    assert employee_ids(preview.accepted_employees) == ["DIV-1", "DIV-2"]

    ada = preview.accepted_employees[0]
    assert ada.employee_id == "DIV-1"  # ID trimmed but case preserved
    assert ada.name == "Ada Lovelace"
    assert ada.email == "ada@x.io"  # lowercased
    assert ada.department == "Engineering"

    # Whitespace-only manager_id counts as blank: DIV-1 is a root.
    assert employee_ids(preview.roots) == ["DIV-1"]
    # Padded manager_id still resolves.
    assert preview.direct_reports[0].reports[0].employee_id == "DIV-2"
    assert preview.manager_errors == []


def test_emails_are_normalized_to_lowercase():
    preview = build_import_preview(
        make_csv(
            [
                ["E-1", "Boss", "Boss@Example.COM", "", "", "Ops"],
                ["E-2", "Report", "REPORT@x.io", "", "Boss@example.com", "Ops"],
            ]
        )
    )

    assert employee_ids(preview.accepted_employees) == ["E-1", "E-2"]
    # Manager email lookup works despite mixed case on both sides.
    assert employee_ids(preview.roots) == ["E-1"]
    entry = next(d for d in preview.direct_reports if d.manager.employee_id == "E-1")
    assert entry.count == 1
    assert employee_ids(entry.reports) == ["E-2"]
    assert preview.manager_errors == []


def test_employee_ids_are_case_sensitive_so_lookups_fail_across_case():
    preview = build_import_preview(
        make_csv(
            [
                ["DIV-1", "Ada", "ada@x.io", "", "", ""],
                ["DIV-2", "Bob", "bob@x.io", "div-1", "", ""],  # lowercase ref misses
            ]
        )
    )

    assert sorted(employee_ids(preview.accepted_employees)) == ["DIV-1", "DIV-2"]
    assert preview.identity_errors == []

    (error,) = preview.manager_errors
    assert error.error_type.value == "manager_not_found"
    assert "'div-1'" in error.message
    assert error.employee_id == "DIV-2"


def test_normalize_helpers():
    assert normalize_optional("  hello  ") == "hello"
    assert normalize_optional("   ") is None
    assert normalize_optional(None) is None
    assert normalize_email("  MiXeD@Case.IO ") == "mixed@case.io"
    assert normalize_email("   ") is None
