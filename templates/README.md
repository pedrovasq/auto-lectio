# Templates Guide

This project renders PowerPoint decks by replacing placeholder tokens in a `.pptx` template and duplicating certain slides using a “waterfall” technique.

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
- `{ACCLAMATION_REF}`
- `{ACCLAMATION_TXT}`
- `{GOSPEL_REF}`
- `{GOSPEL_TXT}`

Hymn placeholders exist but are currently ignored by the renderer: `{ENTRANCE_HYMN}`, `{OFFERTORY_HYMN}`, `{MYSTERY_OF_FAITH}`, `{COMMUNION_HYMN}`, `{RECESSIONAL_HYMN}`.

## Waterfall (slide duplication)

For long readings, the renderer duplicates a “seed” slide and replaces only the body token on each duplicate:

- Seed tokens: `{FIRST_READING_TXT}`, `{PSALM_TXT}`, `{SECOND_READING_TXT}`, `{GOSPEL_TXT}`.
- Expect exactly one seed slide per body token.
- The seed slide is filled with chunk 1. Duplicates are inserted immediately after it for chunks 2..N.
- All other placeholders already present on the seed (e.g., the reference) remain as filled.

Tips for reliable placeholders:

- Keep each token as a single run of text (PowerPoint sometimes splits runs; paragraph-level replacement mitigates this, but single-run is safest).
- Put the reading body token in its own text box.
- Avoid placing images on the seed slide if you don’t want them duplicated; the renderer skips shapes with image relationships on duplicated slides to avoid PPTX repair prompts.

## Psalm Formatting

- `{PSALM_TXT}` should be on a seed slide that will be duplicated for alternating refrain/verse blocks.
- The renderer derives Psalm chunks from the full text, starting with the refrain line (`R.`).

## Text Handling

- Newlines are converted to spaces; repeated whitespace is collapsed.
- Non-Psalm chunks are merged to target ~100–140 characters for better slide balance.

## Common Layout Pattern

A simple, effective order in the template:

- Title or “Liturgia de la Palabra” slide
- First Reading: a slide with `{FIRST_READING_REF}`
- First Reading body seed: a slide with `{FIRST_READING_TXT}`
- Psalm: `{PSALM_REF}` then `{PSALM_TXT}` seed
- Second Reading: `{SECOND_READING_REF}` then `{SECOND_READING_TXT}` seed
- Acclamation: `{ACCLAMATION_REF}` and `{ACCLAMATION_TXT}`
- Gospel: `{GOSPEL_REF}` then `{GOSPEL_TXT}` seed

You may include interstitial slides (e.g., “Palabra de Dios”) as desired; the renderer won’t delete slides.

## Verifying a Template

- Run the renderer with `--verbose` to see where tokens are detected and which slides become seeds.
- Open the resulting PPTX and verify that long readings expand into multiple slides placed directly after their seed.

