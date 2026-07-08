"""Image preprocessing for imperfect label photos.

Jenny in the interviews specifically called out labels shot at weird angles,
under bad lighting, or with bottle glare. Agents reject those and ask for a
re-shoot; we should give the model a fighting chance first.

This module is intentionally conservative: it fixes orientation and boosts
readability without introducing artifacts that would confuse the vision model.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, ImageEnhance

# Claude vision performs best with images in a reasonable range. Anything
# smaller and OCR-scale text disappears; anything larger and we're paying for
# tokens that don't help. 1600px on the long edge is a good middle.
MAX_LONG_EDGE = 1600
MIN_LONG_EDGE = 900


def preprocess(raw_bytes: bytes) -> bytes:
    """Return a preprocessed PNG suitable for the vision model.

    Applies, in order:
      1. EXIF orientation fix — phone photos are frequently sideways.
      2. Conversion to RGB — some uploads are RGBA or CMYK.
      3. Autocontrast — pulls washed-out photos into a usable range.
      4. Mild sharpness bump — helps small print like the government warning.
      5. Long-edge resize into the sweet spot for the vision model.
    """
    with Image.open(io.BytesIO(raw_bytes)) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode != "RGB":
            img = img.convert("RGB")

        img = ImageOps.autocontrast(img, cutoff=1)
        img = ImageEnhance.Sharpness(img).enhance(1.2)

        long_edge = max(img.size)
        if long_edge > MAX_LONG_EDGE:
            scale = MAX_LONG_EDGE / long_edge
            new_size = (int(img.size[0] * scale), int(img.size[1] * scale))
            img = img.resize(new_size, Image.LANCZOS)
        elif long_edge < MIN_LONG_EDGE:
            # Upscaling won't create detail but it does give the vision model
            # more pixels to attend to for small warning text.
            scale = MIN_LONG_EDGE / long_edge
            new_size = (int(img.size[0] * scale), int(img.size[1] * scale))
            img = img.resize(new_size, Image.LANCZOS)

        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True)
        return out.getvalue()
