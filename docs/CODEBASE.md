# Codebase Guide

This file is for future maintainers and agents. It describes the code as implemented now, not just the intended design.

## High-level flow

1. `fetch.py` downloads the USCCB Spanish RSS feed (`https://bible.usccb.org/lecturas.rss`).
2. It picks the item whose link contains the target date in `mmddyy` form.
3. It parses `item.description` HTML into `(header, body)` sections by pairing each `<h4>` with the next sibling `<div class="poetry">`.
4. It converts those sections into:
   - `placeholders`: simple text replacements for the PPTX template
   - `chunks`: pre-split reading bodies for waterfall slides
5. `render.py` loads the JSON payload and an input template.
6. It replaces simple tokens across the deck.
7. It expands waterfall tokens by duplicating a seed slide and replacing only the body token per duplicate.
8. The output PPTX is written to `build/`.

The web UI in `web/app.py` is a thin wrapper around that process.

## File responsibilities

### `fetch.py`

Primary responsibilities:
- date parsing and RSS item selection
- HTML cleanup and section extraction
- liturgical phrasing for reading references
- acclamation cleanup
- sentence/clause/word chunking
- JSON payload creation

Important functions:
- `pick_item(entries, target_mmddyy)`: date match by substring in the RSS item link
- `parse_sections(desc_html)`: extracts `(header, body)` pairs
- `to_placeholders(item_title, sections)`: maps parsed sections to the template contract
- `chunkify(text, max_chars=140, min_chars=100)`: sentence-first chunking for long text
- `make_chunks(placeholders)`: only chunks the reading body tokens

Notable behavior:
- First and second reading references are normalized into spoken Mass phrasing, not copied verbatim from the feed.
- `{ACCLAMATION_TXT}` removes `R.` and `Aleluya` lines.
- `build_payload(...)` normalizes whitespace in both placeholders and chunks.

### `render.py`

Primary responsibilities:
- template selection
- placeholder replacement
- songs JSON merge
- waterfall slide duplication
- PPTX output writing

Important functions:
- `resolve_template_path(args, payload)`: picks `sunday-ord` vs `daily-ord`
- `replace_tokens_in_slide(...)`: run-level replacement inside text frames and table cells
- `chunk_psalm_text(text)`: splits the psalm into refrain/verse alternation
- `duplicate_slide_filtered(...)`: duplicates a seed slide by copying selected XML shapes

Actual rendering order:
1. Load payload and optional songs JSON.
2. Merge song references into `placeholders` if the main payload does not already define them.
3. Replace all non-waterfall tokens on every slide.
4. Find seed slides for each waterfall token.
5. Process seeds in descending slide index.
6. Replace the seed token with chunk 1 and duplicate the seed for chunks 2..N.

Waterfall tokens currently include:
- Readings: `{FIRST_READING_TXT}`, `{PSALM_TXT}`, `{SECOND_READING_TXT}`, `{GOSPEL_TXT}`
- Hymns/fixed sung parts: `{ENTRANCE_TXT}`, `{KYRIE_TXT}`, `{GLORIA_TXT}`, `{OFFERTORY_TXT}`, `{SANCTUS_TXT}`, `{MYSTERIUM_TXT}`, `{AGNUS_TXT}`, `{COMMUNION_TXT}`, `{RECESSIONAL_TXT}`

Notable behavior:
- Psalm chunking is regenerated from the raw psalm text at render time, even if the JSON already contains psalm chunks.
- Hymn chunks preserve newlines; reading chunks are flattened to spaces.
- Missing content is blanked out. The current code avoids deleting slides.

### `web/app.py`

Primary responsibilities:
- serve the minimal UI
- expose `/fetch`, `/render`, `/run`, `/upload`, `/placeholders`
- synthesize a songs JSON from UI form data

Architecture note:
- `/fetch` imports `fetch.py` functions directly.
- `/render` does not import `render.py`; it shells out to the CLI with `subprocess.run(...)`.
- `/run` fetches first, then renders.

This means renderer changes must be tested through the CLI path, even when the UI is the user-facing entry point.

## Current template contract

Core placeholders:
- `{LITURGICAL_DAY}`
- `{FIRST_READING_REF}`, `{FIRST_READING_TXT}`
- `{PSALM_REF}`, `{PSALM_TXT}`
- `{SECOND_READING_REF}`, `{SECOND_READING_TXT}`
- `{ACCLAMATION_REF}`, `{ACCLAMATION_TXT}`
- `{GOSPEL_REF}`, `{GOSPEL_TXT}`

Hymn/fixed-part placeholders:
- `{ENTRANCE_TXT}`, `{KYRIE_TXT}`, `{GLORIA_TXT}`, `{OFFERTORY_TXT}`, `{SANCTUS_TXT}`
- `{MYSTERIUM_TXT}`, `{AGNUS_TXT}`, `{COMMUNION_TXT}`, `{RECESSIONAL_TXT}`
- optional refs: `{ENTRANCE_REF}`, `{OFFERTORY_REF}`, `{COMMUNION_REF}`, `{RECESSIONAL_REF}`

For custom templates, the safest assumption is still one seed slide per waterfall token.

## Fragile spots

### Placeholder replacement

The code does run-level replacement, not paragraph-level reconstruction. If PowerPoint splits a token across multiple runs, replacement may fail. Template authors should keep each token as a single contiguous text run when possible.

### Slide duplication

`duplicate_slide_filtered(...)` uses private `python-pptx` internals and XML deep-copying. It intentionally skips:
- shapes with image relationships
- shapes containing other known placeholder tokens

That filtering reduces package corruption and duplicate-token surprises, but it also means a duplicate slide may not be a byte-for-byte copy of the seed.

### Documentation sync points

When placeholder support changes, update these together:
- `render.py`: `waterfall_keys`, `known_tokens`, songs handling
- `web/app.py`: `PLACEHOLDER_HELP`
- `templates/README.md`
- `AGENTS.md` if the JSON or placeholder contract changes

## Suggested verification after renderer changes

1. Run `venv/bin/python fetch.py --date YYYY-MM-DD`.
2. Run `venv/bin/python render.py --json out/YYYY-MM-DD.es-US.json --out build/YYYY-MM-DD.es-US.pptx --verbose`.
3. Confirm:
   - no supported placeholders remain
   - long readings duplicate correctly
   - psalm alternates refrain and verse
   - hymn chunks render in order
   - PowerPoint opens the result without a repair prompt

## Known drift already corrected

Older docs said hymn placeholders were ignored. That is no longer true. The renderer supports hymn chunk waterfall expansion and optional hymn references from a songs JSON.
