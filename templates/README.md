# Templates Guide

This project renders PowerPoint decks by replacing placeholder tokens in a `.pptx` template and duplicating certain slides using a “waterfall” technique. Rendering is performed through OfficeCLI against an output copy of the template, so source templates are not modified.

## File Names and Location

- Default directory: `templates/`
- Auto-pick when `--template` is a directory or omitted:
  - Sundays: `templates/sunday-ord.pptx`
  - Weekdays: `templates/daily-ord.pptx`
- Custom file: pass an explicit path via `--template`, e.g. `--template templates/custom/custom-sunday.pptx`.
- Uploaded files (via the web UI) are saved under `templates/uploads/` and can be referenced directly, e.g. `--template templates/uploads/<file>.pptx`.

Note: `.pptx` files under `templates/` are ignored by Git. Keep your template files locally or distribute them separately.

## Placeholders (required tokens)

Type these tokens exactly as written into text boxes where you want content to appear:

- `{LITURGICAL_DAY}`
- `{FIRST_READING_REF}`
- `{FIRST_READING_TXT}`
- `{PSALM_REF}`
- `{PSALM_TXT}`
- `{SECOND_READING_REF}`
- `{SECOND_READING_TXT}`
- `{ACCLAMATION_RES}`
- `{ACCLAMATION_VERSE}`
- `{GOSPEL_REF}`
- `{GOSPEL_TXT}`

Additional hymn/fixed-part placeholders are supported by the current renderer:

- Lyrics / waterfall:
  - `{ENTRANCE_TXT}`
  - `{KYRIE_TXT}`
  - `{GLORIA_TXT}`
  - `{OFFERTORY_TXT}`
  - `{SANCTUS_TXT}`
  - `{MYSTERIUM_TXT}`
  - `{AGNUS_TXT}`
  - `{COMMUNION_TXT}`
  - `{MEDITATION_TXT}`
  - `{RECESSIONAL_TXT}`
- Optional references:
  - `{ENTRANCE_REF}`
  - `{OFFERTORY_REF}`
  - `{COMMUNION_REF}`
  - `{MEDITATION_REF}`
  - `{RECESSIONAL_REF}`

These are filled from a songs JSON passed with `--songs`, or from the web UI which generates that JSON for you.

## Optional OfficeCLI Shape Names

Existing literal `{TOKEN}` placeholders are still supported. Future templates may instead name text shapes for a more explicit OfficeCLI contract:

- Simple placeholders: `AL_TOKEN_LITURGICAL_DAY`, `AL_TOKEN_FIRST_READING_REF`, etc.
- Waterfall seed placeholders: `AL_SEED_FIRST_READING_TXT`, `AL_SEED_PSALM_TXT`, etc.

If a matching OfficeCLI shape name is present, the renderer uses that shape directly. Otherwise it falls back to literal `{TOKEN}` find/replace.

## Waterfall (slide duplication)

For long readings, the renderer duplicates a “seed” slide and replaces only the body token on each duplicate:

- Seed tokens: `{FIRST_READING_TXT}`, `{PSALM_TXT}`, `{SECOND_READING_TXT}`, `{GOSPEL_TXT}`.
- Expect exactly one seed slide per body token. If the renderer finds more than one slide containing the same waterfall token, it now fails with a template error instead of guessing.
- Zero seed slides is allowed for optional sections. In that case the renderer skips that waterfall token entirely.
- Empty optional sections are pruned by default: if a supported optional body token has no text/chunks, its placeholder slide sequence and immediate blank spacer slides are removed from the output copy.
- The seed slide is filled with chunk 1. Duplicates are inserted immediately after it for chunks 2..N.
- All other placeholders already present on the seed (e.g., the reference) remain as filled.

Tips for reliable placeholders:

- Keep the literal token text in the slide. OfficeCLI find/replace handles normal PowerPoint text fragmentation better than the old renderer, but seed discovery still looks for the literal token in the PPTX slide XML.
- Put the reading body token in its own text box.
- Avoid putting unrelated placeholders on the same seed slide as a waterfall token unless you want them cloned with the seed slide.
- Images and other relationships on seed slides are cloned by OfficeCLI; verify complex templates with `--verbose` and by opening the output in PowerPoint.

## Psalm Formatting

- `{PSALM_TXT}` should be on a seed slide that will be duplicated for alternating refrain/verse blocks.
- The renderer derives Psalm chunks from the full text at render time, starting with the refrain line (`R.`), rather than trusting the JSON chunks blindly.

## Text Handling

- Reading/acclamation text is normalized so newlines become spaces and repeated whitespace is collapsed.
- The acclamation now uses explicit placeholders for the response and verse instead of waterfall duplication.
- Hymn chunks preserve explicit line breaks from the songs JSON.
- Non-Psalm reading chunks are balanced with the shared `chunking.py` rules, which prefer fuller slides and avoid tiny remainder chunks when possible.

## Common Layout Pattern

A simple, effective order in the template:

- Title or “Liturgia de la Palabra” slide
- First Reading: a slide with `{FIRST_READING_REF}`
- First Reading body seed: a slide with `{FIRST_READING_TXT}`
- Psalm: `{PSALM_REF}` then `{PSALM_TXT}` seed
- Second Reading: `{SECOND_READING_REF}` then `{SECOND_READING_TXT}` seed
- Acclamation: one slide with `{ACCLAMATION_RES}`, one slide with `{ACCLAMATION_VERSE}`, and another response slide with `{ACCLAMATION_RES}`
- Gospel: `{GOSPEL_REF}` then `{GOSPEL_TXT}` seed

You may include interstitial slides (e.g., “Palabra de Dios”) as desired. The renderer recognizes the second-reading response slide and removes it when the second reading is absent.

## Empty Optional Sections

- Missing `{SECOND_READING_TXT}` removes the second-reading reference slide, body seed slide, matching “Palabra de Dios / Te alabamos” response slide, and immediately following blank spacer slides.
- Missing hymn/fixed-part lyric tokens remove the lyric seed slide and immediately following blank spacer slides.
- A blank spacer slide has no text and no placeholder-looking tokens; image/background-only spacer slides still count as blank.
- Use `--keep-empty-sections` to keep these slides and blank the placeholders instead.

## Verifying a Template

- Run the read-only linter before rendering:
  - `venv/bin/python scripts/lint_template.py templates/custom/custom-sunday.pptx`
  - Add `--strict` to treat warnings as failures.
  - Add `--validate` to run `officecli validate` when OfficeCLI is installed.
- Run the renderer with `--verbose` to see where tokens are detected and which slides become seeds.
- After rendering, inspect the output with `venv/bin/python scripts/inspect_pptx.py build/<output>.pptx --tokens`.
- For automated checks, use `venv/bin/python scripts/inspect_pptx.py build/<output>.pptx --fail-on-remaining`.
- Run `officecli validate build/<output>.pptx` after rendering when OfficeCLI is installed.
- Open the resulting PPTX and verify that long readings expand into multiple slides placed directly after their seed.
