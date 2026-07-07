from __future__ import annotations

import time
from dataclasses import asdict
from typing import BinaryIO

from .ocr import extract_text_from_image
from .rules import compare_label_to_application


def review_one(file_obj: BinaryIO, application: dict[str, str]) -> dict:
    start = time.perf_counter()
    label_text = extract_text_from_image(file_obj)
    checks = compare_label_to_application(label_text, application)
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    has_fail = any(c.status == "FAIL" for c in checks)
    has_review = any(c.status == "REVIEW" for c in checks)
    decision = "REJECT" if has_fail else "NEEDS_AGENT_REVIEW" if has_review else "PASS"

    return {
        "decision": decision,
        "elapsed_ms": elapsed_ms,
        "checks": [asdict(c) for c in checks],
        "ocr_text": label_text,
    }

