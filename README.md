# Auto-Lectio :book:
Generate Mass slides automatically (USCCB → JSON → PPTX)

## What it does
- Fetches daily (ES) readings from USCCB RSS.
- Parses HTML into placeholders and chunked bodies.
- Renders a PPTX from a template, replacing placeholders and using a “waterfall” to duplicate long readings into multiple slides.

## Code map
- `fetch.py`: RSS fetcher, HTML parser, liturgical reference formatter, chunk generator, JSON writer.
- `render.py`: PPTX renderer, placeholder replacer, waterfall slide duplicator, hymn/song merger.
- `web/app.py`: Flask UI and JSON API for fetch/render/upload.
- `web/templates/index.html`: basic browser UI.
- `songs/parts/`: fixed JSON snippets for Kyrie, Sanctus, Agnus, and Mysterium.
- `templates/README.md`: template authoring guide.
- `docs/CODEBASE.md`: maintenance notes and current architecture for future agents.

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

3) Render basic (auto-picks Sunday/Daily template from `templates/`):
   - `venv/bin/python render.py --json out/YYYY-MM-DD.es-US.json --out build/YYYY-MM-DD.es-US.pptx`
   - Use a custom templates directory: `--template-root /templates`
   - Or point directly to a template file/dir: `--template /templates/sunday-ord` or `--template /templates/daily-ord.pptx`
   - Provide hymn lyrics (chunked) via: `--songs songs/sample.es-US.json`

4) Render with logs + timestamped filename:
   - `venv/bin/python render.py --verbose --json out/YYYY-MM-DD.es-US.json --out build/YYYY-MM-DD.es-US.pptx --stamp`

The renderer prints the final output path (with timestamp when `--stamp` is used).

## Minimal Web UI

Run a tiny Flask UI to fetch + render:

- Local: `venv/bin/pip install flask && venv/bin/python web/app.py` then open http://127.0.0.1:5000
- Docker: `docker compose up --build` then open http://127.0.0.1:8000

The UI lives in `web/templates/index.html` and calls backend endpoints:

- `POST /fetch` (build JSON)
- `POST /render` (render PPTX)
- `POST /run` (fetch + render)

Implementation note:
- `/fetch` imports and calls functions from `fetch.py` directly.
- `/render` shells out to `render.py` via `subprocess.run(...)` instead of importing renderer functions.
- `/run` composes those two behaviors.

### Deploy behind Nginx (example)

Reverse proxy a path on your site to the container:

```
location /lectio/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

Then visit `https://your-domain/lectio/`.

### Upload limits and timeouts
- The UI allows uploading custom `.pptx` templates. Max size is set to 65 MB.
- Cloudflare (proxied) max upload size is typically 100 MB on Free/Pro/Business; 65 MB is within that cap.
- Cloudflare’s 100-second response timeout may apply; very slow connections could hit this. The container sets Gunicorn timeout to 180s to avoid backend timeouts.
- If you proxy via Nginx, set `client_max_body_size 65m;` in your site config.

## Placeholders
See `AGENTS.md` for the full list and behavior.

### Hymn Lyrics (Songs JSON)
- New hymn lyric placeholders (lyrics only, no titles):
  - `{ENTRANCE_TXT}`, `{KYRIE_TXT}`, `{OFFERTORY_TXT}`, `{SANCTUS_TXT}`, `{MYSTERIUM_TXT}`, `{AGNUS_TXT}`, `{COMMUNION_TXT}`, `{RECESSIONAL_TXT}`.
 - Optional hymn references (simple text placeholders):
   - `{ENTRANCE_REF}`, `{OFFERTORY_REF}`, `{COMMUNION_REF}`, `{RECESSIONAL_REF}`.
- Provide pre-chunked lyrics via a songs JSON file and pass it with `--songs`.
- Example: `songs/sample.es-US.json`.
- Rendering duplicates the seed slide per chunk (waterfall) and preserves explicit line breaks within each chunk.

Pre-baked fixed parts
- Ready-to-use snippets for Kyrie/Sanctus/Agnus and Mysterium (ES/LA, 3 options) live under `songs/parts/` as JSON files (e.g., `songs/parts/kyrie.es.json`, `songs/parts/mysterium.es.2.json`). These can be merged into a songs JSON by copying their `chunks` entries.
 - The web UI auto-loads these parts based on your selections and can include song references in the `placeholders` section of the generated songs JSON.

## Notes
- Templates live under `templates/` by default. The renderer auto-selects:
  - `sunday-ord(.pptx)` for Sundays
 - `daily-ord(.pptx)` for weekdays
  You can override with `--template` (file or directory) or `--template-root`.
  - Provide hymn lyrics with `--songs songs/sample.es-US.json`.
- We avoid deleting slides to keep the PPTX package consistent. If a reading is missing, placeholders are blanked and slides can be left in place or hidden later.

## Maintenance
- The renderer currently replaces placeholders at the run level, not by rebuilding a whole paragraph. If PowerPoint splits a token across runs, replacement can fail.
- Slide duplication in `render.py` uses private `python-pptx` internals and XML deep copies. That is the highest-risk area in the codebase.
- `templates/README.md` documents the supported placeholder contract for template authors; keep it in sync with `web/app.py`'s `PLACEHOLDER_HELP` and `render.py`'s `waterfall_keys`.

## Troubleshooting
- Verbose logs: run with `--verbose` to print the chosen template path, initial placeholder slide positions (1-based), waterfall seed/sequence indices, and short text previews. This helps correlate PowerPoint slide numbers with renderer operations.
- No repair prompt: avoid deleting slides. The renderer blanks missing-reading placeholders instead of deleting slides to prevent duplicate slide-part names and “repair” warnings.
- Slide order shifts: seeds are processed in descending index to minimize index shifting. Logs report final sequence indices so you can confirm where duplicates land.
- Psalm splitting: renderer ignores global chunking for Psalms and alternates refrain/verse slides. If verses look too short, ask to enable verse-only min/merge rules.
- Short slides (<100 chars): non-Psalm waterfalls enforce ~100–140 characters by merging adjacent chunks when it fits. If you want stricter packing, request multi-sentence repacking.
- Newlines/spacing: renderer removes manual newlines and collapses whitespace so PowerPoint manages wrapping. If you need explicit breaks for a template, we can whitelist sections.
- Seeds not found: logs will say “No seed for {TOKEN}”; the renderer falls back to simple replacement across the deck. Verify the exact placeholder token text in the template matches what `fetch.py` emits.
- Moved placeholders: if a future placeholder appears in a duplicated slide, confirm the seed slide only contains the target token. Use `--verbose` snapshots to list tokens present on each slide.
