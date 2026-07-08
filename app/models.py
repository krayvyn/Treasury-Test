"""Data contracts shared between vision extraction, validation, and the UI.

Keeping every downstream consumer typed against these means the Claude prompt,
the rule engine, and the templates cannot drift out of sync silently.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    PASS = "pass"
    REVIEW = "review"  # human eye needed; e.g. Dave's "STONE'S THROW" case
    FAIL = "fail"


class BeverageClass(str, Enum):
    BEER = "beer"
    WINE = "wine"
    SPIRITS = "spirits"
    UNKNOWN = "unknown"


class ExtractedLabel(BaseModel):
    """What Claude vision pulled off the label image."""

    brand_name: Optional[str] = None
    class_type: Optional[str] = None
    alcohol_content: Optional[str] = None  # raw, e.g. "45% Alc./Vol. (90 Proof)"
    alcohol_pct: Optional[float] = None    # normalized numeric value
    net_contents: Optional[str] = None
    bottler_name: Optional[str] = None
    bottler_address: Optional[str] = None
    country_of_origin: Optional[str] = None
    beverage_class: BeverageClass = BeverageClass.UNKNOWN

    # Warning statement gets its own structure because Jenny called out that
    # exact-text + ALL-CAPS + bold are separate failure modes.
    warning_text: Optional[str] = None
    warning_heading_all_caps: Optional[bool] = None
    warning_appears_bold: Optional[bool] = None

    # Confidence + image quality hints so we can surface "unclear image" instead
    # of throwing a false-fail when the photo is bad.
    image_legible: bool = True
    image_notes: Optional[str] = None
    extraction_confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ApplicationRecord(BaseModel):
    """What the applicant claimed on the COLA form."""

    brand_name: Optional[str] = None
    class_type: Optional[str] = None
    alcohol_content: Optional[str] = None
    alcohol_pct: Optional[float] = None
    net_contents: Optional[str] = None
    bottler_name: Optional[str] = None
    bottler_address: Optional[str] = None
    country_of_origin: Optional[str] = None
    beverage_class: BeverageClass = BeverageClass.UNKNOWN


class FieldCheck(BaseModel):
    """One row in the reviewer's verdict table."""

    field: str
    label_value: Optional[str] = None
    application_value: Optional[str] = None
    verdict: Verdict
    reason: str  # short, plain-language justification for the verdict
    similarity: Optional[float] = None  # 0-1, when a fuzzy match ran


class LabelReview(BaseModel):
    """Top-level result: the whole reviewer verdict for one label."""

    overall: Verdict
    summary: str
    checks: list[FieldCheck]
    extracted: ExtractedLabel
    application: ApplicationRecord
    processing_ms: int
    filename: Optional[str] = None
