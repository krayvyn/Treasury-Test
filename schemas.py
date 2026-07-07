"""Data models for label applications, extractions, and comparison results."""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class BeverageClass(str, Enum):
    """TTB beverage categories. Requirements differ slightly per class."""
    BEER = "beer"
    WINE = "wine"
    DISTILLED_SPIRITS = "distilled_spirits"


class Application(BaseModel):
    """What the applicant filed in COLA — the source of truth we check against."""
    beverage_class: BeverageClass
    brand_name: str
    class_type: str = Field(..., description="e.g. 'Kentucky Straight Bourbon Whiskey'")
    alcohol_content: Optional[str] = Field(None, description="e.g. '45% Alc./Vol.' — optional for some beer/wine")
    net_contents: str = Field(..., description="e.g. '750 mL'")
    producer_name: str
    producer_address: Optional[str] = None
    country_of_origin: Optional[str] = Field(None, description="Required for imports")
    is_import: bool = False


class LabelExtraction(BaseModel):
    """What we found on the label image, per Claude's vision pass."""
    brand_name: Optional[str] = None
    class_type: Optional[str] = None
    alcohol_content: Optional[str] = None
    net_contents: Optional[str] = None
    producer_name: Optional[str] = None
    producer_address: Optional[str] = None
    country_of_origin: Optional[str] = None
    government_warning_text: Optional[str] = None
    government_warning_present: bool = False
    government_warning_all_caps_header: bool = Field(
        False, description="Whether 'GOVERNMENT WARNING:' appears in all caps on the label"
    )
    image_quality_notes: Optional[str] = Field(
        None, description="Vision model's note on legibility, glare, angle, etc."
    )


class FieldStatus(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    MISSING_ON_LABEL = "missing_on_label"
    NEEDS_REVIEW = "needs_review"
    NOT_APPLICABLE = "not_applicable"


class FieldCheck(BaseModel):
    field: str
    status: FieldStatus
    expected: Optional[str] = None
    found: Optional[str] = None
    detail: str


class Verdict(str, Enum):
    PASS = "pass"           # everything matched cleanly
    REVIEW = "review"       # minor discrepancies, agent should look
    FAIL = "fail"           # hard violation (e.g. no warning statement)


class ComplianceResult(BaseModel):
    verdict: Verdict
    checks: list[FieldCheck]
    extraction: LabelExtraction
    filename: Optional[str] = None
    elapsed_ms: Optional[int] = None
