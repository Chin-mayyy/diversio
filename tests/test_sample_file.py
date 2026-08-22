"""End-to-end pipeline behavior against the supplied sample_hris.csv."""

import pathlib

from app.services import build_import_preview

from helpers import employee_ids

SAMPLE = (pathlib.Path(__file__).resolve().parents[1] / "sample_hris.csv").read_bytes()


def test_sample_file_totals_and_identity():
    preview = build_import_preview(SAMPLE)

    assert preview.total_source_rows == 25
    assert preview.accepted_count == 25
    assert preview.identity_errors == []


def test_sample_file_manager_errors():
    preview = build_import_preview(SAMPLE)

    problems = {e.employee_id: e.error_type.value for e in preview.manager_errors}
    assert set(problems) == {"DIV-1600", "DIV-1601"}
    assert problems["DIV-1600"] == "manager_not_found"   # Casey Bell -> DIV-9999
    assert problems["DIV-1601"] == "manager_conflict"    # Riley Cooper: DIV-1100 vs mateo.rivera


def test_sample_file_roots():
    preview = build_import_preview(SAMPLE)

    roots = employee_ids(preview.roots)
    assert roots == ["DIV-1001"]
    assert preview.roots[0].name == "Avery Morgan"


def test_sample_file_direct_report_counts():
    preview = build_import_preview(SAMPLE)

    counts = {(e.manager.employee_id, e.count) for e in preview.direct_reports}
    assert ("DIV-1001", 4) in counts  # Avery Morgan
    assert ("DIV-1400", 3) in counts  # Lena Okafor
    assert ("DIV-1110", 3) in counts  # Sofia Chen
    assert sum(count for _, count in counts) == 22  # 25 rows - 1 root - 2 manager errors


def test_sample_file_cycle_members():
    preview = build_import_preview(SAMPLE)

    # Alex Romero -> Taylor Brooks -> Morgan Ellis -> back to Alex Romero.
    assert employee_ids(preview.cyclic_employees) == ["DIV-1701", "DIV-1702", "DIV-1703"]


def test_sample_file_normalization_applied_to_emails_and_quoted_names():
    preview = build_import_preview(SAMPLE)

    renee = next(e for e in preview.accepted_employees if e.employee_id == "DIV-1412")
    assert renee.name == "Alvarez, Renée"  # comma survived CSV quoting
    assert renee.email == "demo.renee.alvarez@diversio.com"
    # Uppercase manager email normalized and resolved to the same person as DIV-1400.
    entry = next(e for e in preview.direct_reports if e.manager.employee_id == "DIV-1400")
    assert any(r.employee_id == "DIV-1412" for r in entry.reports)
