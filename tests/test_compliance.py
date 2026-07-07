"""Unit tests for the compliance comparison rules.

We test the pure comparison logic, not the vision call. The vision
extraction is mocked by constructing LabelExtraction objects directly.
"""
from app.compliance import compare, _parse_abv, _parse_volume_ml
from app.schemas import Application, BeverageClass, FieldStatus, LabelExtraction, Verdict


VALID_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink "
    "alcoholic beverages during pregnancy because of the risk of birth defects. "
    "(2) Consumption of alcoholic beverages impairs your ability to drive a car or "
    "operate machinery, and may cause health problems."
)


def _app(**overrides) -> Application:
    base = dict(
        beverage_class=BeverageClass.DISTILLED_SPIRITS,
        brand_name="Old Tom Distillery",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.",
        net_contents="750 mL",
        producer_name="Old Tom Distillery Co.",
        producer_address="Louisville, KY",
        is_import=False,
    )
    base.update(overrides)
    return Application(**base)


def _extraction(**overrides) -> LabelExtraction:
    base = dict(
        brand_name="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol. (90 Proof)",
        net_contents="750 mL",
        producer_name="Old Tom Distillery Co.",
        producer_address="Louisville, KY",
        country_of_origin=None,
        government_warning_text=VALID_WARNING,
        government_warning_present=True,
        government_warning_all_caps_header=True,
        image_quality_notes=None,
    )
    base.update(overrides)
    return LabelExtraction(**base)


def _find(result, field):
    return next(c for c in result.checks if c.field == field)


# --- happy path ---------------------------------------------------------------


def test_clean_match_passes():
    r = compare(_app(), _extraction())
    assert r.verdict == Verdict.PASS
    assert all(
        c.status in (FieldStatus.MATCH, FieldStatus.NOT_APPLICABLE) for c in r.checks
    )


# --- Dave's case: casing / punctuation drift on brand name -------------------


def test_brand_case_drift_is_review_not_fail():
    """Dave's example: STONE'S THROW vs Stone's Throw — same brand, different presentation."""
    a = _app(brand_name="Stone's Throw")
    e = _extraction(brand_name="STONE'S THROW")
    r = compare(a, e)
    brand = _find(r, "brand_name")
    # Token set ratio should score this at 100 (identical after casefold), so MATCH.
    assert brand.status == FieldStatus.MATCH
    assert r.verdict == Verdict.PASS


def test_completely_different_brand_fails():
    e = _extraction(brand_name="Jack Daniel's")
    r = compare(_app(brand_name="Old Tom Distillery"), e)
    assert _find(r, "brand_name").status == FieldStatus.MISMATCH
    assert r.verdict == Verdict.FAIL


# --- Jenny's case: warning statement formatting ------------------------------


def test_warning_title_case_header_is_mismatch():
    """Jenny caught 'Government Warning' in title case — must be all caps."""
    e = _extraction(
        government_warning_text=VALID_WARNING.replace("GOVERNMENT WARNING", "Government Warning"),
        government_warning_all_caps_header=False,
    )
    r = compare(_app(), e)
    warn = _find(r, "government_warning")
    assert warn.status == FieldStatus.MISMATCH
    assert r.verdict == Verdict.FAIL


def test_missing_warning_is_hard_fail():
    e = _extraction(
        government_warning_text=None,
        government_warning_present=False,
        government_warning_all_caps_header=False,
    )
    r = compare(_app(), e)
    warn = _find(r, "government_warning")
    assert warn.status == FieldStatus.MISSING_ON_LABEL
    assert r.verdict == Verdict.FAIL


def test_warning_missing_required_phrase_is_mismatch():
    truncated = "GOVERNMENT WARNING: Consumption of alcoholic beverages may cause health problems."
    e = _extraction(
        government_warning_text=truncated,
        government_warning_present=True,
        government_warning_all_caps_header=True,
    )
    r = compare(_app(), e)
    assert _find(r, "government_warning").status == FieldStatus.MISMATCH
    assert r.verdict == Verdict.FAIL


# --- ABV parsing -------------------------------------------------------------


def test_abv_parses_percent_and_proof():
    assert _parse_abv("45% Alc./Vol.") == 45.0
    assert _parse_abv("45% Alc./Vol. (90 Proof)") == 45.0
    assert _parse_abv("5.2% ABV") == 5.2
    assert _parse_abv("90 Proof") == 45.0
    assert _parse_abv(None) is None


def test_abv_within_tolerance_passes():
    a = _app(alcohol_content="45.0% Alc./Vol.")
    e = _extraction(alcohol_content="45.1% Alc./Vol.")
    r = compare(a, e)
    assert _find(r, "alcohol_content").status == FieldStatus.MATCH


def test_abv_out_of_tolerance_fails():
    a = _app(alcohol_content="40% Alc./Vol.")
    e = _extraction(alcohol_content="45% Alc./Vol.")
    r = compare(a, e)
    assert _find(r, "alcohol_content").status == FieldStatus.MISMATCH


# --- volume parsing ----------------------------------------------------------


def test_volume_parses_units():
    assert _parse_volume_ml("750 mL") == 750.0
    assert _parse_volume_ml("1.75 L") == 1750.0
    assert abs(_parse_volume_ml("12 fl oz") - 354.882) < 0.1


def test_volume_unit_conversion_matches():
    a = _app(net_contents="750 mL")
    e = _extraction(net_contents="0.75 L")
    r = compare(a, e)
    assert _find(r, "net_contents").status == FieldStatus.MATCH


# --- imports -----------------------------------------------------------------


def test_import_without_country_on_label_fails():
    a = _app(is_import=True, country_of_origin="Scotland")
    e = _extraction(country_of_origin=None)
    r = compare(a, e)
    assert _find(r, "country_of_origin").status == FieldStatus.MISSING_ON_LABEL
    assert r.verdict in (Verdict.REVIEW, Verdict.FAIL)


def test_domestic_skips_country_check():
    r = compare(_app(is_import=False), _extraction(country_of_origin=None))
    assert _find(r, "country_of_origin").status == FieldStatus.NOT_APPLICABLE
