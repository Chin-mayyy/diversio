"""API integration tests for the upload endpoints (no business logic here)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

from helpers import make_csv

client = TestClient(app)


def _upload(data: bytes, filename: str = "hris.csv"):
    return client.post(
        "/api/import",
        files={"file": (filename, data, "text/csv")},
    )


def test_get_index_serves_upload_form():
    response = client.get("/")
    assert response.status_code == 200
    assert 'enctype="multipart/form-data"' in response.text
    assert "/upload" in response.text


def test_api_import_returns_typed_preview_json():
    response = _upload(
        make_csv(
            [
                ["E-1", "Ada", "ada@x.io", "", "", "Eng"],
                ["E-2", "Bob", "bob@x.io", "E-1", "", "Eng"],
            ]
        )
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_source_rows"] == 2
    assert payload["accepted_employees"][0]["employee_id"] == "E-1"
    assert payload["roots"] == [
        {
            "employee_id": "E-1",
            "name": "Ada",
            "email": "ada@x.io",
            "department": "Eng",
            "manager_id": None,
            "manager_email": None,
            "source_row": 2,
        }
    ]
    assert payload["direct_reports"][0]["count"] == 1
    assert payload["cyclic_employees"] == []


def test_api_import_reports_row_level_problems_with_200():
    response = _upload(
        make_csv(
            [
                ["E-1", "Ada", "", "", "", ""],             # missing email: identity error
                ["E-2", "Bob", "b@x.io", "GHOST", "", ""],  # unknown manager: manager error
                ["E-3", "Cara", "c@x.io", "E-2", "", ""],   # healthy reporting edge
            ]
        )
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_source_rows"] == 3

    assert [e["error_type"] for e in payload["identity_errors"]] == ["missing_email"]
    assert payload["identity_errors"][0]["row_number"] == 2

    assert [e["error_type"] for e in payload["manager_errors"]] == ["manager_not_found"]
    assert payload["manager_errors"][0]["employee_id"] == "E-2"

    # E-1 is rejected for the missing email; the other two stay accepted.
    assert {e["employee_id"] for e in payload["accepted_employees"]} == {"E-2", "E-3"}
    assert {r["employee_id"] for r in payload["direct_reports"][0]["reports"]} == {"E-3"}


def test_api_import_rejects_missing_headers_with_400():
    bad = b"employee_id,employee_name\nE-1,Ada\n"
    response = _upload(bad)

    assert response.status_code == 400
    assert "email" in response.json()["detail"]


def test_api_import_rejects_non_utf8_with_400():
    response = _upload(b"\xff\xfe\x00\x00")
    assert response.status_code == 400
    assert "UTF-8" in response.json()["detail"]


def test_api_import_requires_a_file_part():
    response = client.post("/api/import")
    assert response.status_code == 422  # FastAPI validation error for missing part


def test_html_upload_renders_preview_page():
    response = client.post(
        "/upload",
        files={"file": ("hris.csv", make_csv([["E-1", "Ada", "ada@x.io", "", "", "Eng"]]), "text/csv")},
    )

    assert response.status_code == 200
    assert "Root employees" in response.text
    assert "Ada" in response.text
    assert "No reporting cycles detected" in response.text


def test_html_upload_shows_errors_for_structurally_broken_file():
    response = client.post(
        "/upload",
        files={"file": ("broken.csv", b"employee_id,name\nE-1,A\n", "text/csv")},
    )

    assert response.status_code == 400
    assert "missing required column" in response.text
