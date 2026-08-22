"""Cycle detection: exact membership, downstream exclusion, self-loops."""

from __future__ import annotations

from app.services import build_import_preview, detect_cycles

from helpers import employee_ids, make_csv


def test_detect_cycles_marks_only_nodes_on_the_cycle():
    # A -> B -> C -> A forms the cycle; D merely reports into it.
    manager_of = {"A": "B", "B": "C", "C": "A", "D": "A"}
    assert detect_cycles(manager_of) == {"A", "B", "C"}


def test_detect_cycles_handles_multiple_independent_cycles():
    manager_of = {
        "A": "B", "B": "A",            # cycle 1
        "X": "Y", "Y": "Z", "Z": "X",  # cycle 2
        "R": None,                     # plain root
        "S": "R",                      # plain chain into the root
    }
    assert detect_cycles(manager_of) == {"A", "B", "X", "Y", "Z"}


def test_detect_cycles_self_loop():
    assert detect_cycles({"A": "A"}) == {"A"}


def test_detect_cycles_empty_graph():
    assert detect_cycles({}) == set()


def test_simple_reporting_cycle_through_import_pipeline():
    preview = build_import_preview(
        make_csv(
            [
                ["A", "Ada", "a@x.io", "C", "", ""],
                ["B", "Bob", "b@x.io", "A", "", ""],
                ["C", "Cara", "c@x.io", "B", "", ""],
            ]
        )
    )

    assert sorted(employee_ids(preview.cyclic_employees)) == ["A", "B", "C"]
    assert preview.accepted_count == 3
    # Cycle members still count as managers/reports in the adjacency data.
    counts = {(e.manager.employee_id, e.count) for e in preview.direct_reports}
    assert ("A", 1) in counts and ("B", 1) in counts and ("C", 1) in counts


def test_downstream_employee_reaching_a_cycle_is_not_marked_cyclic():
    preview = build_import_preview(
        make_csv(
            [
                ["D", "Dora", "d@x.io", "A", "", ""],  # leads INTO the cycle
                ["A", "Ada", "a@x.io", "C", "", ""],
                ["B", "Bob", "b@x.io", "A", "", ""],
                ["C", "Cara", "c@x.io", "B", "", ""],
            ]
        )
    )

    assert sorted(employee_ids(preview.cyclic_employees)) == ["A", "B", "C"]

    # D is a fully valid employee with a resolved relationship.
    assert employee_ids(preview.accepted_employees) == ["A", "B", "C", "D"]
    entry = next(e for e in preview.direct_reports if e.manager.employee_id == "A")
    # B and D both report directly to A; D is the downstream-only employee.
    assert set(employee_ids(entry.reports)) == {"B", "D"}


def test_two_disconnected_components_with_and_without_cycle():
    preview = build_import_preview(
        make_csv(
            [
                # Component 1: cycle of two.
                ["A", "Ada", "a@x.io", "B", "", ""],
                ["B", "Bob", "b@x.io", "A", "", ""],
                # Component 2: plain chain with its own root.
                ["R", "Root", "r@x.io", "", "", ""],
                ["S", "Sub", "s@x.io", "R", "", ""],
            ]
        )
    )

    assert sorted(employee_ids(preview.cyclic_employees)) == ["A", "B"]
    assert employee_ids(preview.roots) == ["R"]
