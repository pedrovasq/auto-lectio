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
    - Acclamation: emits explicit placeholders for the response and the verse.
  - produces a JSON payload with:
    - `meta`
    - `placeholders` (strings)
    - `chunks` (dict of placeholder_key -> list of strings)

- `render.py` — PPTX renderer that:
  - uses OfficeCLI for PPTX mutation; local rendering requires `officecli` on PATH
  - copies the template to the requested output path before editing, so source templates are not mutated
  - fills placeholders across the deck
  - expands long bodies with a “waterfall” by duplicating the seed slide and changing only the body text
  - handles Psalm specially (alternating R. and verse slides)
  - sanitizes text (newlines → spaces; collapse whitespace)
  - rebalances non-Psalm reading chunks with a shared scoring-based chunker to avoid tiny orphan slides
  - supports verbose logging and timestamped output filenames
  - prunes empty optional sections by default, deleting missing second-reading or hymn/fixed-part slide sequences from the output copy
  - supports `--keep-empty-sections` to preserve the older blank-in-place behavior

## Placeholders in PPTX template
Template placeholders (exact tokens in text boxes):
- {LITURGICAL_DAY}
- {FIRST_READING_REF}
- {FIRST_READING_TXT}
- {PSALM_REF}
- {PSALM_TXT}
- {SECOND_READING_REF}
- {SECOND_READING_TXT}
- {ACCLAMATION_RES}
- {ACCLAMATION_VERSE}
- {GOSPEL_REF}
- {GOSPEL_TXT}
- Hymn lyrics (lyrics only; titles not displayed):
  - {ENTRANCE_TXT}, {KYRIE_TXT}, {GLORIA_TXT}, {OFFERTORY_TXT}, {SANCTUS_TXT}, {MYSTERIUM_TXT}, {AGNUS_TXT}, {COMMUNION_TXT}, {MEDITATION_TXT}, {RECESSIONAL_TXT}
  - Optional hymn references to display source/identifier:
    - {ENTRANCE_REF}, {OFFERTORY_REF}, {COMMUNION_REF}, {MEDITATION_REF}, {RECESSIONAL_REF}

Hymn lyrics are provided via a separate songs JSON file; fetcher does not supply them.

Optional OfficeCLI-native shape names for future templates:
- Simple placeholders may use text shape names like `AL_TOKEN_LITURGICAL_DAY`.
- Waterfall seed body placeholders may use names like `AL_SEED_FIRST_READING_TXT`.
- Existing literal `{TOKEN}` placeholders remain supported and are the compatibility path for current templates.

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
    "{ACCLAMATION_RES}": "...",
    "{ACCLAMATION_VERSE}": "...",
    "{GOSPEL_REF}": "...",
    "{GOSPEL_TXT}": "...",
    "{ENTRANCE_REF}": "Flor y Canto #123",
    "{OFFERTORY_REF}": "",
    "{COMMUNION_REF}": "",
    "{MEDITATION_REF}": "",
    "{RECESSIONAL_REF}": ""
  },
  "chunks": {
    "{FIRST_READING_TXT}": ["chunk1", "chunk2", ...],
    "{PSALM_TXT}": ["chunk1", ...],
    "{SECOND_READING_TXT}": ["chunk1", ...],
    "{GOSPEL_TXT}": ["chunk1", "chunk2", ...]
  }
}

Important: `chunks` is optional; if missing, render.py can fallback to the raw placeholder text.

Songs JSON:
- Provide hymn lyric chunks under a top-level `chunks` mapping with keys from the hymn placeholders above.
- Example path: `songs/sample.es-US.json`.
- Pass with `--songs` to `render.py`.
 - You may also provide simple `placeholders` in the songs JSON (e.g., `{ENTRANCE_REF}`), which will be merged into the render placeholders.

Fixed parts library:
- Pre-baked JSON snippets live under `songs/parts/`:
  - `kyrie.{es|la}.json`, `sanctus.{es|la}.json`, `agnus.{es|la}.json`, `mysterium.{es|la}.{1|2|3}.json`.
  - The web UI uses these files based on your language/version selection.

## Render Plan (render.py)
### Inputs
- template PPTX path (e.g., `template.pptx`)
- payload JSON path (e.g., `out/2025-12-16.es-US.json`)
- output PPTX path (e.g., `build/2025-12-16.es-US.pptx`)
 - optional songs JSON path (e.g., `songs/sample.es-US.json`)

### Output
- A PPTX where placeholders are replaced
- Long readings are expanded into multiple slides using waterfall duplication
 - Hymn lyric placeholders are filled from songs JSON; each chunk produces a duplicate slide, preserving line breaks

## Key Implementation Notes (OfficeCLI)
### 1) Finding placeholders reliably
The renderer uses read-only PPTX ZIP inspection to find seed slides containing literal `{TOKEN}` text or matching `AL_SEED_*` shape names. OfficeCLI performs the actual replacement and can handle normal PowerPoint run fragmentation better than the previous renderer.

### 2) Replacing text
Use OfficeCLI scoped find/replace:
- whole deck for simple placeholders: `officecli set deck.pptx / --find TOKEN --replace VALUE`
- specific slide for waterfall body chunks: `officecli set deck.pptx '/slide[N]' --find TOKEN --replace VALUE`

### 3) “Waterfall” slide duplication
We clone the seed/tail slide with OfficeCLI and insert each clone immediately after the current tail. Only the target body token text is changed per duplicate; all other placeholders on that slide remain as previously filled.

Implementation notes:
- Always edit the output copy, never the source template.
- Use `officecli open` before a render batch and `officecli close` before returning control to non-OfficeCLI readers.
- Clone with `officecli add deck.pptx / --from '/slide[N]' --after '/slide[N]'`.

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
1) Copy the template to the output path.
2) Prune empty optional sections unless `--keep-empty-sections` is used:
   - Missing `{SECOND_READING_TXT}` removes its ref slide, body seed, matching “Palabra de Dios / Te alabamos” response slide, and immediate blank spacer slides.
   - Missing hymn/fixed-part lyric tokens remove their seed slide and immediate blank spacer slides.
3) Replace all *simple* placeholders across all slides:
   - {LITURGICAL_DAY}, all simple placeholders (including hymn refs and acclamation response/verse), etc.
4) Apply waterfall expansion for:
   - {FIRST_READING_TXT}
   - {PSALM_TXT}
   - {SECOND_READING_TXT}
   - {GOSPEL_TXT}
In step (4), do it in slide index order, because inserting slides shifts indices. Work from start to end:
- Find seed slide indices first (by scanning once),
- Then process from lowest index to highest.

### 6) Text normalization
- Renderer strips newlines and collapses whitespace so text wraps naturally inside text boxes.
- Non-Psalm readings use a shared balanced chunker with a wider soft target so the slideshow has fewer abrupt slide changes; Psalm uses R./verse alternation.

### 7) Logging and timestamps
- `--verbose` logs initial placeholder positions, waterfall seed/sequence indices, and short text previews per slide.
- `--stamp` appends a `YYYYmmdd-HHMMSS` suffix to the output filename and updates core modified metadata.
 - The renderer prints which hymn tokens and references were detected when `--verbose` is on.

## What “done” looks like for the next milestone
- `render.py` loads a JSON payload + template PPTX.
- Produces an output PPTX where:
  - {LITURGICAL_DAY} filled
  - all *_REF placeholders filled
  - all *_TXT placeholders filled
  - for long readings, multiple slides are generated using waterfall duplication
- Hymn placeholders + Mystery of Faith can remain untouched for now.

## Common Pitfalls
- Slide indices shift after deletions and insertions: record seed locations before pruning, adjust them by the removed-slide set, then process seeds from highest slide number to lowest.
- Missing OfficeCLI: fail with a clear install/PATH message before copying or mutating output.
- Placeholder seed discovery still expects literal `{TOKEN}` text in the slide XML.
- Do not edit user template PPTX files directly; duplicate them for experiments.

## Quick CLI
- Fetch (today): `venv/bin/python fetch.py`
- Fetch (specific date): `venv/bin/python fetch.py --date 12-14-25`
- Render (auto-pick Sunday/Daily): `venv/bin/python render.py --json out/YYYY-MM-DD.es-US.json --out build/YYYY-MM-DD.es-US.pptx`
  - Override templates dir: `--template-root /templates`
  - Force specific template: `--template /templates/sunday-ord` or `--template /templates/daily-ord.pptx`
  - Provide hymn lyrics: `--songs songs/sample.es-US.json`
  - Preserve empty optional-section slides: `--keep-empty-sections`
- Render (verbose + timestamp): `venv/bin/python render.py --verbose --json out/YYYY-MM-DD.es-US.json --out build/YYYY-MM-DD.es-US.pptx --stamp`

## Testing Checklist
- Run fetcher for today -> JSON created
- Run renderer -> PPTX opens in PowerPoint without repair warnings
- First Reading spans multiple slides (verify duplicates inserted)
- No missing {PLACEHOLDER} tokens remain for the supported set
