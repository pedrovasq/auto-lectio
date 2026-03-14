# TODO

## Testing

- Add `pytest` and create unit tests for pure fetch logic in `fetch.py`:
  - `classify`
  - `extract_book_phrase`
  - `first_reading_intro`
  - `second_reading_intro`
  - `normalize_acclamation_text`
  - `chunkify`
  - `chunking.chunk_text`
  - `chunking.rebalance_chunks`

- Add unit tests for pure render logic in `render.py`:
  - `chunk_psalm_text`
  - `resolve_template_path`
  - duplicate-seed validation for waterfall tokens
  - zero-seed behavior for optional waterfall tokens

- Add fixture-based renderer tests using a minimal `.pptx` template:
  - one seed slide per supported waterfall token
  - duplicate waterfall seed fixture that must fail
  - missing second-reading seed fixture that must skip cleanly
  - hymn/gloria seed fixture

- Add end-to-end golden tests:
  - fetch from saved RSS/item fixtures instead of the live feed
  - render from known JSON plus known template
  - assert expected slide counts after waterfall expansion
  - assert no supported placeholder tokens remain in the output deck

## Debugging Tools

- Add a template lint script, e.g. `scripts/lint_template.py`, that reports:
  - missing required tokens
  - duplicate waterfall seeds
  - unsupported tokens
  - placeholder tokens split across PowerPoint runs

- Add a rendered-deck inspection script, e.g. `scripts/inspect_pptx.py`, that:
  - prints slide count
  - prints supported placeholder occurrences by slide
  - fails if any supported placeholder remains after render

## Fixtures

- Create small committed test fixtures under a dedicated directory:
  - minimal JSON payloads
  - songs JSON payloads including Gloria
  - minimal `.pptx` templates designed for automated tests
  - saved RSS/HTML fixtures for fetcher tests

## Maintenance

- Keep the placeholder contract synchronized across:
  - `render.py`
  - `web/app.py`
  - `templates/README.md`
  - `AGENTS.md`
  - sample songs JSON files

- Consider splitting renderer logic into importable functions so the web app does not need to shell out to `render.py` for testing and debugging.

- Add an explicit liturgical-rules layer for seasonal/feast behavior, including:
  - when `GLORIA` should be present vs omitted
  - Lent-specific handling beyond Gloria, especially Gospel acclamation differences
  - feast/solemnity exceptions during Lent and Ordinary Time
