"""Extract TTB-relevant fields from a label image using Claude vision.

We ask Claude to return a strict JSON envelope so the downstream compliance
check has a stable shape. One API call per label — Sarah's team learned the
hard way that a 30-40 second turnaround kills adoption, so we keep it to one
round-trip and let Claude do the heavy lifting in a single pass.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Optional

from anthropic import Anthropic

from .schemas import LabelExtraction

# Sonnet is the right balance of vision quality and latency for this workload.
# Haiku is faster but drops accuracy on stylized label typography (calligraphy,
# distressed fonts, ornate serifs common on spirits labels).
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")

EXTRACTION_PROMPT = """You are assisting a TTB (Alcohol and Tobacco Tax and Trade Bureau)
compliance agent reviewing an alcohol beverage label. Extract the following fields
exactly as they appear on the label. Return ONLY a JSON object, no prose, no code fences.

Schema:
{
  "brand_name": string or null,
  "class_type": string or null,           // e.g. "Kentucky Straight Bourbon Whiskey", "India Pale Ale", "Cabernet Sauvignon"
  "alcohol_content": string or null,      // e.g. "45% Alc./Vol." or "5.2% ABV" — copy verbatim
  "net_contents": string or null,         // e.g. "750 mL", "12 FL OZ", "1.75 L"
  "producer_name": string or null,        // bottler / producer / brewer / vintner name
  "producer_address": string or null,     // city, state; full address if present
  "country_of_origin": string or null,    // e.g. "Product of Scotland", if stated
  "government_warning_text": string or null,     // the FULL verbatim health warning text if present
  "government_warning_present": boolean,         // true if any recognizable government warning appears
  "government_warning_all_caps_header": boolean, // true ONLY if "GOVERNMENT WARNING:" appears in all caps as the header
  "image_quality_notes": string or null   // note any glare, blur, skew, cropping, or illegibility; null if image is clean
}

Rules:
- Copy text verbatim. Preserve original casing, punctuation, and spacing.
- If a field is not visible on the label, use null. Do not guess.
- For the government warning: TTB requires the exact statement beginning with
  "GOVERNMENT WARNING:" in all caps, bold. Report what you actually see.
- If the image is unreadable (severe glare, extreme angle, blur), still return
  what you can and describe the problem in image_quality_notes.
"""


class VisionError(Exception):
    pass


def _client() -> Anthropic:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise VisionError(
            "ANTHROPIC_API_KEY is not set. Set it in the environment or a .env file."
        )
    return Anthropic(api_key=key)


def _guess_media_type(filename: Optional[str], data: bytes) -> str:
    if filename:
        low = filename.lower()
        if low.endswith(".png"):
            return "image/png"
        if low.endswith(".webp"):
            return "image/webp"
        if low.endswith(".gif"):
            return "image/gif"
    # Sniff PNG magic
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def extract_label(image_bytes: bytes, filename: Optional[str] = None) -> LabelExtraction:
    """Single vision call. Returns a LabelExtraction or raises VisionError."""
    client = _client()
    b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    media_type = _guess_media_type(filename, image_bytes)

    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=1024,
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
    except Exception as e:
        raise VisionError(f"Vision API call failed: {e}") from e

    # Pull text blocks
    text = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text").strip()

    # Model sometimes wraps in a code fence despite instructions; strip defensively.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        raise VisionError(f"Vision response was not valid JSON: {e}. Raw: {text[:400]}") from e

    return LabelExtraction(**payload)
