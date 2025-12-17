# AGENTS.md — Auto-Lectio (USCCB → JSON → PPTX)

## Goal
Auto-generate a Catholic Mass slideshow for a given day by:
1) Fetching daily readings from the USCCB RSS feed (Spanish pages).
2) Parsing the HTML into structured text.
3) Chunking long readings into slide-sized pieces.
4) Rendering a PPTX by replacing placeholders in a template.
5) For long readings, use a **“waterfall”** technique:
   - One placeholder slide acts as a seed.
   - Fill it with chunk 1.
   - Duplicate that slide as many times as needed, insert immediately after it, and fill chunk 2..N.

## Current State (what exists)
We have two main scripts:

- `fetch.py` — RSS fetcher + parser that:
  - downloads `https://bible.usccb.org/lecturas.rss`
  - picks the item for a target date using the `mmddyy` token in the item link
  - parses `item.description` (HTML) into sections by pairing `<h4>` headers with `<div class="poetry">` bodies
  - normalizes text (line endings, whitespace), and chunkifies long bodies
  - formats reading intros for liturgical usage:
    - First Reading: “Lectura del profeta …” for prophets, “Lectura del libro de los Hechos…”, feminine articles (Sabiduría), etc.
    - Second Reading: “Lectura de la (primera/segunda) carta del apóstol san Pablo a los …”, “Lectura de la carta a los Hebreos”, “Lectura del libro del Apocalipsis”, “Lectura de la (primera/…) carta del apóstol san Juan/Pedro”, “Lectura de la carta del apóstol Santiago/Judas”, etc.
    - Gospel ref simplified to just the book name.
    - Acclamation: keeps only the verse (strips “R.”/Aleluya) and attempts a short reference when possible.
  - produces a JSON payload with:
    - `meta`
    - `placeholders` (strings)
    - `chunks` (dict of placeholder_key -> list of strings)

- `render.py` — PPTX renderer that:
  - fills placeholders across the deck
  - expands long bodies with a “waterfall” by duplicating the seed slide and changing only the body text
  - handles Psalm specially (alternating R. and verse slides)
  - sanitizes text (newlines → spaces; collapse whitespace)
  - enforces chunk length (non-Psalm) to ~100–140 chars by merging short chunks
  - supports verbose logging and timestamped output filenames
  - avoids slide deletion (to prevent repair prompts); blanks placeholders when a reading is absent

## Placeholders in PPTX template
Template placeholders (exact tokens in text boxes):
- {LITURGICAL_DAY}
- {ENTRANCE_HYMN} (ignore for now)
- {FIRST_READING_REF}
- {FIRST_READING_TXT}
- {PSALM_REF}
- {PSALM_TXT}
- {SECOND_READING_REF}
- {SECOND_READING_TXT}
- {ACCLAMATION_REF}
- {ACCLAMATION_TXT}
- {GOSPEL_REF}
- {GOSPEL_TXT}
- {OFFERTORY_HYMN} (ignore for now)
- {MYSTERY_OF_FAITH} (ignore for now)
- {COMMUNION_HYMN} (ignore for now)
- {RECESSIONAL_HYMN} (ignore for now)

For now: only fill day + readings/psalm/acclamation/gospel (refs + texts).

## JSON Contract (expected)
Example shape:

{
  "meta": {
    "date": "2025-12-16",
    "language": "es-US",
    "source": "usccb_rss",
    "link": "https://bible.usccb.org/es/bible/lecturas/121625.cfm",
    "title": "Martes de la ...",
  },
  "placeholders": {
    "{LITURGICAL_DAY}": "...",
    "{FIRST_READING_REF}": "Primera lectura ...",
    "{FIRST_READING_TXT}": "…\n\n…",
    "{PSALM_REF}": "...",
    "{PSALM_TXT}": "...",
    "{SECOND_READING_REF}": "...",
    "{SECOND_READING_TXT}": "...",
    "{ACCLAMATION_REF}": "...",
    "{ACCLAMATION_TXT}": "...",
    "{GOSPEL_REF}": "...",
    "{GOSPEL_TXT}": "..."
  },
  "chunks": {
    "{FIRST_READING_TXT}": ["chunk1", "chunk2", ...],
    "{PSALM_TXT}": ["chunk1", ...],
    "{SECOND_READING_TXT}": ["chunk1", ...],
    "{GOSPEL_TXT}": ["chunk1", "chunk2", ...]
  }
}

Important: `chunks` is optional; if missing, render.py can fallback to the raw placeholder text.

## Render Plan (render.py)
### Inputs
- template PPTX path (e.g., `template.pptx`)
- payload JSON path (e.g., `out/2025-12-16.es-US.json`)
- output PPTX path (e.g., `build/2025-12-16.es-US.pptx`)

### Output
- A PPTX where placeholders are replaced
- Long readings are expanded into multiple slides using waterfall duplication

## Key Implementation Notes (python-pptx)
### 1) Finding placeholders reliably
Placeholders might appear:
- in a single run
- or split across multiple runs (PowerPoint can fragment runs)

Minimum viable approach (good enough if placeholders are typed as a single run):
- iterate slides -> shapes -> text_frame -> paragraphs -> runs
- if a run contains `{FIRST_READING_TXT}`, replace

More robust approach (recommended):
- operate at paragraph level:
  - `full = "".join(run.text for run in paragraph.runs)`
  - if placeholder token is in `full`, then:
    - clear all runs
    - set paragraph.text to replaced text
This avoids issues with split runs.

### 2) Replacing text in a shape
Prefer setting `text_frame.text` only if you’re okay losing per-run styling.
If you need to preserve formatting, change only the paragraph that contains the placeholder.

For our first pass, it’s acceptable to lose styling inside the reading body textbox as long as the template is designed accordingly.

### 3) “Waterfall” slide duplication
We duplicate the seed slide (same layout + copied shapes) and insert it immediately after the seed. Only the target body token text is changed per duplicate; all other placeholders on that slide remain as previously filled.

Implementation notes:
- Create a new slide with the same layout and move it to sit right after the seed by targeting the slide’s specific relationship id (not “last slide”).
- Copy shapes from the seed slide into the new slide to preserve formatting. To avoid repair prompts, we avoid deleting slides from the deck and keep per-slide relationships intact.

### 4) Waterfall algorithm (per placeholder key)
For each long-text placeholder that supports chunking:
- locate the slide(s) containing that placeholder token (expect exactly one “seed” slide per reading text)
- let chunks = payload["chunks"].get(placeholder, [payload["placeholders"][placeholder]])
- replace placeholder on seed slide with chunks[0]
- for each subsequent chunk (1..N-1):
  - duplicate the seed slide
  - insert duplicate immediately after the previous inserted slide
  - replace placeholder on duplicated slide with that chunk
Also ensure other placeholders on that slide (like `{FIRST_READING_REF}`) remain filled.

### 5) Rendering order
Recommended order:
1) Replace all *simple* placeholders across all slides:
   - {LITURGICAL_DAY}, all *_REF, {ACCLAMATION_TXT} if not waterfall, etc.
2) Apply waterfall expansion for:
   - {FIRST_READING_TXT}
   - {PSALM_TXT}
   - {SECOND_READING_TXT}
   - {GOSPEL_TXT}
In step (2), do it in slide index order, because inserting slides shifts indices. Work from start to end:
- Find seed slide indices first (by scanning once),
- Then process from lowest index to highest.

### 6) Text normalization
- Renderer strips newlines and collapses whitespace so text wraps naturally inside text boxes.
- Non-Psalm waterfalls enforce ~100–140 characters per chunk; Psalm uses R./verse alternation.

### 7) Logging and timestamps
- `--verbose` logs initial placeholder positions, waterfall seed/sequence indices, and short text previews per slide.
- `--stamp` appends a `YYYYmmdd-HHMMSS` suffix to the output filename and updates core modified metadata.

## What “done” looks like for the next milestone
- `render.py` loads a JSON payload + template PPTX.
- Produces an output PPTX where:
  - {LITURGICAL_DAY} filled
  - all *_REF placeholders filled
  - all *_TXT placeholders filled
  - for long readings, multiple slides are generated using waterfall duplication
- Hymn placeholders + Mystery of Faith can remain untouched for now.

## Common Pitfalls
- Slide indices shift after insertions: either process in increasing index and update indices carefully, or precompute seed locations and insert relative to current position.
- Placeholder tokens split across runs: use paragraph-level string rebuild to find/replace.
- Duplicating slides in python-pptx needs private APIs; isolate in `duplicate_slide(prs, slide_index, insert_after_index)` and keep it tested.
- Styling loss when setting `text_frame.text`: acceptable for now if the template is designed with a single textbox style.

## Quick CLI
- Fetch (today): `venv/bin/python fetch.py`
- Fetch (specific date): `venv/bin/python fetch.py --date 12-14-25`
- Render (basic): `venv/bin/python render.py --template template.pptx --json out/YYYY-MM-DD.es-US.json --out build/YYYY-MM-DD.es-US.pptx`
- Render (verbose + timestamp): `venv/bin/python render.py --verbose --template template.pptx --json out/YYYY-MM-DD.es-US.json --out build/YYYY-MM-DD.es-US.pptx --stamp`

## Testing Checklist
- Run fetcher for today -> JSON created
- Run renderer -> PPTX opens in PowerPoint without repair warnings
- First Reading spans multiple slides (verify duplicates inserted)
- No missing {PLACEHOLDER} tokens remain for the supported set
