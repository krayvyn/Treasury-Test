"""Claude vision extraction.

One vision call per label. Structured JSON out. The prompt is intentionally
opinionated about the warning statement — that's the field Jenny called out as
the trickiest, and we want the model to look at wording, capitalization, and
apparent weight as three separate observations.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any

from anthropic import Anthropic, APIError

from .config import settings
from .models import BeverageClass, ExtractedLabel

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.anthropic_api_key)
    return _client


EXTRACTION_PROMPT = """You are a TTB label-compliance assistant helping a human agent review an alcohol beverage label.

Look at the label image and extract every required field. Return ONLY a single JSON object, no prose, no code fences.

Schema:
{
  "brand_name": string or null,
  "class_type": string or null,             // e.g. "Kentucky Straight Bourbon Whiskey"
  "alcohol_content": string or null,        // the label's exact text, e.g. "45% Alc./Vol. (90 Proof)"
  "alcohol_pct": number or null,            // the numeric ABV percentage
  "net_contents": string or null,           // e.g. "750 mL"
  "bottler_name": string or null,
  "bottler_address": string or null,
  "country_of_origin": string or null,      // only if shown on the label
  "beverage_class": "beer" | "wine" | "spirits" | "unknown",
  "warning_text": string or null,           // the FULL government warning as it appears
  "warning_heading_all_caps": boolean or null,   // is "GOVERNMENT WARNING:" in all caps?
  "warning_appears_bold": boolean or null,       // does the warning statement appear bold?
  "image_legible": boolean,                 // false if you can't reliably read the label
  "image_notes": string or null,            // if not legible, briefly explain (glare, angle, blur)
  "extraction_confidence": number           // 0.0 - 1.0, your overall confidence
}

Rules:
- Transcribe values exactly as they appear. Don't correct capitalization or punctuation.
- If a field isn't visible, use null. Don't guess.
- If the image is unclear (glare, extreme angle, out of focus), set image_legible=false and explain in image_notes rather than returning garbage.
- For the warning statement, capture the entire text including the "GOVERNMENT WARNING:" heading.
- Return JSON only. No markdown, no commentary."""


def _parse_json(raw: str) -> dict[str, Any]:
    """Extract the first JSON object from the model response.

    The prompt asks for pure JSON but the model occasionally wraps it in a
    code fence or adds a stray sentence. Strip both cases.
    """
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))
    braced = re.search(r"\{.*\}", raw, re.DOTALL)
    if braced:
        return json.loads(braced.group(0))
    raise ValueError(f"No JSON object in model response: {raw[:200]}")


def _coerce_beverage_class(raw: Any) -> BeverageClass:
    if isinstance(raw, str):
        try:
            return BeverageClass(raw.lower())
        except ValueError:
            pass
    return BeverageClass.UNKNOWN


def extract(image_bytes: bytes, media_type: str = "image/png") -> ExtractedLabel:
    """Run one vision call and return a validated ExtractedLabel."""
    client = _get_client()
    b64 = base64.standard_b64encode(image_bytes).decode("ascii")

    try:
        response = client.messages.create(
            model=settings.vision_model,
            max_tokens=1500,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": EXTRACTION_PROMPT},
                    ],
                }
            ],
        )
    except APIError as exc:
        # Wrap the SDK error so callers only need to catch one type.
        raise RuntimeError(f"Vision API error: {exc}") from exc

    text_parts = [block.text for block in response.content if block.type == "text"]
    if not text_parts:
        raise RuntimeError("Vision API returned no text content")

    data = _parse_json("\n".join(text_parts))
    data["beverage_class"] = _coerce_beverage_class(data.get("beverage_class"))
    return ExtractedLabel.model_validate(data)
