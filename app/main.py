"""FastAPI application: upload routes, HTML presentation, and a JSON API.

All business logic lives in ``parser`` / ``services`` / ``models``; this module
only handles HTTP concerns (multipart handling, status codes, rendering).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .models import ImportPreview
from .parser import CsvStructureError, FileTooLargeError
from .services import build_import_preview

app = FastAPI(
    title="HRIS Import Preview",
    description="Upload an HRIS CSV and preview employees, hierarchy, and data problems.",
)

_templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Upload form."""
    return _templates.TemplateResponse(request=request, name="index.html")


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile = File(...)) -> HTMLResponse:
    """Browser-facing upload: renders the import preview as HTML.

    A structurally broken upload renders a 400 error page; row-level data
    problems are part of the preview itself, not an error.
    """
    data = await file.read()
    try:
        preview = build_import_preview(data)
    except FileTooLargeError as exc:
        return _error_page(request, str(exc), status_code=413)
    except CsvStructureError as exc:
        return _error_page(request, str(exc), status_code=400)

    return _templates.TemplateResponse(
        request=request, name="result.html", context={"preview": preview}
    )


@app.post("/api/import")
async def api_import(file: UploadFile = File(...)) -> ImportPreview:
    """Machine-facing upload: returns the import preview as JSON.

    200 -- file processed; row-level problems appear in the payload.
    400 -- structurally invalid CSV (bad encoding, missing headers, malformed).
    413 -- upload exceeds the size limit.
    422 -- request missing the multipart 'file' part (raised by FastAPI).
    """
    data = await file.read()
    try:
        return build_import_preview(data)
    except FileTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except CsvStructureError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _error_page(request: Request, message: str, status_code: int) -> HTMLResponse:
    return _templates.TemplateResponse(
        request=request,
        name="error.html",
        context={"message": message},
        status_code=status_code,
    )
