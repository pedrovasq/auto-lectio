# UI Session Notes - 2026-03-12

This file is specific to the current UI discussion and implementation session.
It is not related to `TODO.md`.

## Session Goal

Improve the web UI so it is safer and more usable for the common Mass slideshow workflow.

## Agreed Decisions

### Template selection

- Replace the manual template path text input with a server-driven dropdown.
- Remove manual path entry entirely from the UI.
- Reason: entering arbitrary paths is not user-friendly and creates unnecessary security risk.
- Uploaded templates should automatically appear in the dropdown and be selected after upload.
- Keep all previously uploaded templates visible and reusable across sessions.
- Sort uploaded templates newest-first to keep the list usable as it grows.

### Scope direction

- Focus first on the highest-value workflow improvements rather than visual polish alone.
- Keep discussing details before implementation so the behavior is explicit.

## Recommended Template Structure

The current structure works, but it is not ideal long-term if template usage grows.

### Current structure

- `templates/custom/`
- `templates/uploads/`

### Recommended structure

- `templates/library/`
  - Stable, curated templates intended for normal use.
  - Examples: `daily-ord.pptx`, `sunday-ord.pptx`, `custom-sunday.pptx`.
- `templates/uploads/`
  - User-uploaded files from the web UI.
- `templates/archive/` (optional, later)
  - Old or deprecated templates that should not appear by default.

### Why this is better

- Separates approved templates from ad hoc uploads.
- Makes the dropdown easier to understand.
- Avoids overloading `custom/` as a vague bucket.
- Gives the UI a clear default source of templates to present first.

### Dropdown behavior recommendation

- Show curated templates first, then uploads.
- Show all uploads, not just recent ones.
- Use human-readable labels with the real relative path as the underlying value.
- Do not allow arbitrary path typing from the browser.
- Add a refresh action so newly added files appear without reloading the page.

## Planned UI Improvements For This Session

### 1. Template picker

- Add a backend endpoint to list valid `.pptx` templates from approved directories.
- Populate a dropdown from that endpoint.
- Group or label entries by source (`Library`, `Uploads`).
- Auto-select a newly uploaded template after a successful upload.
- Remove the free-text template path field from the page.

### 2. Better workflow clarity

- Make the main path obvious: choose date, choose template, optionally add songs, generate output.
- Reduce the current "operator console" feel of the form.
- Keep `Fetch + Render` as the primary action.

### 3. Better result feedback

- Keep the success output with download/view links.
- Improve error display so backend render errors are visible in the UI.
- Prefer showing useful stderr/stdout details when a render fails.

### 4. Better state handling

- Avoid guessing the JSON path solely from the selected date when possible.
- Prefer carrying forward the actual path returned by `/fetch`.

### 5. Better diagnostics

- Show the actual JSON path currently loaded in the UI.
- Surface renderer stdout/stderr in the result area when useful.
- Make render failures actionable instead of reducing them to a generic error line.

### 6. Payload preview

- Show a preview of the fetched liturgical payload before rendering.
- Include title, source link, reading references, section presence, and chunk counts.
- Show which song placeholders are currently populated from the UI form.
- Make the currently loaded payload explicit instead of relying on hidden assumptions.

### 7. Explicit render state

- Do not guess the JSON payload path from the selected date.
- Require an explicitly loaded payload before allowing render-only actions.
- Make the "current payload" state visible in the UI.

### 8. Layout cleanup

- Rework the page into clearer sections with stronger hierarchy.
- Make the main workflow easier to scan: setup, songs, actions, preview, result, template help.
- Improve the visual structure without changing the underlying stack or introducing a frontend framework.

### 9. Template inspection

- Add server-side inspection for approved templates only.
- Show which supported placeholders are present in the selected template.
- Show waterfall token seed counts so template problems are visible before render.
- Keep inspection read-only and scoped to files already exposed by the template dropdown.

### 10. Gloria as fixed part

- Replace free-text Gloria entry with a simple include/omit control.
- Load Gloria from a fixed local part file, similar to Kyrie, Sanctus, Agnus, and Mysterium.
- Keep the decision manual in the UI instead of trying to infer liturgical rules automatically.

### 11. Layout refinement

- Make the date field narrower relative to the template selector.
- Reduce the global corner radius so the UI feels less soft and more editorial.
- Move the placeholder help out of the narrow sidebar so it does not become an isolated tall column.

### 12. Visual tuning

- Tighten spacing and card rhythm after the larger layout changes.
- Improve button hierarchy and form density.
- Make the placeholder reference area easier to scan now that it spans the full width.

## Open Questions

- Whether curated templates should later include metadata such as description or intended use.
- Whether the placeholder help panel should stay always visible or move behind a help/details control.

## Implementation Notes

- The dropdown should be populated from server-side filesystem discovery, not hardcoded paths.
- The server should only expose templates from approved directories under `templates/`.
- Manual path entry should not be retained as an "advanced" escape hatch for now.
