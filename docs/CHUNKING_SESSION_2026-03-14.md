# Chunking Session Notes - 2026-03-14

This file is specific to the current chunking discussion and implementation session.
It is not related to `TODO.md`.

## Session Goal

Reduce disorienting slide churn by generating fewer, better-balanced reading chunks.

## Problem Summary

- The current reading chunker is mostly character-limit driven.
- It prefers sentence boundaries, then clause boundaries, but it does not balance the full sequence well.
- The renderer applies a second narrow merge-only pass, which is not strong enough to fix small orphan chunks.
- Real payloads already contain many very small chunks, including some that produce slides with only a few words.

## Agreed Direction

- Treat reading chunking as a single balancing problem instead of two weak passes.
- Keep Psalm handling separate.
- Prefer stable reading rhythm over strict adherence to a small 100-140 character band.
- Allow somewhat longer slides when that avoids tiny follow-up slides.

## Implementation Plan

### 1. Shared chunking helper

- Move balancing logic into a shared module so fetch and render use the same rules.
- Keep the public fetch contract unchanged: JSON still emits `chunks`.

### 2. Better reading chunker

- Split text into sentence and clause units.
- Use scoring to choose chunk boundaries across the whole reading.
- Prefer:
  - chunks near a target size
  - sentence endings over weak clause endings
  - avoiding very short remainder chunks
- Only fall back to word-based splitting when a single clause is too long.

### 3. Renderer alignment

- Stop using the old merge-only chunk bound logic for readings.
- Rebalance precomputed reading chunks with the same shared helper so older payloads also improve.
- Keep hymn and Psalm behavior unchanged.

### 4. Verification

- Add automated tests for:
  - avoiding tiny orphan chunks
  - merging short dialogue fragments into larger chunks
  - preserving chunk order while reducing pathological short slides

## Notes

- This session focuses on readings, not hymn chunking.
- If Psalm slides still feel too short later, that should be a separate rule set rather than reusing the reading chunker.
