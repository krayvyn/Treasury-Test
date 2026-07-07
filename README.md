# TTB Label Compliance Assistant (Prototype)

This is a standalone proof-of-concept for TTB label review workflows.
It focuses on fast, agent-friendly checks and does **not** integrate with COLA.

## Why this design

- **Speed-first UX**: local OCR + rules to target sub-5 second checks per label on normal hardware.
- **Simple interface**: two clear modes (single review and batch review), minimal clicks.
- **Human-in-the-loop**: fuzzy matching for nuanced fields and explicit `NEEDS_AGENT_REVIEW` outcomes.
- **Offline-friendly**: no required cloud API calls (helps with restricted government networks).

## Features

- Single-label compliance check
- Batch processing for importer surges (200-300 applications)
- Field checks:
  - Brand name (fuzzy, case/punctuation-tolerant)
  - Class/type (fuzzy)
  - ABV (normalized percent compare)
  - Net contents (normalized quantity/unit compare)
  - Government warning statement (exact required text check)
- Export batch decisions to CSV

## Tech choices

- `Streamlit` for quick, clear UI suitable for mixed technical comfort levels.
- `pytesseract` + `Pillow` for local OCR.
- Rule-based validation layer for deterministic checks.

## Prerequisites

1. Python 3.10+
2. Tesseract OCR installed on host machine (required by `pytesseract`)
   - [Windows installer](https://github.com/UB-Mannheim/tesseract/wiki)

## Setup

```bash
cd ttb_label_prototype
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
streamlit run app.py
```

## Batch mode input format

Upload one CSV with these columns:

- `filename`
- `brand_name`
- `class_type`
- `abv`
- `net_contents`

Then upload image files with names matching the `filename` values.
See `sample_data/applications.csv` for an example.

## Assumptions and trade-offs

- This prototype assumes image text is OCR-readable. Poor image quality may still need manual review.
- "Bold" warning heading validation is not enforced in this version; exact text + uppercase heading is enforced.
- No PII/data retention layer is implemented for prototype scope.
- No direct integration with legacy COLA infrastructure (intentional per requirement).

## Deployment options

- **Fastest for evaluation**: run locally with Streamlit.
- **Cloud option**: deploy to Azure App Service/Container Apps with Tesseract installed in container image.

## Suggested next steps

- Add perspective correction/glare handling pre-processing for poor photo quality.
- Add queue management, user roles, and audit trail for pilot operations.
- Add beverage-type-specific rule packs (beer/wine/spirits).
