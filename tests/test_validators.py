"""Tests for the deterministic rule engine.

These cover the cases the TTB agents specifically called out in the interviews.
Nothing here hits the network; all values are hand-constructed.
"""

from app.models import ApplicationRecord, BeverageClass, ExtractedLabel, Verdict
from app.validators import MANDATORY_WARNING, _normalize, _similarity, review


def _base_application() -> ApplicationRecord:
    return ApplicationRecord(
        brand_name="Old Tom Distillery",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol. (90 Proof)",
        alcohol_pct=45.0,
        net_contents="750 mL",
        bottler_name="Old Tom Distillery Co.",
        bottler_address="Bardstown, KY",
        beverage_class=BeverageClass.SPIRITS,
    )


def _base_label(**overrides) -> ExtractedLabel:
    data = dict(
        brand_name="Old Tom Distillery",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol. (90 Proof)",
        alcohol_pct=45.0,
        net_contents="750 mL",
        bottler_name="Old Tom Distillery Co.",
        bottler_address="Bardstown, KY",
        beverage_class=BeverageClass.SPIRITS,
        warning_text=MANDATORY_WARNING,
        warning_heading_all_caps=True,
        warning_appears_bold=True,
        image_legible=True,
        extraction_confidence=0.95,
    )
    data.update(overrides)
    return ExtractedLabel(**data)


def test_all_matching_passes():
    result = review(_base_label(), _base_application(), 1200)
    assert result.overall == Verdict.PASS
    assert result.summary == "All checks passed."


def test_dave_stones_throw_case_still_passes():
    """Dave's exact example: label is ALL-CAPS with straight apostrophe,
    application is Title Case with curly apostrophe. Same brand."""
    label = _base_label(brand_name="STONE'S THROW")
    app = _base_application()
    app.brand_name = "Stone\u2019s Throw"
    result = review(label, app, 900)
    brand_check = next(c for c in result.checks if c.field == "Brand name")
    assert brand_check.verdict == Verdict.PASS
    assert "normaliz" in brand_check.reason.lower()


def test_abv_within_tolerance_passes():
    label = _base_label(alcohol_pct=45.1)
    app = _base_application()
    result = review(label, app, 800)
    abv = next(c for c in result.checks if c.field == "Alcohol content")
    assert abv.verdict == Verdict.PASS


def test_abv_over_tolerance_fails():
    label = _base_label(alcohol_pct=47.0, alcohol_content="47% Alc./Vol.")
    app = _base_application()
    result = review(label, app, 800)
    abv = next(c for c in result.checks if c.field == "Alcohol content")
    assert abv.verdict == Verdict.FAIL
    assert result.overall == Verdict.FAIL


def test_warning_missing_fails():
    label = _base_label(warning_text=None)
    result = review(label, _base_application(), 800)
    warning = next(c for c in result.checks if c.field == "Government warning")
    assert warning.verdict == Verdict.FAIL
    assert "no government warning" in warning.reason.lower()


def test_warning_title_case_heading_fails():
    """Jenny's specific catch: 'Government Warning' in title case."""
    label = _base_label(warning_heading_all_caps=False)
    result = review(label, _base_application(), 800)
    warning = next(c for c in result.checks if c.field == "Government warning")
    assert warning.verdict == Verdict.FAIL
    assert "all caps" in warning.reason.lower()


def test_warning_not_bold_fails():
    label = _base_label(warning_appears_bold=False)
    result = review(label, _base_application(), 800)
    warning = next(c for c in result.checks if c.field == "Government warning")
    assert warning.verdict == Verdict.FAIL
    assert "bold" in warning.reason.lower()


def test_illegible_image_short_circuits_to_review():
    label = _base_label(image_legible=False, image_notes="Heavy glare on the label front")
    result = review(label, _base_application(), 300)
    assert result.overall == Verdict.REVIEW
    assert len(result.checks) == 1
    assert result.checks[0].field == "Image quality"
    assert "re-shoot" in result.summary


def test_missing_field_on_label_fails_that_field():
    label = _base_label(net_contents=None)
    result = review(label, _base_application(), 700)
    nc = next(c for c in result.checks if c.field == "Net contents")
    assert nc.verdict == Verdict.FAIL


def test_close_but_not_identical_brand_needs_review():
    label = _base_label(brand_name="Old Tim Distillery")  # one-letter typo
    result = review(label, _base_application(), 700)
    brand = next(c for c in result.checks if c.field == "Brand name")
    assert brand.verdict in (Verdict.REVIEW, Verdict.FAIL)


def test_normalize_handles_curly_quotes_and_case():
    assert _normalize("Stone\u2019s Throw") == _normalize("STONE'S THROW")


def test_similarity_identical_after_normalize():
    assert _similarity("STONE'S THROW", "Stone\u2019s Throw") == 1.0
