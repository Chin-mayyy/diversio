# HRIS Import Preview

A small FastAPI application for previewing an HRIS CSV export before any data
is imported. Upload a file in the browser (or POST it to the JSON API) and get
back:

- the total number of source rows;
- the employees accepted for analysis;
- row-level identity validation errors with source row numbers;
- manager-resolution errors (missing, conflicting, or self-referencing);
- root employees who have no manager;
- managers with their direct reports and direct-report counts;
- employees that participate in a reporting cycle.

No database, no persistence: each upload is processed entirely in memory.

## Why FastAPI instead of Django?

The assignment notes Django matches Diversio's stack but allows another
Python framework if the choice is explained. FastAPI was chosen here because:

- **Scope fit.** The deliverable is a single stateless endpoint pair (an
  upload form + a JSON API) over pure functions, with no ORM, migrations,
  admin, or auth — most of what Django provides would be unused ballast.
- **Typed boundaries.** The import result is a Pydantic model (`ImportPreview`),
  so the JSON response schema is explicit, validated, and documented
  automatically at `/docs` without hand-writing serializers.
- **Testability.** The core pipeline never touches HTTP objects; FastAPI sits
  on top of it as a thin adapter, and `fastapi.testclient` covers the web
  layer without a running server.

The trade-off: Django's templating/admin would make the HTML surface slightly
faster to extend, and Django is the team's familiar framework — adapting to
FastAPI conventions would be a real cost in a larger codebase.

## Architecture

```
app/
  models.py     Domain models (Pydantic): RawRow, ParsedRow, Employee,
                RowError, ImportPreview. No HTTP/template imports.
  parser.py     Structural CSV parsing: bytes -> UTF-8 decode (BOM-tolerant)
                -> header validation -> RawRow list with source line numbers.
                Fatal structural problems raise CsvStructureError.
  services.py   All business logic as pure functions:
                  normalize_row          trim values, lowercase emails
                  validate_identity      required fields, duplicate detection
                  resolve_managers       id/email reference resolution
                  analyze_hierarchy      roots + adjacency list
                  detect_cycles          exact cycle membership
                  build_import_preview   orchestration entry point
  main.py       FastAPI routes: GET /, POST /upload (HTML), POST /api/import
                (JSON). HTTP concerns only.
  templates/    Jinja2 templates: base.html, index.html, result.html, error.html
tests/          pytest suite (pure-function tests + API integration tests)
sample_hris.csv The sample export from the assignment
pyproject.toml  Project metadata; uv is the package manager
```

`build_import_preview(data: bytes) -> ImportPreview` is the whole pipeline.
It can be called directly from a REPL or test without starting a server.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync            # creates .venv, installs runtime + dev dependencies
```

## Run

```bash
uv run uvicorn app.main:app --reload
```

Then open <http://127.0.0.1:8000/> and upload `sample_hris.csv`. An
interactive API schema is available at `/docs`.

## Test

```bash
uv run pytest -v
```

## API

| Method | Path          | Description |
|--------|---------------|-------------|
| GET    | `/`           | HTML upload form |
| POST   | `/upload`     | Multipart CSV upload; renders the HTML preview |
| POST   | `/api/import` | Multipart CSV upload; returns the preview as JSON |

Status codes used by `/api/import`:

- `200` — file processed successfully. Row-level data problems are *part of
  the result* (see `identity_errors` / `manager_errors`), not failures.
- `400` — structurally invalid upload: not UTF-8, empty, missing required
  columns, or malformed CSV structure. `detail` explains why.
- `413` — upload exceeds the 10 MiB size limit.
- `422` — request missing the multipart `file` part.

Example:

```bash
curl -s -F "file=@sample_hris.csv" http://127.0.0.1:8000/api/import | jq .
```

## CSV format

Required headers (any order, extra columns ignored):

```
employee_id,employee_name,email,manager_id,manager_email,department
```

Standard CSV quoting applies (a name like `Alvarez, Renée` must be quoted).
UTF-8 files with or without a byte-order mark are accepted.

## Normalization and validation rules

Applied in order:

1. **Trim** surrounding whitespace from every value; whitespace-only cells are
   treated as blank.
2. **Lowercase** `email` and `manager_email`.
3. **Employee IDs stay case-sensitive** (`DIV-1` ≠ `div-1`).

Identity rules:

- `employee_id` and `email` are required.
- Each must be unique after normalization.
- If an ID or email is duplicated, **every** row sharing it is invalid.
- Invalid rows do not participate in manager lookup or hierarchy analysis —
  so a reference pointing at an invalid row will itself report
  "manager not found".

Manager rules:

- Both manager fields blank → root employee.
- Only `manager_id` → looked up case-sensitively by employee ID.
- Only `manager_email` → looked up by normalized email.
- Both supplied → both must resolve, and to the **same** employee.
- Unresolvable reference, conflicting references, or an employee naming
  themselves produce a `manager_errors` entry. The employee **stays accepted**
  but produces no reporting relationship and is not a root.
- Manager rows may appear before or after their reports; resolution runs only
  after the whole file has been read.

## Hierarchy algorithm

After resolution, relationships form an adjacency list
(`manager_id -> [direct reports]`) built in one O(n) pass over the resolved
edges — no repeated scans of the employee list. Roots are the employees whose
manager fields were both blank. Direct-report counts are `len()` of each
adjacency entry. Overall processing is O(n) time and space; a 100,000-row
file needs two linear passes plus constant-time hash lookups per row.

## Cycle detection

`detect_cycles` receives the resolved edges as `employee -> manager`. Since
each employee has **at most one** outgoing edge, the structure is a functional
graph, which permits an exact, iterative three-state walk (WHITE / GRAY /
BLACK):

1. From every unvisited node, follow manager links, pushing nodes onto the
   current chain and marking them GRAY.
2. Reaching a GRAY node means the chain looped back onto itself: the segment
   from that node to the current position **is** a cycle, and exactly those
   nodes are marked cyclic.
3. Reaching a root (no outgoing edge) or a BLACK node ends the chain with no
   new cycle found; the chain is then colored BLACK.

Correctness rests on out-degree ≤ 1: the marked segment could only have been
reached along reporting edges, so employees that merely report *into* a cycle
are never marked (e.g. in `D → A → B → C → A`, only A/B/C are cyclic). Each
node turns GRAY once and BLACK once, so detection is O(n) time and space, and
the walk is iterative — a 100k-deep chain cannot hit Python's recursion limit.

For a general digraph with arbitrary fan-out, strongly connected components
(e.g. Tarjan's algorithm) would be the appropriate tool; SCCs are unnecessary
complexity for this edge shape. Self-loops cannot occur because self-management
is rejected during resolution.

## Design decisions

- **Pure core, thin shell.** No function in `parser.py`/`services.py` imports
  FastAPI or templates; `main.py` contains no business logic. Tests exercise
  the pipeline directly, and the HTTP layer is covered by a handful of
  integration tests.
- **Explicit result models.** `ImportPreview` and its children are Pydantic
  models, so the API response is typed, serializable, and stable — internal
  objects are not exposed raw.
- **Fatal vs. row-level errors.** Problems that make the file untrustworthy
  (bad encoding, missing headers, structural damage) abort the import with a
  clear message and status code. Per-row data problems never abort anything:
  they are collected with source line numbers into the preview, which is the
  entire point of a pre-import review tool.
- **Duplicate semantics.** Every row sharing a duplicated ID/email is
  rejected, per spec — even if other copies look fine.
- **Deterministic output.** Employees, roots, and cycle members are sorted by
  employee ID; errors by row number; managers by count descending then name —
  stable for both tests and humans.

## Assumptions and known limitations

- **All six headers must be present** (order-insensitive). The assignment's
  contract lists them all; a file lacking any of them is treated as malformed.
  Extra columns are ignored.
- Header matching tolerates stray whitespace/case (`" Email "` works); cell
  matching follows the rules above exactly.
- Row numbers refer to physical file lines (header = line 1), so a quoted
  field spanning lines reports its last line.
- Files are capped at 10 MiB as a guard rail (~100k rows fits comfortably).
- Everything runs in memory per request: nothing is cached or persisted, and
  there is no pagination for very large previews.
- `department` and `employee_name` may be blank; only `employee_id`/`email`
  are identity-required.
- Duplicate header names in one file are not specially handled (first match
  wins).

## AI tools used

Built with assistance from an LLM coding agent (**ox-alpha**); implementation
plan, code, tests, and this document were reviewed and verified locally by
running the test suite and exercising the app manually.
