"""Hierarchy analysis: roots, adjacency, and direct-report counts."""

from __future__ import annotations

from app.services import build_import_preview

from helpers import employee_ids, make_csv


def _org_chart() -> bytes:
    #  R
    #  |-- M1 --> L1, L2, L3
    #  |-- M2
    return make_csv(
        [
            ["R", "Root", "root@x.io", "", "", "Exec"],
            ["M1", "Manager One", "m1@x.io", "R", "", "Eng"],
            ["M2", "Manager Two", "m2@x.io", "R", "", "Eng"],
            ["L1", "Leaf One", "l1@x.io", "M1", "", "Eng"],
            ["L2", "Leaf Two", "l2@x.io", "M1", "", "Eng"],
            ["L3", "Leaf Three", "l3@x.io", "M1", "", "Eng"],
        ]
    )


def test_multiple_roots_are_listed_sorted():
    preview = build_import_preview(
        make_csv(
            [
                ["B-ROOT", "Beta", "beta@x.io", "", "", ""],
                ["A-ROOT", "Alpha", "alpha@x.io", "", "", ""],
                ["CHILD", "Child", "child@x.io", "B-ROOT", "", ""],
            ]
        )
    )

    assert employee_ids(preview.roots) == ["A-ROOT", "B-ROOT"]


def test_direct_report_counts_are_correct_and_sorted_descending():
    preview = build_import_preview(_org_chart())

    counts = [(entry.manager.employee_id, entry.count) for entry in preview.direct_reports]
    assert counts == [("M1", 3), ("R", 2)]

    by_manager = {entry.manager.employee_id: entry for entry in preview.direct_reports}
    assert employee_ids(by_manager["R"].reports) == ["M1", "M2"]
    assert employee_ids(by_manager["M1"].reports) == ["L1", "L2", "L3"]


def test_employees_without_relationships_do_not_appear_in_direct_report_table():
    preview = build_import_preview(_org_chart())

    manager_ids = {entry.manager.employee_id for entry in preview.direct_reports}
    # Leaves manage nobody; they never show up as managers.
    assert "L1" not in manager_ids and "L2" not in manager_ids and "L3" not in manager_ids


def test_employee_with_unresolved_manager_is_neither_root_nor_related():
    preview = build_import_preview(
        make_csv(
            [
                ["R", "Root", "root@x.io", "", "", ""],
                ["X", "Orphan", "orphan@x.io", "MISSING", "", ""],
            ]
        )
    )

    assert preview.accepted_count == 2
    assert employee_ids(preview.roots) == ["R"]
    assert [(entry.manager.employee_id, entry.count) for entry in preview.direct_reports] == []
