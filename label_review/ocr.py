from __future__ import annotations

import io
from typing import BinaryIO

from PIL import Image, ImageOps


def extract_text_from_image(file_obj: BinaryIO) -> str:
    """
    Attempts offline OCR using pytesseract.
    Raises RuntimeError with a user-friendly message if OCR isn't available.
    """
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError(
            "pytesseract is not installed. Run `pip install -r requirements.txt`."
        ) from exc

    try:
        payload = file_obj.read()
        image = Image.open(io.BytesIO(payload))
        image = ImageOps.exif_transpose(image).convert("L")
        text = pytesseract.image_to_string(image)
        return text.strip()
    except Exception as exc:
        raise RuntimeError(f"OCR failed for image: {exc}") from exc

