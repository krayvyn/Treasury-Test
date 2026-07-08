"""FastAPI entrypoint.

Routes:
  GET  /                — landing page (single upload + samples + batch link)
  GET  /batch           — batch upload page
  POST /api/analyze     — analyze one label, return JSON LabelReview
  POST /api/batch       — analyze many labels, return JSON list[LabelReview]
  POST /api/sample/{id} — run a baked-in sample end-to-end
  GET  /healthz         — liveness probe for Render
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import settings
from .models import ApplicationRecord, LabelReview
from .preprocessing import preprocess
from .samples import SAMPLES, by_id
from .validators import review
from .vision import extract

APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR / "static"
TEMPLATE_DIR = APP_DIR / "templates"

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# Concurrency guard for batch — Claude vision has per-key rate limits and we
# don't want a burst of 300 labels to trip them.
_batch_sem = asyncio.Semaphore(settings.batch_concurrency)


# --- Pages -------------------------------------------------------------------


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "samples": SAMPLES, "settings": settings},
    )


@app.get("/batch")
async def batch_page(request: Request):
    return templates.TemplateResponse(
        "batch.html",
        {"request": request, "settings": settings},
    )


@app.get("/healthz")
async def healthz():
    return {"ok": True}


# --- Core analysis path ------------------------------------------------------


async def _analyze_bytes(
    raw: bytes,
    application: ApplicationRecord,
    filename: str | None,
) -> LabelReview:
    """Preprocess + extract + validate. All timing folded into processing_ms."""
    started = time.perf_counter()
    prepared = preprocess(raw)
    # extract() is a blocking SDK call; run it off the event loop so the
    # server stays responsive during batch runs.
    extracted = await asyncio.to_thread(extract, prepared, "image/jpeg")
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return review(extracted, application, elapsed_ms, filename)


def _parse_application(raw: str | None) -> ApplicationRecord:
    if not raw:
        return ApplicationRecord()
    try:
        return ApplicationRecord.model_validate_json(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid application JSON: {exc}") from exc


async def _read_upload(upload: UploadFile) -> bytes:
    raw = await upload.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(raw) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File {upload.filename} exceeds {settings.max_upload_mb} MB limit.",
        )
    return raw


# --- API ---------------------------------------------------------------------


@app.post("/api/analyze")
async def api_analyze(
    label: UploadFile = File(...),
    application: str | None = Form(default=None),
):
    raw = await _read_upload(label)
    app_record = _parse_application(application)
    result = await _analyze_bytes(raw, app_record, label.filename)
    return JSONResponse(result.model_dump(mode="json"))


@app.post("/api/batch")
async def api_batch(
    labels: list[UploadFile] = File(...),
    applications: str | None = Form(default=None),
):
    """Analyze multiple labels in parallel.

    `applications` is an optional JSON array whose entries match the uploads by
    order (or by filename if the entry has a `filename` key). Missing entries
    fall back to an empty ApplicationRecord — the review will surface every
    field as "not declared on the application" instead of crashing.
    """
    if not labels:
        raise HTTPException(status_code=400, detail="No labels uploaded.")

    app_records: dict[str, ApplicationRecord] = {}
    positional: list[ApplicationRecord] = []
    if applications:
        try:
            parsed = json.loads(applications)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid applications JSON: {exc}") from exc
        if not isinstance(parsed, list):
            raise HTTPException(status_code=400, detail="applications must be a JSON array.")
        for entry in parsed:
            record = ApplicationRecord.model_validate(entry)
            positional.append(record)
            fname = entry.get("filename") if isinstance(entry, dict) else None
            if fname:
                app_records[fname] = record

    async def _one(idx: int, upload: UploadFile) -> LabelReview:
        raw = await _read_upload(upload)
        app_record = (
            app_records.get(upload.filename or "")
            or (positional[idx] if idx < len(positional) else ApplicationRecord())
        )
        async with _batch_sem:
            return await _analyze_bytes(raw, app_record, upload.filename)

    results = await asyncio.gather(
        *(_one(i, u) for i, u in enumerate(labels)),
        return_exceptions=True,
    )

    payload = []
    for upload, result in zip(labels, results):
        if isinstance(result, Exception):
            payload.append(
                {
                    "filename": upload.filename,
                    "error": str(result),
                }
            )
        else:
            payload.append(result.model_dump(mode="json"))
    return JSONResponse(payload)


@app.post("/api/sample/{sample_id}")
async def api_sample(sample_id: str):
    sample = by_id(sample_id)
    if sample is None:
        raise HTTPException(status_code=404, detail="Unknown sample.")
    image_path = STATIC_DIR / sample.image_path
    if not image_path.exists():
        raise HTTPException(
            status_code=500,
            detail=(
                f"Sample image missing at {image_path}. "
                "Add the file to app/static/samples/ and redeploy."
            ),
        )
    raw = image_path.read_bytes()
    result = await _analyze_bytes(raw, sample.application, image_path.name)
    return JSONResponse(result.model_dump(mode="json"))
