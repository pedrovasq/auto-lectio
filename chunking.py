from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, List


READING_MIN_CHARS = 90
READING_TARGET_CHARS = 150
READING_SOFT_MAX_CHARS = 170
READING_HARD_MAX_CHARS = 210


@dataclass(frozen=True)
class ChunkUnit:
    text: str
    boundary: str


def normalize_inline_text(text: str) -> str:
    if text is None:
        return ""
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", " ")
    return " ".join(text.split()).strip()


def split_sentences(text: str) -> List[str]:
    text = normalize_inline_text(text)
    if not text:
        return []

    protected = {
        "Sr.": "Sr<dot>",
        "Sra.": "Sra<dot>",
        "Dr.": "Dr<dot>",
        "Dra.": "Dra<dot>",
        "p.ej.": "pej<dot>",
        "etc.": "etc<dot>",
    }
    for source, target in protected.items():
        text = text.replace(source, target)

    parts = re.split(r"(?<=[.!?…])\s+(?=[\"“¿¡A-ZÁÉÍÓÚÜÑ])", text)

    restored: List[str] = []
    for part in parts:
        for source, target in protected.items():
            part = part.replace(target, source)
        part = part.strip()
        if part:
            restored.append(part)
    return restored


def _split_clauses(sentence: str) -> List[str]:
    parts = [c.strip() for c in re.split(r"(?<=[,;:])\s+", sentence) if c.strip()]
    return parts or [sentence.strip()]


def _wrap_words(text: str, hard_max_chars: int) -> List[str]:
    words = text.split()
    if not words:
        return []

    out: List[str] = []
    current: List[str] = []
    for word in words:
        candidate = " ".join(current + [word]).strip()
        if current and len(candidate) > hard_max_chars:
            out.append(" ".join(current).strip())
            current = [word]
            continue
        current.append(word)
    if current:
        out.append(" ".join(current).strip())
    return out


def _sentence_to_units(sentence: str, soft_max_chars: int, hard_max_chars: int) -> List[ChunkUnit]:
    sentence = sentence.strip()
    if not sentence:
        return []
    if len(sentence) <= soft_max_chars:
        return [ChunkUnit(sentence, "sentence")]

    units: List[ChunkUnit] = []
    clauses = _split_clauses(sentence)
    if len(clauses) == 1 and len(sentence) <= hard_max_chars:
        return [ChunkUnit(sentence, "sentence")]
    for idx, clause in enumerate(clauses):
        boundary = "sentence" if idx == len(clauses) - 1 else "clause"
        if len(clause) <= hard_max_chars:
            units.append(ChunkUnit(clause, boundary))
            continue
        wrapped = _wrap_words(clause, hard_max_chars)
        for w_idx, segment in enumerate(wrapped):
            seg_boundary = boundary if w_idx == len(wrapped) - 1 else "word"
            units.append(ChunkUnit(segment, seg_boundary))
    return units


def _build_units(text: str, soft_max_chars: int, hard_max_chars: int) -> List[ChunkUnit]:
    units: List[ChunkUnit] = []
    for sentence in split_sentences(text):
        units.extend(_sentence_to_units(sentence, soft_max_chars, hard_max_chars))
    return units


def _join_units(units: Iterable[ChunkUnit]) -> str:
    return " ".join(unit.text for unit in units).strip()


def _boundary_penalty(boundary: str) -> float:
    if boundary == "sentence":
        return 0.0
    if boundary == "clause":
        return 12.0
    return 26.0


def _chunk_score(
    text: str,
    boundary: str,
    is_last: bool,
    target_chars: int,
    min_chars: int,
    soft_max_chars: int,
) -> float:
    length = len(text)
    score = abs(length - target_chars) * 0.8

    if length < min_chars:
        deficit = min_chars - length
        score += deficit * (5.0 if not is_last else 4.0)
        if length < 60:
            score += (60 - length) * 4.0
    if length > soft_max_chars:
        score += (length - soft_max_chars) * 2.5

    score += _boundary_penalty(boundary)

    if text.endswith((",", ";", ":")):
        score += 10.0
    if text.endswith(("“", '"', "(", "¿", "¡")):
        score += 14.0

    return score


def chunk_text(
    text: str,
    *,
    min_chars: int = READING_MIN_CHARS,
    target_chars: int = READING_TARGET_CHARS,
    soft_max_chars: int = READING_SOFT_MAX_CHARS,
    hard_max_chars: int = READING_HARD_MAX_CHARS,
) -> List[str]:
    text = normalize_inline_text(text)
    if not text:
        return []

    units = _build_units(text, soft_max_chars=soft_max_chars, hard_max_chars=hard_max_chars)
    if not units:
        return []

    @lru_cache(maxsize=None)
    def solve(start: int) -> tuple[float, tuple[str, ...]]:
        if start >= len(units):
            return 0.0, ()

        best_score: float | None = None
        best_chunks: tuple[str, ...] = ()
        current_units: List[ChunkUnit] = []

        for end in range(start, len(units)):
            current_units.append(units[end])
            chunk_value = _join_units(current_units)
            if len(chunk_value) > hard_max_chars:
                break

            is_last = end == len(units) - 1
            score = _chunk_score(
                chunk_value,
                units[end].boundary,
                is_last,
                target_chars=target_chars,
                min_chars=min_chars,
                soft_max_chars=soft_max_chars,
            )
            tail_score, tail_chunks = solve(end + 1)
            total = score + tail_score

            if best_score is None or total < best_score:
                best_score = total
                best_chunks = (chunk_value, *tail_chunks)

        return (best_score if best_score is not None else 0.0), best_chunks

    return list(solve(0)[1])


def rebalance_chunks(
    chunks: List[str],
    *,
    min_chars: int = READING_MIN_CHARS,
    target_chars: int = READING_TARGET_CHARS,
    soft_max_chars: int = READING_SOFT_MAX_CHARS,
    hard_max_chars: int = READING_HARD_MAX_CHARS,
) -> List[str]:
    normalized = [normalize_inline_text(chunk) for chunk in chunks if normalize_inline_text(chunk)]
    if not normalized:
        return []
    return chunk_text(
        " ".join(normalized),
        min_chars=min_chars,
        target_chars=target_chars,
        soft_max_chars=soft_max_chars,
        hard_max_chars=hard_max_chars,
    )
