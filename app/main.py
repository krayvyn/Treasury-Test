"""FastAPI entry point for the TTB Label Compliance prototype.

Endpoints:
  GET  /                — the single-page UI
  POST /api/review      — one label + one application, JSON result
  POST /api/batch       — many labels + one application, JSON array
  GET  /api/healthz     — liveness probe (Render uses this)
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .compliance import compare
from .schemas import Application, BeverageClass, ComplianceResult
from .vision import VisionError, extract_label

APP_DIR = Path(__file__).parent

app = FastAPI(
    title="TTB Label Compliance Prototype",
    description="AI-assisted first-pass review of alcohol beverage label applications.",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")

MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB per image; ample for label photography
MAX_BATCH = 25                     # bounds latency & cost per request


def _build_application(
    beverage_class: str,
    brand_name: str,
    class_type: str,
    net_contents: str,
    producer_name: str,
    alcohol_content: Optional[str],
    producer_address: Optional[str],
    country_of_origin: Optional[str],
    is_import: bool,
) -> Application:
    try:
        bc = BeverageClass(beverage_class)
    except ValueError:
        raise HTTPException(400, f"Invalid beverage_class: {beverage_class}")
    return Application(
        beverage_class=bc,
        brand_name=brand_name.strip(),
        class_type=class_type.strip(),
        alcohol_content=(alcohol_content or "").strip() or None,
        net_contents=net_contents.strip(),
        producer_name=producer_name.strip(),
        producer_address=(producer_address or "").strip() or None,
        country_of_origin=(country_of_origin or "").strip() or None,
        is_import=is_import,
    )


async def _review_one(image_bytes: bytes, filename: str, application: Application) -> ComplianceResult:
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(413, f"{filename}: image exceeds {MAX_IMAGE_BYTES // (1024*1024)} MB limit.")

    started = time.perf_counter()
    # extract_label is sync (anthropic SDK is sync); run in thread so we don't block the loop.
    try:
        extraction = await asyncio.to_thread(extract_label, image_bytes, filename)
    except VisionError as e:
        raise HTTPException(502, str(e))
    result = compare(application, extraction)
    result.filename = filename
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/api/review", response_model=ComplianceResult)
async def review(
    image: UploadFile = File(...),
    beverage_class: str = Form(...),
    brand_name: str = Form(...),
    class_type: str = Form(...),
    net_contents: str = Form(...),
    producer_name: str = Form(...),
    alcohol_content: Optional[str] = Form(None),
    producer_address: Optional[str] = Form(None),
    country_of_origin: Optional[str] = Form(None),
    is_import: bool = Form(False),
):
    application = _build_application(
        beverage_class, brand_name, class_type, net_contents, producer_name,
        alcohol_content, producer_address, country_of_origin, is_import,
    )
    image_bytes = await image.read()
    return await _review_one(image_bytes, image.filename or "label.jpg", application)


@app.post("/api/batch")
async def batch(
    images: list[UploadFile] = File(...),
    beverage_class: str = Form(...),
    brand_name: str = Form(...),
    class_type: str = Form(...),
    net_contents: str = Form(...),
    producer_name: str = Form(...),
    alcohol_content: Optional[str] = Form(None),
    producer_address: Optional[str] = Form(None),
    country_of_origin: Optional[str] = Form(None),
    is_import: bool = Form(False),
):
    if len(images) > MAX_BATCH:
        raise HTTPException(413, f"Batch limit is {MAX_BATCH} labels per request.")

    application = _build_application(
        beverage_class, brand_name, class_type, net_contents, producer_name,
        alcohol_content, producer_address, country_of_origin, is_import,
    )

    async def _one(img: UploadFile) -> dict:
        raw = await img.read()
        try:
            result = await _review_one(raw, img.filename or "label.jpg", application)
            return result.model_dump(mode="json")
        except HTTPException as e:
            return {
                "filename": img.filename,
                "verdict": "error",
                "error": e.detail,
            }

    # Fan out in parallel; each label is one vision call.
    results = await asyncio.gather(*(_one(i) for i in images))
    return JSONResponse({"results": results})
