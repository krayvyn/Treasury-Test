# TTB Label Check

A prototype web tool that does a first-pass compliance review of alcohol beverage
label applications. An agent uploads a label image and the corresponding
application data; the tool extracts the label's declared fields with Claude
vision, compares them to the filing, and returns a per-field verdict with a
clear PASS / REVIEW / FAIL headline.

The intent is to remove the mechanical "is the number on the form the same as
the number on the label" work that Sarah's team is drowning in, while leaving
judgment calls to the agent.

## What it checks

For each label:

- **Brand name** &mdash; fuzzy compare, tolerant of casing and punctuation drift
  (`STONE'S THROW` vs `Stone's Throw` is a match, not a mismatch)
- **Class / type designation** &mdash; fuzzy compare
- **Alcohol content** &mdash; numeric parse; handles `% Alc./Vol.`, `% ABV`, and
  `Proof`; 0.15% tolerance
- **Net contents** &mdash; unit-normalized to mL; handles `750 mL`, `0.75 L`,
  `12 fl oz`; 1% tolerance
- **Producer / bottler name** &mdash; fuzzy compare
- **Country of origin** &mdash; only enforced when the application is marked as
  an import
- **Government Health Warning** &mdash; strict. Must be present, header must be
  `GOVERNMENT WARNING:` in all caps, and all required phrases must appear.
  Anything short of that is a hard FAIL.

Verdicts:

- **PASS** &mdash; all applicable fields match cleanly
- **REVIEW** &mdash; minor discrepancies (casing drift, missing optional field);
  agent should confirm
- **FAIL** &mdash; hard mismatch or missing government warning

## Architecture

```
Browser ── multipart POST ──► FastAPI ── image + prompt ──► Claude vision (Sonnet)
                                 │                              │
                                 ◄──── structured JSON ─────────┘
                                 │
                                 ├── compliance.py compares extraction to application
                                 └── returns per-field checks + verdict
```

Nothing is persisted server-side. Images and application data live in memory
for the duration of a single request.

**Tech choices and why:**

- **FastAPI** &mdash; single-file async, cheap to host, works fine on Render's
  free tier
- **Claude Sonnet vision** &mdash; a single vision call replaces OCR + parsing
  + field extraction. Handles stylized label typography (calligraphy,
  distressed serifs, ornate spirits labels) and imperfect photography
  (glare, skew) far better than a traditional OCR pipeline. Latency lands
  around 2&ndash;4 seconds per label, comfortably under Sarah's 5-second bar.
- **`rapidfuzz`** &mdash; token-set ratio for name comparison; handles reordered
  words, punctuation drift, and casing without becoming lax about actual
  differences
- **No JS framework** &mdash; the UI is under 300 lines of vanilla JS. Half of
  Sarah's team is over 50 and the design brief is "something my mother could
  figure out." Big touch targets, one form, one result panel.

## Run it locally

```bash
git clone <your-repo-url>
cd ttb-label-check

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY

export $(grep -v '^#' .env | xargs)   # or use direnv / a dotenv loader
uvicorn app.main:app --reload
```

Open http://localhost:8000.

Run tests:

```bash
pip install pytest
pytest -q
```

## Deploy to Render

1. Push this repo to GitHub.
2. In Render, **New +** &rarr; **Blueprint** &rarr; select your repo. The
   included `render.yaml` provisions the service.
3. When Render asks, set `ANTHROPIC_API_KEY` as a secret env var. The
   blueprint marks it `sync: false` so it's never in git.
4. Deploy. Health check is at `/api/healthz`.

Free-tier services sleep after inactivity and take ~30 seconds to wake, which
is fine for a prototype but not for the real agents; move to a paid plan
before any pilot.

## API

**`POST /api/review`** &mdash; single label. Multipart form:

- `image` &mdash; the label image (JPG / PNG / WebP, &le; 8 MB)
- `beverage_class` &mdash; `distilled_spirits` / `wine` / `beer`
- `brand_name`, `class_type`, `net_contents`, `producer_name` &mdash; required
- `alcohol_content`, `producer_address`, `country_of_origin` &mdash; optional
- `is_import` &mdash; boolean

Returns a `ComplianceResult` JSON object (see `app/schemas.py`).

**`POST /api/batch`** &mdash; up to 25 label images against one application
record. Same fields, but `images` is a repeated file field.

Returns `{ "results": [ComplianceResult, ...] }`. Vision calls run in
parallel; total wall time is roughly the slowest single call plus
serialization.

**`GET /api/healthz`** &mdash; liveness probe.

## Assumptions and trade-offs

- **Single application per batch.** The batch endpoint checks many labels
  against one application record. That covers the Seattle importer case
  Sarah mentioned (same importer dumping 200+ related labels). Matching
  labels to distinct applications by filename would need a CSV upload
  path; the schema and the frontend leave room for it but it isn't wired.
- **No COLA integration.** Per Marcus, that would need its own authorization
  and 18 months of FedRAMP paperwork. This is a standalone proof of concept.
- **The vision model can be wrong.** Every check surfaces what the model
  believes it saw, so an agent can catch bad extractions. `image_quality_notes`
  is surfaced prominently when the model reports glare, blur, or skew.
- **Warning check is text-based.** True verification of "bold" and "specific
  font size" requires layout analysis beyond what a single vision call
  reliably delivers. The prototype detects the all-caps `GOVERNMENT WARNING:`
  header and the full required phrase set, which catches the common
  violations Jenny described. Font-size / weight verification would be a
  next iteration.
- **8 MB per image, 25 per batch.** Bounds latency and cost per request.
- **No auth.** Prototype only. Any production deployment needs SSO and
  audit logging, plus the usual FedRAMP treatment Marcus mentioned.

## Testing

Compliance logic is covered by pytest cases in `tests/test_compliance.py`,
including the specific scenarios raised in the interview notes (Dave's
casing case, Jenny's title-case warning rejection, ABV parsing, unit
conversion, and import handling). Vision extraction is mocked by
constructing `LabelExtraction` objects directly so tests run without an
API key.

## Layout

```
app/
  main.py          # FastAPI routes
  vision.py        # Claude vision extraction
  compliance.py    # comparison rules and verdict logic
  schemas.py       # pydantic models
  templates/
    index.html     # single-page UI
  static/
    style.css
    app.js
tests/
  test_compliance.py
render.yaml        # Render blueprint
requirements.txt
```
