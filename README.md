# Auto-Lectio :book:
Generate Mass slides automatically (USCCB → JSON → PPTX)

## What it does
- Fetches daily (ES) readings from USCCB RSS.
- Parses HTML into placeholders and chunked bodies.
- Renders a PPTX from a template, replacing placeholders and using a “waterfall” to duplicate long readings into multiple slides.

## Key features
- Liturgical intros:
  - First Reading: “Lectura del profeta …”, “Lectura del libro de los Hechos…”, feminine articles (Sabiduría), etc.
  - Second Reading: Paul’s letters with ordinals, Hebrews, Revelation, 1–3 John, 1–2 Peter, Santiago/Judas, etc.
  - Gospel reference simplified to book name.
  - Acclamation keeps only the verse (strips “R.”/Aleluya) and extracts a short reference when present.
- Waterfall duplication: duplicates the seed slide and changes only the body text; preserves formatting; inserts immediately after the seed.
- Psalm handling: alternates R. (refrain) and verse blocks as separate slides.
- Text normalization: removes manual newlines, collapses whitespace so PowerPoint wraps naturally.
- Chunk sizing: targets ~100–140 chars for non-Psalm waterfalls (merges short chunks when possible).
- No slide deletions (avoids repair prompts); blanks placeholders if a reading is absent.
- Verbose logging and timestamped outputs for traceability.

## Quick start
Assumes a virtualenv `venv` with dependencies installed (python-pptx, feedparser, beautifulsoup4).

1) Fetch today:
   - `venv/bin/python fetch.py`

2) Fetch specific date:
   - `venv/bin/python fetch.py --date 12-14-25`

3) Render basic:
   - `venv/bin/python render.py --template template.pptx --json out/YYYY-MM-DD.es-US.json --out build/YYYY-MM-DD.es-US.pptx`

4) Render with logs + timestamped filename:
   - `venv/bin/python render.py --verbose --template template.pptx --json out/YYYY-MM-DD.es-US.json --out build/YYYY-MM-DD.es-US.pptx --stamp`

The renderer prints the final output path (with timestamp when `--stamp` is used).

## Placeholders
See `AGENTS.md` for the full list and behavior.

## Notes
- The canonical template is `template.pptx` (copied from `testtt.pptx`).
- We avoid deleting slides to keep the PPTX package consistent. If a reading is missing, placeholders are blanked and slides can be left in place or hidden later.

## Troubleshooting
- Verbose logs: run with `--verbose` to print initial placeholder slide positions (1-based), waterfall seed/sequence indices, and short text previews. This helps correlate PowerPoint slide numbers with renderer operations.
- No repair prompt: avoid deleting slides. The renderer blanks missing-reading placeholders instead of deleting slides to prevent duplicate slide-part names and “repair” warnings.
- Slide order shifts: seeds are processed in descending index to minimize index shifting. Logs report final sequence indices so you can confirm where duplicates land.
- Psalm splitting: renderer ignores global chunking for Psalms and alternates refrain/verse slides. If verses look too short, ask to enable verse-only min/merge rules.
- Short slides (<100 chars): non-Psalm waterfalls enforce ~100–140 characters by merging adjacent chunks when it fits. If you want stricter packing, request multi-sentence repacking.
- Newlines/spacing: renderer removes manual newlines and collapses whitespace so PowerPoint manages wrapping. If you need explicit breaks for a template, we can whitelist sections.
- Seeds not found: logs will say “No seed for {TOKEN}”; the renderer falls back to simple replacement across the deck. Verify the exact placeholder token text in the template matches what `fetch.py` emits.
- Moved placeholders: if a future placeholder appears in a duplicated slide, confirm the seed slide only contains the target token. Use `--verbose` snapshots to list tokens present on each slide.
