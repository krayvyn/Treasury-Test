"""Rule engine that compares an extracted label to an application record.

Design goals, straight from the interview notes:

  * Dave's "STONE'S THROW" vs "Stone's Throw" case — a naive exact-match
    rejects this; a reviewer wouldn't. We normalize case, punctuation, and
    whitespace before comparing, but we still surface the raw values so a
    human can see what actually differed.

  * Jenny's warning-statement check — the mandatory language, ALL-CAPS header,
    and bold face are three separate failure modes. We check them independently
    so the reason we surface points at the specific problem.

  * Agents span Dave (28 years, prints his emails) to Jenny (8 months, would
    have built the tool herself). Reasons are written in plain English so both
    read the same thing the same way.

Nothing here calls the network; it's all deterministic and unit-testable.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .models import (
    ApplicationRecord,
    ExtractedLabel,
    FieldCheck,
    LabelReview,
    Verdict,
)

# Similarity thresholds tuned to make Dave's case pass cleanly and outright
# typos fail. REVIEW is the middle zone where a human should take a look.
STRONG_MATCH = 0.95
WEAK_MATCH = 0.78

# The mandatory Government Warning, as of 27 CFR 16.21. We match against a
# normalized form so minor punctuation differences don't cause a false fail;
# the ALL-CAPS heading and bold face are checked separately.
MANDATORY_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should "
    "not drink alcoholic beverages during pregnancy because of the risk of "
    "birth defects. (2) Consumption of alcoholic beverages impairs your "
    "ability to drive a car or operate machinery, and may cause health "
    "problems."
)


def _normalize(value: str | None) -> str:
    """Casefold, strip accents, collapse punctuation and whitespace."""
    if not value:
        return ""
    # NFKD splits accented chars into base + combining marks, then we drop the
    # marks. Handles curly quotes, en-dashes, etc.
    stripped = unicodedata.normalize("NFKD", value)
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    stripped = stripped.casefold()
    stripped = re.sub(r"[’'`´]", "'", stripped)
    stripped = re.sub(r"[^\w\s%.]", " ", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return stripped


def _similarity(a: str | None, b: str | None) -> float:
    na, nb = _normalize(a), _normalize(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _text_check(
    field_label: str,
    label_value: str | None,
    application_value: str | None,
    *,
    required: bool = True,
) -> FieldCheck:
    if not label_value and not application_value:
        verdict = Verdict.FAIL if required else Verdict.PASS
        reason = (
            f"Missing from both the label and the application."
            if required
            else "Not required for this beverage class."
        )
        return FieldCheck(
            field=field_label,
            label_value=label_value,
            application_value=application_value,
            verdict=verdict,
            reason=reason,
        )

    if not label_value:
        return FieldCheck(
            field=field_label,
            label_value=None,
            application_value=application_value,
            verdict=Verdict.FAIL,
            reason="Present on the application but not visible on the label.",
        )

    if not application_value:
        return FieldCheck(
            field=field_label,
            label_value=label_value,
            application_value=None,
            verdict=Verdict.FAIL,
            reason="Shown on the label but not declared on the application.",
        )

    ratio = _similarity(label_value, application_value)
    if ratio >= STRONG_MATCH:
        # Distinguish "identical" from "matches after normalization" so the
        # reviewer sees when the applicant used a different case or punctuation.
        if label_value.strip() == application_value.strip():
            reason = "Exact match."
        else:
            reason = "Matches after normalizing case and punctuation."
        verdict = Verdict.PASS
    elif ratio >= WEAK_MATCH:
        verdict = Verdict.REVIEW
        reason = "Close but not identical. A reviewer should confirm."
    else:
        verdict = Verdict.FAIL
        reason = "Label and application do not match."

    return FieldCheck(
        field=field_label,
        label_value=label_value,
        application_value=application_value,
        verdict=verdict,
        reason=reason,
        similarity=round(ratio, 3),
    )


def _abv_check(label: ExtractedLabel, application: ApplicationRecord) -> FieldCheck:
    """ABV gets a numeric tolerance instead of string similarity."""
    lp, ap = label.alcohol_pct, application.alcohol_pct
    label_display = label.alcohol_content or (f"{lp}%" if lp is not None else None)
    app_display = application.alcohol_content or (f"{ap}%" if ap is not None else None)

    if lp is None or ap is None:
        return _text_check(
            "Alcohol content", label.alcohol_content, application.alcohol_content
        )

    # TTB tolerance for spirits is 0.15% ABV, wine is 1.0-1.5%, beer is 0.3%.
    # A general 0.3% window is the safe pass zone; anything above needs a look.
    delta = abs(lp - ap)
    if delta <= 0.3:
        verdict = Verdict.PASS
        reason = f"Within tolerance ({delta:.2f}% difference)."
    elif delta <= 1.0:
        verdict = Verdict.REVIEW
        reason = (
            f"{delta:.2f}% difference — inside beer/wine tolerance but check "
            "class-specific rules."
        )
    else:
        verdict = Verdict.FAIL
        reason = f"{delta:.2f}% difference exceeds TTB tolerance."

    return FieldCheck(
        field="Alcohol content",
        label_value=label_display,
        application_value=app_display,
        verdict=verdict,
        reason=reason,
        similarity=round(1.0 - min(delta / 5.0, 1.0), 3),
    )


def _warning_check(label: ExtractedLabel) -> FieldCheck:
    """The government warning has three separable failure modes."""
    if not label.warning_text:
        return FieldCheck(
            field="Government warning",
            label_value=None,
            application_value=MANDATORY_WARNING,
            verdict=Verdict.FAIL,
            reason="No government warning found on the label.",
        )

    ratio = _similarity(label.warning_text, MANDATORY_WARNING)

    problems: list[str] = []
    if ratio < STRONG_MATCH:
        problems.append("wording differs from the required statement")
    if label.warning_heading_all_caps is False:
        problems.append("'GOVERNMENT WARNING:' is not in all caps")
    if label.warning_appears_bold is False:
        problems.append("the statement does not appear bold")

    if not problems:
        return FieldCheck(
            field="Government warning",
            label_value=label.warning_text,
            application_value=MANDATORY_WARNING,
            verdict=Verdict.PASS,
            reason="Full mandatory statement, all-caps heading, bold face.",
            similarity=round(ratio, 3),
        )

    # Any warning-statement problem is a hard fail. This is one of the few
    # places we don't want a REVIEW verdict — TTB rejects these outright.
    return FieldCheck(
        field="Government warning",
        label_value=label.warning_text,
        application_value=MANDATORY_WARNING,
        verdict=Verdict.FAIL,
        reason="Non-compliant: " + "; ".join(problems) + ".",
        similarity=round(ratio, 3),
    )


def _rollup(checks: list[FieldCheck]) -> tuple[Verdict, str]:
    """Combine per-field verdicts into an overall status."""
    if any(c.verdict == Verdict.FAIL for c in checks):
        failed = [c.field for c in checks if c.verdict == Verdict.FAIL]
        return Verdict.FAIL, f"Rejected — {len(failed)} issue{'s' if len(failed) != 1 else ''} on {', '.join(failed)}."
    if any(c.verdict == Verdict.REVIEW for c in checks):
        review = [c.field for c in checks if c.verdict == Verdict.REVIEW]
        return Verdict.REVIEW, f"Needs a human eye on {', '.join(review)}."
    return Verdict.PASS, "All checks passed."


def review(
    label: ExtractedLabel,
    application: ApplicationRecord,
    processing_ms: int,
    filename: str | None = None,
) -> LabelReview:
    """Run the full check-list and return a LabelReview."""
    if not label.image_legible:
        # Bail out with a specific reason instead of cascading false-fails
        # through every field.
        return LabelReview(
            overall=Verdict.REVIEW,
            summary=(
                "The label image is not clearly legible. Ask the applicant "
                "for a re-shoot before proceeding."
            ),
            checks=[
                FieldCheck(
                    field="Image quality",
                    label_value=label.image_notes or "Unclear",
                    application_value=None,
                    verdict=Verdict.REVIEW,
                    reason=label.image_notes
                    or "Extraction confidence too low to compare fields.",
                )
            ],
            extracted=label,
            application=application,
            processing_ms=processing_ms,
            filename=filename,
        )

    checks: list[FieldCheck] = [
        _text_check("Brand name", label.brand_name, application.brand_name),
        _text_check("Class / type", label.class_type, application.class_type),
        _abv_check(label, application),
        _text_check("Net contents", label.net_contents, application.net_contents),
        _text_check("Bottler name", label.bottler_name, application.bottler_name),
        _text_check(
            "Bottler address", label.bottler_address, application.bottler_address
        ),
        _warning_check(label),
    ]

    # Country of origin is only required for imports. Skip when both sides
    # agree it's domestic.
    if application.country_of_origin or label.country_of_origin:
        checks.append(
            _text_check(
                "Country of origin",
                label.country_of_origin,
                application.country_of_origin,
            )
        )

    overall, summary = _rollup(checks)
    return LabelReview(
        overall=overall,
        summary=summary,
        checks=checks,
        extracted=label,
        application=application,
        processing_ms=processing_ms,
        filename=filename,
    )
