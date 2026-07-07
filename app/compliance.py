"""Compare an Application (source of truth) against a LabelExtraction.

Rules of thumb per the interviews:
- Names: fuzzy match. Dave's example: "STONE'S THROW" on label vs "Stone's Throw"
  in the application is the same brand. Case and punctuation drift is tolerable;
  a different actual word is not.
- ABV: parse the numeric value. "45% Alc./Vol. (90 Proof)" and "45% ABV" are
  the same declaration.
- Net contents: normalize units. "750 mL" == "750ml".
- Government warning: strict. Jenny caught a rejection for "Government Warning"
  in title case instead of all caps. If it's missing entirely, that's a hard FAIL.
- Country of origin: only required on imports.
"""
from __future__ import annotations

import re
from typing import Optional

from rapidfuzz import fuzz

from .schemas import (
    Application,
    ComplianceResult,
    FieldCheck,
    FieldStatus,
    LabelExtraction,
    Verdict,
)

# The mandatory TTB health warning statement, verbatim per 27 CFR § 16.21.
# We check for its presence and canonical form. Exact-string equality is too
# brittle (whitespace, line breaks from OCR), so we normalize whitespace and
# then require every phrase to appear.
REQUIRED_WARNING_PHRASES = [
    "GOVERNMENT WARNING",
    "According to the Surgeon General",
    "women should not drink alcoholic beverages during pregnancy",
    "birth defects",
    "impairs your ability to drive a car or operate machinery",
    "may cause health problems",
]

# Similarity thresholds. Tuned so that "STONE'S THROW" vs "Stone's Throw"
# resolves as a match (score ~100 after casefold) but distinct brands don't.
NAME_MATCH_THRESHOLD = 88       # brand, producer name
CLASS_TYPE_MATCH_THRESHOLD = 80 # class/type has more legitimate variation
ADDRESS_MATCH_THRESHOLD = 75    # addresses have punctuation drift


# --- helpers ------------------------------------------------------------------


def _norm(s: Optional[str]) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()


def _name_similarity(a: str, b: str) -> float:
    """Case-insensitive token-set ratio. Handles reordered words and punctuation."""
    return fuzz.token_set_ratio(a.lower(), b.lower())


def _parse_abv(s: Optional[str]) -> Optional[float]:
    """Pull the ABV percentage as a float, ignoring proof/label chrome."""
    if not s:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", s)
    if m:
        return float(m.group(1))
    # "90 Proof" alone
    m = re.search(r"(\d+(?:\.\d+)?)\s*proof", s, re.IGNORECASE)
    if m:
        return float(m.group(1)) / 2.0
    return None


def _parse_volume_ml(s: Optional[str]) -> Optional[float]:
    """Normalize net contents to milliliters for comparison."""
    if not s:
        return None
    txt = s.lower().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(ml|l|fl\.?\s*oz|oz)", txt)
    if not m:
        return None
    value = float(m.group(1))
    unit = m.group(2).replace(" ", "").replace(".", "")
    if unit == "ml":
        return value
    if unit == "l":
        return value * 1000.0
    if unit in ("floz", "oz"):
        return value * 29.5735
    return None


def _warning_check(extraction: LabelExtraction) -> FieldCheck:
    """Government warning: hard requirement. Text must contain every mandated phrase,
    and the 'GOVERNMENT WARNING:' header must be in all caps."""
    if not extraction.government_warning_present:
        return FieldCheck(
            field="government_warning",
            status=FieldStatus.MISSING_ON_LABEL,
            expected="Mandatory TTB Government Warning statement",
            found=None,
            detail="No government warning statement detected on the label. This is a hard rejection under 27 CFR § 16.21.",
        )

    text = _norm(extraction.government_warning_text)
    missing = [p for p in REQUIRED_WARNING_PHRASES if p.lower() not in text.lower()]

    if not extraction.government_warning_all_caps_header:
        return FieldCheck(
            field="government_warning",
            status=FieldStatus.MISMATCH,
            expected="Header 'GOVERNMENT WARNING:' in all caps, bold",
            found=extraction.government_warning_text,
            detail="Warning header is not in all caps. TTB requires 'GOVERNMENT WARNING:' verbatim in all caps.",
        )

    if missing:
        return FieldCheck(
            field="government_warning",
            status=FieldStatus.MISMATCH,
            expected="Complete mandatory warning statement",
            found=extraction.government_warning_text,
            detail=f"Warning is present but missing required phrase(s): {'; '.join(missing)}.",
        )

    return FieldCheck(
        field="government_warning",
        status=FieldStatus.MATCH,
        expected="Complete mandatory warning statement",
        found="Present, complete, all-caps header",
        detail="Government warning statement is present with the required header formatting and required content.",
    )


def _brand_check(app: Application, ex: LabelExtraction) -> FieldCheck:
    if not ex.brand_name:
        return FieldCheck(
            field="brand_name",
            status=FieldStatus.MISSING_ON_LABEL,
            expected=app.brand_name,
            found=None,
            detail="Brand name is not visible on the label.",
        )
    score = _name_similarity(app.brand_name, ex.brand_name)
    if score >= 98:
        status, detail = FieldStatus.MATCH, "Brand name matches."
    elif score >= NAME_MATCH_THRESHOLD:
        status = FieldStatus.NEEDS_REVIEW
        detail = f"Brand name matches semantically (similarity {score:.0f}) but casing or punctuation differs. Agent judgment recommended."
    else:
        status, detail = FieldStatus.MISMATCH, f"Brand name on label does not match application (similarity {score:.0f})."
    return FieldCheck(field="brand_name", status=status, expected=app.brand_name, found=ex.brand_name, detail=detail)


def _class_type_check(app: Application, ex: LabelExtraction) -> FieldCheck:
    if not ex.class_type:
        return FieldCheck(
            field="class_type",
            status=FieldStatus.MISSING_ON_LABEL,
            expected=app.class_type,
            found=None,
            detail="Class/type designation is not visible on the label.",
        )
    score = _name_similarity(app.class_type, ex.class_type)
    if score >= 95:
        status, detail = FieldStatus.MATCH, "Class/type matches."
    elif score >= CLASS_TYPE_MATCH_THRESHOLD:
        status = FieldStatus.NEEDS_REVIEW
        detail = f"Class/type is close (similarity {score:.0f}) but wording differs. Verify TTB class designation is correct."
    else:
        status, detail = FieldStatus.MISMATCH, f"Class/type on label does not match application (similarity {score:.0f})."
    return FieldCheck(field="class_type", status=status, expected=app.class_type, found=ex.class_type, detail=detail)


def _abv_check(app: Application, ex: LabelExtraction) -> FieldCheck:
    if not app.alcohol_content:
        # Beer/wine can be exempt in some cases
        return FieldCheck(
            field="alcohol_content",
            status=FieldStatus.NOT_APPLICABLE,
            expected=None,
            found=ex.alcohol_content,
            detail="Application did not declare an ABV; skipped.",
        )
    if not ex.alcohol_content:
        return FieldCheck(
            field="alcohol_content",
            status=FieldStatus.MISSING_ON_LABEL,
            expected=app.alcohol_content,
            found=None,
            detail="ABV declaration not visible on the label.",
        )
    a = _parse_abv(app.alcohol_content)
    b = _parse_abv(ex.alcohol_content)
    if a is None or b is None:
        return FieldCheck(
            field="alcohol_content",
            status=FieldStatus.NEEDS_REVIEW,
            expected=app.alcohol_content,
            found=ex.alcohol_content,
            detail="Could not parse ABV from one or both sources. Agent review needed.",
        )
    if abs(a - b) < 0.15:  # TTB tolerance is class-dependent; 0.15% is a safe default
        return FieldCheck(
            field="alcohol_content",
            status=FieldStatus.MATCH,
            expected=app.alcohol_content,
            found=ex.alcohol_content,
            detail=f"ABV matches ({a}% vs {b}%).",
        )
    return FieldCheck(
        field="alcohol_content",
        status=FieldStatus.MISMATCH,
        expected=app.alcohol_content,
        found=ex.alcohol_content,
        detail=f"ABV mismatch: application says {a}%, label says {b}%.",
    )


def _net_contents_check(app: Application, ex: LabelExtraction) -> FieldCheck:
    if not ex.net_contents:
        return FieldCheck(
            field="net_contents",
            status=FieldStatus.MISSING_ON_LABEL,
            expected=app.net_contents,
            found=None,
            detail="Net contents not visible on the label.",
        )
    a = _parse_volume_ml(app.net_contents)
    b = _parse_volume_ml(ex.net_contents)
    if a is None or b is None:
        # Fall back to string similarity
        score = _name_similarity(app.net_contents, ex.net_contents)
        status = FieldStatus.MATCH if score >= 95 else FieldStatus.NEEDS_REVIEW
        return FieldCheck(
            field="net_contents",
            status=status,
            expected=app.net_contents,
            found=ex.net_contents,
            detail="Could not parse volume; compared as text.",
        )
    # Allow 1% tolerance for rounding
    if abs(a - b) / max(a, b) < 0.01:
        return FieldCheck(
            field="net_contents",
            status=FieldStatus.MATCH,
            expected=app.net_contents,
            found=ex.net_contents,
            detail=f"Net contents match ({a:.0f} mL equivalent).",
        )
    return FieldCheck(
        field="net_contents",
        status=FieldStatus.MISMATCH,
        expected=app.net_contents,
        found=ex.net_contents,
        detail=f"Net contents mismatch: application {a:.0f} mL, label {b:.0f} mL.",
    )


def _producer_check(app: Application, ex: LabelExtraction) -> FieldCheck:
    if not ex.producer_name:
        return FieldCheck(
            field="producer_name",
            status=FieldStatus.MISSING_ON_LABEL,
            expected=app.producer_name,
            found=None,
            detail="Producer / bottler name not visible on the label.",
        )
    score = _name_similarity(app.producer_name, ex.producer_name)
    if score >= 95:
        status, detail = FieldStatus.MATCH, "Producer name matches."
    elif score >= NAME_MATCH_THRESHOLD:
        status = FieldStatus.NEEDS_REVIEW
        detail = f"Producer name is close (similarity {score:.0f}) — verify."
    else:
        status, detail = FieldStatus.MISMATCH, f"Producer name mismatch (similarity {score:.0f})."
    return FieldCheck(field="producer_name", status=status, expected=app.producer_name, found=ex.producer_name, detail=detail)


def _country_check(app: Application, ex: LabelExtraction) -> FieldCheck:
    if not app.is_import:
        return FieldCheck(
            field="country_of_origin",
            status=FieldStatus.NOT_APPLICABLE,
            expected=None,
            found=ex.country_of_origin,
            detail="Domestic product; country of origin not required.",
        )
    if not app.country_of_origin:
        return FieldCheck(
            field="country_of_origin",
            status=FieldStatus.NEEDS_REVIEW,
            expected=None,
            found=ex.country_of_origin,
            detail="Application is flagged as import but no country of origin declared.",
        )
    if not ex.country_of_origin:
        return FieldCheck(
            field="country_of_origin",
            status=FieldStatus.MISSING_ON_LABEL,
            expected=app.country_of_origin,
            found=None,
            detail="Import product but country of origin not visible on label. TTB requires country of origin on imports.",
        )
    score = _name_similarity(app.country_of_origin, ex.country_of_origin)
    if score >= 85:
        return FieldCheck(
            field="country_of_origin",
            status=FieldStatus.MATCH,
            expected=app.country_of_origin,
            found=ex.country_of_origin,
            detail="Country of origin matches.",
        )
    return FieldCheck(
        field="country_of_origin",
        status=FieldStatus.MISMATCH,
        expected=app.country_of_origin,
        found=ex.country_of_origin,
        detail="Country of origin on label does not match application.",
    )


# --- entry point --------------------------------------------------------------


def compare(app: Application, extraction: LabelExtraction) -> ComplianceResult:
    checks: list[FieldCheck] = [
        _brand_check(app, extraction),
        _class_type_check(app, extraction),
        _abv_check(app, extraction),
        _net_contents_check(app, extraction),
        _producer_check(app, extraction),
        _country_check(app, extraction),
        _warning_check(extraction),
    ]

    verdict = _verdict(checks)
    return ComplianceResult(verdict=verdict, checks=checks, extraction=extraction)


def _verdict(checks: list[FieldCheck]) -> Verdict:
    # Any hard failure on the warning is an automatic FAIL.
    for c in checks:
        if c.field == "government_warning" and c.status in (FieldStatus.MISSING_ON_LABEL, FieldStatus.MISMATCH):
            return Verdict.FAIL

    statuses = [c.status for c in checks if c.status != FieldStatus.NOT_APPLICABLE]

    if any(s == FieldStatus.MISMATCH for s in statuses):
        return Verdict.FAIL
    if any(s in (FieldStatus.MISSING_ON_LABEL, FieldStatus.NEEDS_REVIEW) for s in statuses):
        return Verdict.REVIEW
    return Verdict.PASS
