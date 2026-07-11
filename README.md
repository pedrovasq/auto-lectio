# Auto-Lectio :book:
Generate Mass slides automatically (USCCB → JSON → PPTX)

## What it does
- Fetches daily (ES) readings from USCCB RSS.
- Parses HTML into placeholders and chunked bodies.
- Renders a PPTX from a template, replacing placeholders and using a “waterfall” to duplicate long readings into multiple slides.

## Code map
- `fetch.py`: RSS fetcher, HTML parser, liturgical reference formatter, chunk generator, JSON writer.
- `chunking.py`: shared balanced reading chunker used by fetch and render.
- `render.py`: PPTX renderer, placeholder replacer, waterfall slide duplicator, hymn/song merger.
- `scripts/lint_template.py`: read-only PPTX template linter for placeholder coverage, duplicate seeds, and unsupported tokens.
- `scripts/inspect_pptx.py`: read-only PPTX inspector for rendered decks, remaining placeholders, and optional validation.
- `web/app.py`: Flask UI and JSON API for fetch/render/upload.
- `web/templates/home.html`: public landing page.
- `web/templates/docs.html`: public documentation page.
- `web/templates/guided.html`: minimal guided workflow for common use.
- `web/templates/advanced.html`: current advanced browser UI.
- `web/templates/base.html`: shared shell for the public pages.
- `web/static/site.css`: shared styles for the public pages.
- `songs/parts/`: fixed JSON snippets for Kyrie, Sanctus, Agnus, and Mysterium.
- `templates/README.md`: template authoring guide.
- `docs/CODEBASE.md`: maintenance notes and current architecture for future agents.

## Key features
- Liturgical intros:
  - First Reading: “Lectura del profeta …”, “Lectura del libro de los Hechos…”, feminine articles (Sabiduría), etc.
  - Second Reading: Paul’s letters with ordinals, Hebrews, Revelation, 1–3 John, 1–2 Peter, Santiago/Judas, etc.
  - Gospel reference simplified to book name.
  - Acclamation keeps the verse in the payload, extracts a short reference when present, and renders as a waterfall sequence: response, verse, response.
- Waterfall duplication: duplicates the seed slide and changes only the body text; preserves formatting; inserts immediately after the seed.
- Psalm handling: alternates R. (refrain) and verse blocks as separate slides.
- Text normalization: removes manual newlines, collapses whitespace so PowerPoint wraps naturally.
- Chunk sizing: uses a balanced sentence/clause chunker for non-Psalm readings, with a wider soft target to reduce tiny orphan slides.
- Empty optional-section pruning: missing second reading and hymn/fixed-part content removes the related placeholder slides and immediate spacer slides by default.
- Verbose logging and timestamped outputs for traceability.

## Quick start
Assumes a virtualenv `venv` with Python dependencies installed and the `officecli` binary on `PATH`.
Docker builds install OfficeCLI automatically.

1) Fetch today:
   - `venv/bin/python fetch.py`

2) Fetch specific date:
   - `venv/bin/python fetch.py --date 12-14-25`

3) Render basic (auto-picks Sunday/Daily template from `templates/`):
   - `venv/bin/python render.py --json out/YYYY-MM-DD.es-US.json --out build/YYYY-MM-DD.es-US.pptx`
   - Use a custom templates directory: `--template-root /templates`
   - Or point directly to a template file/dir: `--template /templates/sunday-ord` or `--template /templates/daily-ord.pptx`
   - Provide hymn lyrics (chunked) via: `--songs songs/sample.es-US.json`
   - Keep empty optional-section slides instead of pruning them: `--keep-empty-sections`

4) Render with logs + timestamped filename:
   - `venv/bin/python render.py --verbose --json out/YYYY-MM-DD.es-US.json --out build/YYYY-MM-DD.es-US.pptx --stamp`

The renderer prints the final output path (with timestamp when `--stamp` is used).

5) Lint a template before rendering:
   - `venv/bin/python scripts/lint_template.py templates/custom/domingo-jgv.pptx`
   - JSON output: `venv/bin/python scripts/lint_template.py templates/custom/domingo-jgv.pptx --json`
   - Strict + OfficeCLI validation: `venv/bin/python scripts/lint_template.py templates/custom/domingo-jgv.pptx --strict --validate`

6) Inspect a rendered deck:
   - `venv/bin/python scripts/inspect_pptx.py build/YYYY-MM-DD.es-US.pptx`
   - Show token locations: `venv/bin/python scripts/inspect_pptx.py build/YYYY-MM-DD.es-US.pptx --tokens`
   - Fail if supported placeholders remain: `venv/bin/python scripts/inspect_pptx.py build/YYYY-MM-DD.es-US.pptx --fail-on-remaining`

## Web UI

Run a tiny Flask UI to fetch + render:

- Local: `venv/bin/pip install flask && venv/bin/python web/app.py` then open http://127.0.0.1:5000
- Docker: `docker compose up --build` then open http://127.0.0.1:8000

Public pages:
- `/`: landing page
- `/docs`: documentation
- `/guided`: guided workflow
- `/advanced`: current advanced UI

Guided mode notes:
- Uses only dates currently available from the RSS feed.
- Sends ordinary acclamation mode by default.
- Assumes Kyrie, Gloria, Santo, and Cordero de Dios in Spanish.
- Lets the user choose the `Misterio de la fe` option and optionally add a few hymn lyric fields.

The advanced UI calls backend endpoints:

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
Existing `{TOKEN}` text placeholders remain supported. Future OfficeCLI-oriented templates can use shape names like `AL_TOKEN_LITURGICAL_DAY` and `AL_SEED_GOSPEL_TXT`; see `templates/README.md`.

### Hymn Lyrics (Songs JSON)
- New hymn lyric placeholders (lyrics only, no titles):
  - `{ENTRANCE_TXT}`, `{KYRIE_TXT}`, `{GLORIA_TXT}`, `{OFFERTORY_TXT}`, `{SANCTUS_TXT}`, `{MYSTERIUM_TXT}`, `{AGNUS_TXT}`, `{COMMUNION_TXT}`, `{MEDITATION_TXT}`, `{RECESSIONAL_TXT}`.
 - Optional hymn references (simple text placeholders):
   - `{ENTRANCE_REF}`, `{OFFERTORY_REF}`, `{COMMUNION_REF}`, `{MEDITATION_REF}`, `{RECESSIONAL_REF}`.
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
- Missing optional sections are pruned by default. If the second reading or a hymn/fixed-part lyric has no text/chunks, the renderer removes its placeholder slide(s) plus immediate spacer slides from the output copy. Use `--keep-empty-sections` to retain the older blank-in-place behavior.

## Maintenance
- The renderer mutates only an output copy of the template; source templates are not modified.
- PPTX editing is delegated to OfficeCLI. Placeholder discovery for diagnostics is read-only ZIP inspection.
- `templates/README.md` documents the supported placeholder contract for template authors; keep it in sync with `web/app.py`'s `PLACEHOLDER_HELP` and `render.py`'s `WATERFALL_KEYS`.

## Troubleshooting
- Verbose logs: run with `--verbose` to print the chosen template path, initial placeholder slide positions (1-based), waterfall seed/sequence indices, and short text previews. This helps correlate PowerPoint slide numbers with renderer operations.
- Missing OfficeCLI: install OfficeCLI and confirm `officecli --version` works before rendering locally.
- Template linting: run `scripts/lint_template.py` on a custom template before rendering. Missing core placeholders and duplicate waterfall seeds fail; missing second reading and hymn placeholders are warnings by default.
- Render inspection: run `scripts/inspect_pptx.py build/<output>.pptx --fail-on-remaining` after rendering to catch any supported placeholder tokens left in the deck.
- Empty-section pruning: run with `--verbose` to see which optional sections were removed. Use `--keep-empty-sections` if a custom template needs the old blanking behavior.
- Slide order shifts: seeds are processed in descending index to minimize index shifting. Logs report final sequence indices so you can confirm where duplicates land.
- Psalm splitting: renderer ignores global chunking for Psalms and alternates refrain/verse slides. If verses look too short, ask to enable verse-only min/merge rules.
- Short slides: non-Psalm readings now use a shared balancing pass in `chunking.py` that prefers fuller slides and avoids tiny remainders when possible.
- Newlines/spacing: renderer removes manual newlines and collapses whitespace so PowerPoint manages wrapping. If you need explicit breaks for a template, we can whitelist sections.
- Seeds not found: logs will say “No seed for {TOKEN}”; the renderer falls back to simple replacement across the deck. Verify the exact placeholder token text in the template matches what `fetch.py` emits.
- Moved placeholders: if a future placeholder appears in a duplicated slide, confirm the seed slide only contains the target token. Use `--verbose` snapshots to list tokens present on each slide.
