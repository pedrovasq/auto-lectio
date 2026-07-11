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
6. It copies the template to the requested output path, then opens that output copy with OfficeCLI.
7. It prunes empty optional sections from the output copy unless `--keep-empty-sections` is set.
8. It replaces simple tokens across the deck.
9. It expands waterfall tokens by cloning a seed slide and replacing only the body token per duplicate.
10. The output PPTX is written to `build/`.

The web UI in `web/app.py` is a thin wrapper around that process, now split between public informational pages and the existing operator workflow.

## File responsibilities

### `fetch.py`

Primary responsibilities:
- date parsing and RSS item selection
- HTML cleanup and section extraction
- liturgical phrasing for reading references
- acclamation cleanup
- balanced reading chunking
- JSON payload creation

Important functions:
- `pick_item(entries, target_mmddyy)`: date match by substring in the RSS item link
- `parse_sections(desc_html)`: extracts `(header, body)` pairs
- `to_placeholders(item_title, sections)`: maps parsed sections to the template contract
- `chunkify(...)`: wrapper around the shared balanced chunker in `chunking.py`
- `make_chunks(placeholders)`: only chunks the reading body tokens

Notable behavior:
- First and second reading references are normalized into spoken Mass phrasing, not copied verbatim from the feed.
- The acclamation is split into explicit placeholders: `{ACCLAMATION_RES}` and `{ACCLAMATION_VERSE}`.
- `build_payload(...)` normalizes whitespace in both placeholders and chunks.

### `chunking.py`

Primary responsibilities:
- shared reading chunking rules used by both fetch and render
- sentence/clause/word unitization
- chunk-sequence balancing with scoring

Important functions:
- `chunk_text(...)`: builds balanced reading chunks from raw text
- `rebalance_chunks(...)`: rebalances existing reading chunks, useful for older payloads

Notable behavior:
- Uses a wider soft/hard size band than the older 100-140 character pass.
- Penalizes very short orphan chunks and weak clause endings.
- Will split long sentences at clause boundaries even when they are still below the hard ceiling, so neighboring short lines can be absorbed.

### `render.py`

Primary responsibilities:
- template selection
- placeholder replacement
- songs JSON merge
- empty optional-section pruning
- waterfall slide duplication
- PPTX output writing

Important functions:
- `resolve_template_path(args, payload)`: picks `sunday-ord` vs `daily-ord`
- `render_with_officecli(...)`: copies the template and applies all PPTX edits through OfficeCLI
- `OfficeCli`: small subprocess adapter around the `officecli` binary
- `chunk_psalm_text(text)`: splits the psalm into refrain/verse alternation
- `build_prune_plans(...)`: decides which optional-section slides should be removed before replacement
- `find_seed_slide_numbers(...)`: read-only ZIP inspection for placeholder seed discovery

Actual rendering order:
1. Load payload and optional songs JSON.
2. Merge song references into `placeholders` if the main payload does not already define them.
3. Copy the selected template to the requested output path.
4. Plan empty optional-section pruning and record original seed slide locations.
5. Remove planned empty-section slides with OfficeCLI unless `--keep-empty-sections` was passed, then adjust recorded seed slide numbers for the removed slides.
6. Open the output copy with OfficeCLI.
7. Replace all non-waterfall tokens with OfficeCLI find/replace.
8. Process seeds in descending slide number.
9. Clone seed/tail slides with OfficeCLI and replace each body token in slide scope.

Waterfall tokens currently include:
- Readings: `{FIRST_READING_TXT}`, `{PSALM_TXT}`, `{SECOND_READING_TXT}`, `{GOSPEL_TXT}`
- Hymns/fixed sung parts: `{ENTRANCE_TXT}`, `{KYRIE_TXT}`, `{GLORIA_TXT}`, `{OFFERTORY_TXT}`, `{SANCTUS_TXT}`, `{MYSTERIUM_TXT}`, `{AGNUS_TXT}`, `{COMMUNION_TXT}`, `{MEDITATION_TXT}`, `{RECESSIONAL_TXT}`

Notable behavior:
- Psalm chunking is regenerated from the raw psalm text at render time, even if the JSON already contains psalm chunks.
- Hymn chunks preserve newlines; reading chunks are flattened to spaces.
- Non-Psalm reading chunks are rebalanced with the shared chunker so older payloads also benefit.
- Missing optional sections are pruned by default. Missing second reading removes the ref slide, body seed slide, matching response slide, and immediate blank spacer slides. Missing hymn/fixed-part lyrics remove their seed slide and immediate blank spacer slides.
- `--keep-empty-sections` restores the older behavior where empty placeholders are blanked and slides remain.
- Source templates are never mutated; all edits happen on the output copy.

### `scripts/pptx_scan.py`

Primary responsibilities:
- read PPTX files as ZIP archives without mutating them
- enumerate `ppt/slides/slideN.xml` in slide-number order
- detect supported literal `{TOKEN}` placeholders by slide
- detect supported OfficeCLI shape names by slide, including `AL_TOKEN_*` and `AL_SEED_*`
- detect unsupported placeholder-looking tokens such as `{FOO_BAR}`
- provide optional `officecli validate` integration for diagnostic CLIs

Notable behavior:
- The scanner is deterministic and read-only. It does not call `officecli open`, `set`, `add`, `move`, or `close`.
- Literal placeholder detection is XML substring-based, matching the renderer's compatibility path.
- Shape-name detection reads `p:cNvPr name="..."` attributes and only reports names that belong to the supported Auto-Lectio contract.

### `scripts/lint_template.py`

Primary responsibilities:
- validate a template before render
- fail on missing required core placeholders
- fail on duplicate waterfall seed slides
- warn on missing optional second reading, hymn/fixed-part, and hymn reference placeholders
- warn on unsupported placeholder-looking tokens
- optionally run OfficeCLI validation with `--validate`

CLI behavior:
- `0`: no lint errors, or only warnings without `--strict`
- `1`: lint errors, or warnings when `--strict` is used
- `2`: runtime failure such as unreadable/invalid PPTX, or required OfficeCLI missing

Useful commands:
- `venv/bin/python scripts/lint_template.py templates/custom/domingo-jgv.pptx`
- `venv/bin/python scripts/lint_template.py templates/custom/domingo-jgv.pptx --json`
- `venv/bin/python scripts/lint_template.py templates/custom/domingo-jgv.pptx --strict --validate`

### `scripts/inspect_pptx.py`

Primary responsibilities:
- inspect any PPTX deck, especially rendered output
- report slide count, remaining supported literal placeholders, named placeholders, and unsupported tokens
- optionally print token locations with `--tokens`
- optionally run OfficeCLI validation with `--validate`
- fail rendered-output checks with `--fail-on-remaining`

CLI behavior:
- `0`: inspection succeeded and no configured failure was found
- `1`: `--fail-on-remaining` found supported literal placeholders
- `2`: runtime failure such as unreadable/invalid PPTX

Useful commands:
- `venv/bin/python scripts/inspect_pptx.py build/YYYY-MM-DD.es-US.pptx`
- `venv/bin/python scripts/inspect_pptx.py build/YYYY-MM-DD.es-US.pptx --tokens`
- `venv/bin/python scripts/inspect_pptx.py build/YYYY-MM-DD.es-US.pptx --fail-on-remaining`

### `web/app.py`

Primary responsibilities:
- serve the public site pages and the advanced operator UI
- expose `/fetch`, `/render`, `/run`, `/upload`, `/placeholders`
- synthesize a songs JSON from UI form data

Current page routes:
- `/`: Spanish landing page (`web/templates/home.html`)
- `/docs`: Spanish documentation page (`web/templates/docs.html`)
- `/guided`: minimal guided workflow for common use (`web/templates/guided.html`)
- `/advanced`: current operator UI (`web/templates/advanced.html`)

Architecture note:
- `/fetch` imports `fetch.py` functions directly.
- `/render` does not import `render.py`; it shells out to the CLI with `subprocess.run(...)`.
- `/run` fetches first, then renders.

Template/layout note:
- `web/templates/base.html` provides the shared shell for the public pages.
- `web/static/site.css` holds the shared styling for the public pages.
- `web/templates/guided.html` is a client-side progressive form that uses `/feed/dates`, `/templates`, `/upload`, and `/run`.
- Guided mode constrains the user to feed-available dates, defaults the acclamation to ordinary, assumes fixed sung parts in Spanish, and only exposes `Misterio de la fe` as a fixed-part choice.
- The advanced page is still a standalone template with its own embedded styles and behavior.

This means renderer changes must be tested through the CLI path, even when the UI is the user-facing entry point.

## Current template contract

Core placeholders:
- `{LITURGICAL_DAY}`
- `{FIRST_READING_REF}`, `{FIRST_READING_TXT}`
- `{PSALM_REF}`, `{PSALM_TXT}`
- `{SECOND_READING_REF}`, `{SECOND_READING_TXT}`
- `{ACCLAMATION_RES}`, `{ACCLAMATION_VERSE}`
- `{GOSPEL_REF}`, `{GOSPEL_TXT}`

Hymn/fixed-part placeholders:
- `{ENTRANCE_TXT}`, `{KYRIE_TXT}`, `{GLORIA_TXT}`, `{OFFERTORY_TXT}`, `{SANCTUS_TXT}`
- `{MYSTERIUM_TXT}`, `{AGNUS_TXT}`, `{COMMUNION_TXT}`, `{MEDITATION_TXT}`, `{RECESSIONAL_TXT}`
- optional refs: `{ENTRANCE_REF}`, `{OFFERTORY_REF}`, `{COMMUNION_REF}`, `{MEDITATION_REF}`, `{RECESSIONAL_REF}`

For custom templates, the safest assumption is still one seed slide per waterfall token.

Optional OfficeCLI-native shape names are also supported for future templates:
- `AL_TOKEN_<PLACEHOLDER_NAME>` for simple placeholders, e.g. `AL_TOKEN_LITURGICAL_DAY`
- `AL_SEED_<PLACEHOLDER_NAME>` for waterfall seed body placeholders, e.g. `AL_SEED_GOSPEL_TXT`

When a matching shape name exists, `render.py` sets that shape text directly. Otherwise it falls back to the literal `{TOKEN}` text contract used by existing templates.

## Fragile spots

### OfficeCLI dependency

Rendering requires the `officecli` binary on `PATH`. Docker installs it during image build; local development should verify `officecli --version` before rendering.

### Seed discovery

The renderer discovers placeholder seed slides by reading slide XML inside the PPTX package. This is read-only and does not mutate templates. Existing templates are discovered through literal `{TOKEN}` text; future templates can use stable `AL_TOKEN_*` and `AL_SEED_*` shape names.

When pruning is enabled, seed locations are discovered before OfficeCLI deletes slides. OfficeCLI paths use logical slide positions after deletion, while slide XML part numbers can remain sparse, so the renderer adjusts the original seed numbers by the removed-slide set instead of rescanning the mutated package for seed positions.

### Slide duplication

OfficeCLI clone operations replace the old private `python-pptx` XML copying. If slide order behavior changes in OfficeCLI, verify the waterfall sequence with `--verbose` and `officecli view <deck> outline`.

### Documentation sync points

When placeholder support changes, update these together:
- `render.py`: `WATERFALL_KEYS`, `KNOWN_TOKENS`, songs handling
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
   - `officecli validate build/YYYY-MM-DD.es-US.pptx` succeeds
   - PowerPoint opens the result without a repair prompt

## Known drift already corrected

Older docs said hymn placeholders were ignored. That is no longer true. The renderer supports hymn chunk waterfall expansion and optional hymn references from a songs JSON.
