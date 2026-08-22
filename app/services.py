"""Import pipeline: normalization, identity validation, manager resolution,
hierarchy analysis, and cycle detection.

All functions here are pure: no FastAPI request objects, no templates, no I/O
beyond decoding the uploaded bytes. ``build_import_preview`` is the single
entry point and can be called directly from tests.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field

from .models import (
    Employee,
    ImportPreview,
    IssueType,
    ManagerDirectReports,
    ParsedRow,
    RawRow,
    RowError,
)
from .parser import parse_csv


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def normalize_optional(value: str | None) -> str | None:
    """Trim surrounding whitespace; collapse blank results to None."""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def normalize_email(value: str | None) -> str | None:
    """Emails are trimmed and lowercased; blank collapses to None."""
    trimmed = normalize_optional(value)
    return trimmed.lower() if trimmed is not None else None


def normalize_row(raw: RawRow) -> ParsedRow:
    """Apply the CSV contract's normalization rules to one raw row."""
    return ParsedRow(
        row_number=raw.row_number,
        employee_id=normalize_optional(raw.employee_id),  # case preserved
        employee_name=normalize_optional(raw.employee_name) or "",
        email=normalize_email(raw.email),
        manager_id=normalize_optional(raw.manager_id),  # case preserved
        manager_email=normalize_email(raw.manager_email),
        department=normalize_optional(raw.department) or "",
    )


# ---------------------------------------------------------------------------
# Identity validation
# ---------------------------------------------------------------------------


def validate_identity(rows: list[ParsedRow]) -> tuple[list[Employee], list[RowError]]:
    """Split normalized rows into accepted employees and identity errors.

    Rules:
      * ``employee_id`` and ``email`` are required;
      * each must be unique after normalization;
      * EVERY row sharing a duplicated id or email is invalid;
      * invalid rows never reach manager resolution or hierarchy analysis.
    """
    errors: list[RowError] = []
    candidates: list[ParsedRow] = []

    for row in rows:
        if row.employee_id is None:
            errors.append(
                _row_error(
                    row, IssueType.MISSING_EMPLOYEE_ID,
                    "Required field 'employee_id' is missing or blank.",
                )
            )
        elif row.email is None:
            errors.append(
                _row_error(
                    row, IssueType.MISSING_EMAIL,
                    "Required field 'email' is missing or blank.",
                )
            )
        else:
            candidates.append(row)

    duplicated_ids = {
        value
        for value, count in Counter(r.employee_id for r in candidates).items()
        if count > 1
    }
    duplicated_emails = {
        value
        for value, count in Counter(r.email for r in candidates).items()
        if count > 1
    }

    employees: list[Employee] = []
    for row in candidates:
        # Both checks are reported independently of each other; a row only
        # needs one reason to be excluded, so report the first that applies.
        assert row.employee_id is not None and row.email is not None  # narrowed above
        if row.employee_id in duplicated_ids:
            errors.append(
                _row_error(
                    row, IssueType.DUPLICATE_EMPLOYEE_ID,
                    f"employee_id '{row.employee_id}' appears on multiple rows;"
                    " every row sharing a duplicated employee_id is invalid.",
                )
            )
            continue
        if row.email in duplicated_emails:
            errors.append(
                _row_error(
                    row, IssueType.DUPLICATE_EMAIL,
                    f"email '{row.email}' appears on multiple rows after"
                    " normalization; every row sharing it is invalid.",
                )
            )
            continue
        employees.append(
            Employee(
                employee_id=row.employee_id,
                name=row.employee_name,
                email=row.email,
                department=row.department,
                manager_id=row.manager_id,
                manager_email=row.manager_email,
                source_row=row.row_number,
            )
        )

    return employees, sorted(errors, key=lambda err: err.row_number)


def _row_error(row: ParsedRow, error_type: IssueType, message: str) -> RowError:
    return RowError(
        row_number=row.row_number,
        error_type=error_type,
        message=message,
        employee_id=row.employee_id,
        email=row.email,
    )


# ---------------------------------------------------------------------------
# Manager / reference resolution
# ---------------------------------------------------------------------------


@dataclass
class ManagerResolution:
    """Outcome of resolving manager references for all accepted employees."""

    #: Resolved reporting edges: employee_id -> manager_id. Employees with a
    #: manager error simply have no entry here.
    manager_of: dict[str, str] = field(default_factory=dict)
    #: IDs whose manager fields were both blank: true roots.
    root_ids: list[str] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)


def resolve_managers(employees: list[Employee]) -> ManagerResolution:
    """Resolve each employee's manager reference to an accepted employee.

    Hash-map indexes (id -> employee, normalized email -> employee) make every
    lookup O(1); total work is O(n). Manager rows may appear anywhere in the
    file because resolution happens only after the full file has been read.
    """
    by_id = {e.employee_id: e for e in employees}
    by_email = {e.email: e for e in employees}

    result = ManagerResolution()

    for emp in employees:
        ref_id, ref_email = emp.manager_id, emp.manager_email

        if ref_id is None and ref_email is None:
            result.root_ids.append(emp.employee_id)
            continue

        by_id_hit = by_id.get(ref_id) if ref_id is not None else None
        by_email_hit = by_email.get(ref_email) if ref_email is not None else None

        if ref_id is not None and by_id_hit is None:
            result.errors.append(
                _manager_error(
                    emp, IssueType.MANAGER_NOT_FOUND,
                    f"No employee found with employee_id '{ref_id}'"
                    " (given as manager_id).",
                )
            )
            continue
        if ref_email is not None and by_email_hit is None:
            result.errors.append(
                _manager_error(
                    emp, IssueType.MANAGER_NOT_FOUND,
                    f"No employee found with email '{ref_email}'"
                    " (given as manager_email).",
                )
            )
            continue
        if (
            by_id_hit is not None
            and by_email_hit is not None
            and by_id_hit.employee_id != by_email_hit.employee_id
        ):
            result.errors.append(
                _manager_error(
                    emp, IssueType.MANAGER_CONFLICT,
                    f"manager_id '{ref_id}' resolves to employee"
                    f" '{by_id_hit.employee_id}' but manager_email"
                    f" '{ref_email}' resolves to employee"
                    f" '{by_email_hit.employee_id}'.",
                )
            )
            continue

        resolved = by_id_hit if by_id_hit is not None else by_email_hit
        if resolved is None:  # unreachable: at least one lookup succeeded above
            continue

        if resolved.employee_id == emp.employee_id:
            result.errors.append(
                _manager_error(
                    emp, IssueType.SELF_MANAGED,
                    f"Employee '{emp.employee_id}' cannot manage themselves.",
                )
            )
            continue

        result.manager_of[emp.employee_id] = resolved.employee_id

    return result


def _manager_error(emp: Employee, error_type: IssueType, message: str) -> RowError:
    return RowError(
        row_number=emp.source_row,
        error_type=error_type,
        message=message,
        employee_id=emp.employee_id,
        email=emp.email,
    )


# ---------------------------------------------------------------------------
# Hierarchy analysis
# ---------------------------------------------------------------------------


@dataclass
class HierarchyAnalysis:
    roots: list[Employee]
    #: Adjacency list: manager_id -> direct reports (sorted by employee_id).
    reports_of: dict[str, list[Employee]]
    cyclic_ids: set[str]


def analyze_hierarchy(
    employees: list[Employee], resolution: ManagerResolution
) -> HierarchyAnalysis:
    by_id = {e.employee_id: e for e in employees}

    reports_of: dict[str, list[Employee]] = {e.employee_id: [] for e in employees}
    for child_id, parent_id in resolution.manager_of.items():
        reports_of[parent_id].append(by_id[child_id])
    for reports in reports_of.values():
        reports.sort(key=lambda e: e.employee_id)

    roots = [by_id[i] for i in sorted(resolution.root_ids)]
    cyclic_ids = detect_cycles(resolution.manager_of)

    return HierarchyAnalysis(roots=roots, reports_of=reports_of, cyclic_ids=cyclic_ids)


def detect_cycles(manager_of: Mapping[str, str | None]) -> set[str]:
    """Return exactly the employee IDs that sit ON a reporting cycle.

    In the reporting graph every employee has AT MOST ONE outgoing edge (their
    single resolved manager). We exploit that structure with an iterative
    three-state walk:

      * WHITE -- node not visited yet;
      * GRAY  -- node is on the chain currently being walked;
      * BLACK -- node finished earlier (its chain was already resolved).

    Walking forward follows manager links from an unvisited start node:

      * reaching a WHITE node extends the current chain;
      * reaching a GRAY node means the chain looped back onto itself: the
        segment from that GRAY node to the current position IS the cycle, so
        exactly those nodes are marked cyclic;
      * reaching a node with no outgoing edge (a root) or a BLACK node means
        the chain flows into already-analyzed territory and closes no cycle.

    Why this is correct here: because out-degree <= 1, the chain between the
    GRAY node and the current position could only have been reached by
    following reporting edges, so marking that segment cannot over-mark
    nodes that merely lead INTO a cycle; and every cyclic node is eventually
    walked this way, so nothing is under-marked either. Employees whose
    manager reference errored have no outgoing edge at all, and self-loops
    are impossible because self-management is rejected during resolution.

    Complexity: O(n) time (each node turns GRAY once and BLACK once) and O(n)
    space. The walk is iterative, so a 100k-deep reporting chain cannot hit
    Python's recursion limit. For a general digraph with arbitrary fan-out,
    strongly connected components (e.g. Tarjan's algorithm) would be the
    appropriate tool instead.
    """
    white, gray, black = 0, 1, 2
    # Seed colors for edge targets too, so the function stays safe even if a
    # caller hands us a target id that has no key of its own.
    color = {node: white for node in set(manager_of) | set(manager_of.values())}
    cyclic: set[str] = set()

    for start in manager_of:
        if color[start] != white:
            continue
        chain: list[str] = []
        node: str | None = start
        while node is not None:
            state = color[node]
            if state == white:
                color[node] = gray
                chain.append(node)
                node = manager_of.get(node)
            elif state == gray:
                # Closed a loop: mark the cycle segment within this chain.
                cyclic.update(chain[chain.index(node):])
                break
            else:  # black: leads into an already-resolved region.
                break
        for visited in chain:
            color[visited] = black

    return cyclic


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def build_import_preview(data: bytes) -> ImportPreview:
    """Process uploaded CSV bytes end-to-end into an :class:`ImportPreview`.

    Raises:
        CsvStructureError: when the file cannot be parsed at all (bad encoding,
            missing headers, malformed structure). Row-level problems do NOT
            raise; they are part of the returned preview.
    """
    parsed = parse_csv(data)

    rows = [normalize_row(raw) for raw in parsed.rows]
    employees, identity_errors = validate_identity(rows)

    resolution = resolve_managers(employees)
    analysis = analyze_hierarchy(employees, resolution)

    by_id = {e.employee_id: e for e in employees}
    direct_reports = [
        ManagerDirectReports(
            manager=by_id[manager_id], count=len(reports), reports=reports
        )
        for manager_id, reports in analysis.reports_of.items()
        if reports
    ]
    direct_reports.sort(
        key=lambda entry: (
            -entry.count,
            entry.manager.name.casefold(),
            entry.manager.employee_id,
        )
    )

    return ImportPreview(
        total_source_rows=parsed.total_source_rows,
        accepted_employees=sorted(employees, key=lambda e: e.employee_id),
        identity_errors=identity_errors,
        manager_errors=sorted(resolution.errors, key=lambda err: err.row_number),
        roots=analysis.roots,
        direct_reports=direct_reports,
        cyclic_employees=[by_id[i] for i in sorted(analysis.cyclic_ids)],
    )
