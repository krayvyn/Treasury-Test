# TTB Label Review — prototype

A working prototype for the interview task: upload an alcohol beverage label,
compare it against a COLA-style application record, get a plain-English
verdict in about 3–5 seconds.

**Live:** https://treasury-test-ny3g.onrender.com
**Repo:** https://github.com/krayvyn/Treasury-Test

---

## What it does

1. Reviewer drops a label image (or picks a baked-in sample).
2. Optionally enters application details (brand, ABV, net contents, etc.).
3. The server preprocesses the image, extracts fields with Claude vision,
   and runs a deterministic rule engine against the application data.
4. UI shows a stamp (Approved / Needs review / Rejected), a per-field
   comparison table, and a plain-English reason for every check.

There's a batch page (`/batch`) that runs up to 50 labels in parallel with a
filter chip UI for triage.

## Design decisions, mapped to the interview notes

| Interview point | How it's addressed |
|---|---|
| Sarah: "if we can't get results back in about 5 seconds, nobody's going to use it" | Single Claude vision call per label. Preprocessed images sized to the sweet spot. Timing badge on every result surfaces the number. |
| Sarah: "something my mother could figure out" | One big drop zone, one primary button. Application form is collapsed by default. Every field on the results page shows both values and a plain-English reason — no jargon, no icons that need decoding. |
| Sarah: "batch uploads would be huge" | `/batch` page, `POST /api/batch`, bounded parallelism (default 4), filter chips (All / Rejected / Review / Passed). |
| Dave: "'STONE'S THROW' vs 'Stone's Throw' is obviously the same" | `validators._normalize` collapses case, curly quotes, and punctuation before comparing. The result explicitly says "matches after normalizing case and punctuation" so the reviewer can see it wasn't an exact match. |
| Dave: "don't make my life harder" | Zero configuration required. Drag, click, done. No account, no state. |
| Jenny: "'GOVERNMENT WARNING:' has to be all caps and bold" | The warning is checked on three separable axes: mandatory wording match, all-caps heading, and bold face. Each failure mode names itself in the reason string. |
| Jenny: "AI could handle bad photos" | `preprocessing.py` fixes EXIF orientation, autocontrasts, mild sharpness, resize into the vision model's sweet spot. If the model still can't read it, we short-circuit to a "Needs review — ask for a re-shoot" verdict instead of cascading false-fails. |
| Marcus: "network blocks a lot of outbound domains" | Only one outbound host (`api.anthropic.com`). No third-party CDNs at request time except Google Fonts, which can be self-hosted for a hardened deployment. |
| Marcus: "just don't do anything crazy" with PII | Nothing is persisted. Files live only in the request lifetime. `no labels are retained` is stated in the footer. |

## Architecture

```
app/
  main.py           FastAPI routes: /, /batch, /api/analyze, /api/batch, /api/sample/{id}
  preprocessing.py  EXIF fix, autocontrast, resize (Pillow)
  vision.py         Claude vision extraction, JSON coercion, error wrapping
  validators.py     Deterministic rule engine + fuzzy matching
  models.py         Pydantic contracts shared by extraction, validation, UI
  samples.py        Baked-in demo applications
  templates/        Jinja2 (base, index, batch)
  static/           CSS, JS, sample images
tests/
  test_validators.py  Covers Dave's case, Jenny's warning check, ABV tolerance
  test_vision.py      Response-parsing tolerance
```

Two things worth calling out about the architecture:

- **Model contracts are the single source of truth.** `ExtractedLabel`,
  `ApplicationRecord`, and `LabelReview` are defined in one place. The
  Claude prompt, the rule engine, and the templates all bind to those
  shapes, so drift shows up as a Pydantic validation error rather than a
  silent field mismatch.

- **The rule engine is deterministic and unit-testable.** Anything that
  can be checked without the vision model — normalization, ABV tolerance,
  warning-statement rules — lives in `validators.py` and has no network
  dependency. That's what the tests exercise.

## Setup

Requires Python 3.12+.

```bash
git clone https://github.com/krayvyn/Treasury-Test.git
cd Treasury-Test
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # then paste your ANTHROPIC_API_KEY
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000.

Run the tests:

```bash
pytest
```

## Deploying to Render

`render.yaml` is committed at the repo root. Point Render at the repo, set
`ANTHROPIC_API_KEY` in the dashboard (not committed), and it deploys.
Health check is at `/healthz`.

## Render Optimization
**Free-tier performance tuning.** Initial warm-request timing on Render's
  0.1 vCPU free tier was ~18s per label using PNG + LANCZOS preprocessing
  and `max_tokens=1500` on the vision response. Profiling showed the CPU
  was spending most of that time on Pillow encode and waiting for the
  larger token stream. Switching to JPEG output, BILINEAR resize, and
  `max_tokens=800` brought warm requests under the 5s bar Sarah called out.
  First request after 15 min idle still takes ~20s to wake the container
  — a free-tier artifact, not a production concern.

## Assumptions and trade-offs

- **One vision call per label.** A cheaper OCR-first pipeline is possible
  (Tesseract → LLM only for warning text), but it doubles the moving parts
  and the interview notes emphasized speed and clarity, not cost.
- **Application data is optional.** If the reviewer doesn't fill in the
  form, the tool still extracts every field and shows what's on the label.
  Comparison checks then read as "shown on the label but not declared."
- **No persistence.** Not appropriate for a prototype crossing PII
  considerations. Every request is stateless.
- **Fuzzy match thresholds** (`STRONG_MATCH=0.92`, `WEAK_MATCH=0.78`) are
  tuned to accept Dave's case and reject outright typos. They're constants
  at the top of `validators.py` — easy to move to config if a future
  deployment wants to tune them per beverage class.
- **Sample images** live in `app/static/samples/`. Four samples are
  registered in `samples.py`. If the corresponding image files aren't
  committed, the sample endpoint returns a helpful 500 rather than
  silently failing.

## What's missing that a production build would need

Kept out of scope by design, called out here so the reviewer knows they
weren't overlooked:

- FedRAMP / FISMA compliance work for the hosting environment.
- COLA integration (Marcus explicitly scoped this out: "this is a
  standalone proof-of-concept").
- Audit logging for every review decision.
- User authentication and role separation.
- Class-specific ABV tolerances (currently a single 0.3% window; spirits
  is 0.15%, wine is 1.0–1.5%, beer is 0.3% — the code path is ready for it
  in `_abv_check`).
- Rate-limit handling for large batches beyond what the semaphore covers.
-
   
