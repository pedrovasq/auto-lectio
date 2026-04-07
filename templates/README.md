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

## Waterfall (slide duplication)

For long readings, the renderer duplicates a “seed” slide and replaces only the body token on each duplicate:

- Seed tokens: `{FIRST_READING_TXT}`, `{PSALM_TXT}`, `{SECOND_READING_TXT}`, `{GOSPEL_TXT}`.
- Expect exactly one seed slide per body token. If the renderer finds more than one slide containing the same waterfall token, it now fails with a template error instead of guessing.
- Zero seed slides is allowed for optional sections. In that case the renderer skips that waterfall token entirely.
- The seed slide is filled with chunk 1. Duplicates are inserted immediately after it for chunks 2..N.
- All other placeholders already present on the seed (e.g., the reference) remain as filled.

Tips for reliable placeholders:

- Keep each token as a single run of text when possible. The current renderer does run-level replacement, so a token split across multiple PowerPoint runs may not be replaced.
- Put the reading body token in its own text box.
- Avoid putting unrelated placeholders on the same seed slide as a waterfall token. The duplicate logic filters out shapes containing other known tokens.
- Be careful with seed-slide images. The duplicate logic skips shapes with image relationships to avoid PPTX repair prompts, so those images may not appear on duplicated slides.

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

You may include interstitial slides (e.g., “Palabra de Dios”) as desired; the renderer won’t delete slides.

## Verifying a Template

- Run the renderer with `--verbose` to see where tokens are detected and which slides become seeds.
- Open the resulting PPTX and verify that long readings expand into multiple slides placed directly after their seed.
