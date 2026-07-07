from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher


GOVERNMENT_WARNING_EXACT = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth defects. "
    "(2) Consumption of alcoholic beverages impairs your ability to drive a car or "
    "operate machinery, and may cause health problems."
)


def normalize_for_match(value: str) -> str:
    value = value or ""
    value = value.upper()
    value = re.sub(r"[^A-Z0-9]+", "", value)
    return value


def normalize_spaces(value: str) -> str:
    value = value or ""
    value = re.sub(r"\s+", " ", value).strip()
    return value


def fuzzy_equal(a: str, b: str, threshold: float = 0.94) -> bool:
    na = normalize_for_match(a)
    nb = normalize_for_match(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= threshold


def extract_abv(text: str) -> str:
    text = text or ""
    # Captures "45% Alc./Vol." and simple "45%"
    match = re.search(r"(\d{1,2}(?:\.\d{1,2})?)\s*%\s*(?:ALC\.?\s*/\s*VOL\.?)?", text, re.IGNORECASE)
    if not match:
        return ""
    return f"{match.group(1)}%"


def extract_net_contents(text: str) -> str:
    text = text or ""
    match = re.search(r"(\d+(?:\.\d+)?)\s*(ML|L|FL\.?\s*OZ)", text, re.IGNORECASE)
    if not match:
        return ""
    qty = match.group(1)
    unit = normalize_spaces(match.group(2)).upper().replace(".", "")
    return f"{qty} {unit}"


@dataclass
class FieldResult:
    field: str
    expected: str
    actual: str
    status: str
    notes: str


def compare_label_to_application(label_text: str, application: dict[str, str]) -> list[FieldResult]:
    label_text = normalize_spaces(label_text)
    label_upper = label_text.upper()
    results: list[FieldResult] = []

    expected_brand = application.get("brand_name", "")
    brand_found = fuzzy_equal(label_text, expected_brand, threshold=0.93)
    results.append(
        FieldResult(
            field="Brand Name",
            expected=expected_brand,
            actual="Detected in label text" if brand_found else "Not confidently detected",
            status="PASS" if brand_found else "REVIEW",
            notes="Case/punctuation differences are treated as equivalent.",
        )
    )

    expected_class = application.get("class_type", "")
    class_found = fuzzy_equal(label_text, expected_class, threshold=0.9)
    results.append(
        FieldResult(
            field="Class/Type",
            expected=expected_class,
            actual="Detected in label text" if class_found else "Not confidently detected",
            status="PASS" if class_found else "REVIEW",
            notes="Can require agent judgment if wording is close but not exact.",
        )
    )

    expected_abv_raw = application.get("abv", "")
    expected_abv = extract_abv(expected_abv_raw) or expected_abv_raw
    actual_abv = extract_abv(label_text)
    abv_ok = normalize_for_match(expected_abv) == normalize_for_match(actual_abv)
    results.append(
        FieldResult(
            field="Alcohol Content (ABV)",
            expected=expected_abv,
            actual=actual_abv or "Not detected",
            status="PASS" if abv_ok else "FAIL",
            notes="ABV is compared by normalized percentage value.",
        )
    )

    expected_net = extract_net_contents(application.get("net_contents", "")) or application.get("net_contents", "")
    actual_net = extract_net_contents(label_text)
    net_ok = normalize_for_match(expected_net) == normalize_for_match(actual_net)
    results.append(
        FieldResult(
            field="Net Contents",
            expected=expected_net,
            actual=actual_net or "Not detected",
            status="PASS" if net_ok else "FAIL",
            notes="Compares quantity/unit after normalization.",
        )
    )

    warning_present = GOVERNMENT_WARNING_EXACT in label_text
    warning_caps_ok = "GOVERNMENT WARNING:" in label_upper
    warning_status = "PASS" if warning_present and warning_caps_ok else "FAIL"
    warning_note = (
        "Must match required text exactly and include uppercase heading."
        if warning_status == "FAIL"
        else "Exact warning statement detected."
    )
    results.append(
        FieldResult(
            field="Government Warning Statement",
            expected=GOVERNMENT_WARNING_EXACT,
            actual="Detected exactly" if warning_present else "Missing or altered",
            status=warning_status,
            notes=warning_note,
        )
    )

    return results
