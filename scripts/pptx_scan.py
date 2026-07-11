from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from zipfile import BadZipFile, ZipFile


HYMN_TOKENS = [
    "{ENTRANCE_TXT}",
    "{KYRIE_TXT}",
    "{GLORIA_TXT}",
    "{OFFERTORY_TXT}",
    "{SANCTUS_TXT}",
    "{MYSTERIUM_TXT}",
    "{AGNUS_TXT}",
    "{COMMUNION_TXT}",
    "{MEDITATION_TXT}",
    "{RECESSIONAL_TXT}",
]

WATERFALL_TOKENS = [
    "{FIRST_READING_TXT}",
    "{PSALM_TXT}",
    "{SECOND_READING_TXT}",
    "{GOSPEL_TXT}",
    *HYMN_TOKENS,
]

CORE_REQUIRED_TOKENS = [
    "{LITURGICAL_DAY}",
    "{FIRST_READING_REF}",
    "{FIRST_READING_TXT}",
    "{PSALM_REF}",
    "{PSALM_TXT}",
    "{ACCLAMATION_RES}",
    "{ACCLAMATION_VERSE}",
    "{GOSPEL_REF}",
    "{GOSPEL_TXT}",
]

OPTIONAL_SECOND_READING_TOKENS = [
    "{SECOND_READING_REF}",
    "{SECOND_READING_TXT}",
]

OPTIONAL_HYMN_REF_TOKENS = [
    "{ENTRANCE_REF}",
    "{OFFERTORY_REF}",
    "{COMMUNION_REF}",
    "{MEDITATION_REF}",
    "{RECESSIONAL_REF}",
]

KNOWN_TOKENS = sorted(
    {
        *CORE_REQUIRED_TOKENS,
        *OPTIONAL_SECOND_READING_TOKENS,
        *OPTIONAL_HYMN_REF_TOKENS,
        *HYMN_TOKENS,
    }
)

SIMPLE_TOKENS = sorted(set(KNOWN_TOKENS) - set(WATERFALL_TOKENS))
PLACEHOLDER_RE = re.compile(r"\{[A-Z][A-Z0-9_]*\}")
SHAPE_NAME_RE = re.compile(r"<p:cNvPr\b[^>]*\bname=\"([^\"]*)\"", re.IGNORECASE)


@dataclass(frozen=True)
class ValidationResult:
    attempted: bool
    ok: bool
    message: str
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "ok": self.ok,
            "message": self.message,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def token_slug(token: str) -> str:
    return token.strip("{}")


def token_shape_name(token: str) -> str:
    return f"AL_TOKEN_{token_slug(token)}"


def seed_shape_name(token: str) -> str:
    return f"AL_SEED_{token_slug(token)}"


def supported_shape_names() -> set[str]:
    return {token_shape_name(token) for token in SIMPLE_TOKENS} | {
        seed_shape_name(token) for token in WATERFALL_TOKENS
    }


def _slide_num(slide_name: str) -> int:
    return int(Path(slide_name).stem.replace("slide", ""))


def slide_xml_names(path: Path) -> list[str]:
    try:
        with ZipFile(path, "r") as zf:
            names = zf.namelist()
    except (BadZipFile, FileNotFoundError, PermissionError) as exc:
        raise RuntimeError(f"Cannot read PPTX file {path}: {exc}") from exc

    slide_names = [
        name
        for name in names
        if name.startswith("ppt/slides/slide") and name.endswith(".xml")
    ]
    try:
        return sorted(slide_names, key=_slide_num)
    except ValueError as exc:
        raise RuntimeError(f"Invalid slide XML path in {path}") from exc


def _read_slide_xml(path: Path) -> list[tuple[int, str, str]]:
    slide_names = slide_xml_names(path)
    slides: list[tuple[int, str, str]] = []
    try:
        with ZipFile(path, "r") as zf:
            for name in slide_names:
                slides.append((_slide_num(name), name, zf.read(name).decode("utf-8", errors="ignore")))
    except (BadZipFile, FileNotFoundError, PermissionError, KeyError) as exc:
        raise RuntimeError(f"Cannot read PPTX slides from {path}: {exc}") from exc
    return slides


def _append_location(mapping: dict[str, list[int]], key: str, slide_num: int) -> None:
    mapping.setdefault(key, []).append(slide_num)


def _scan_literal_tokens(slides: Iterable[tuple[int, str, str]]) -> tuple[dict[str, list[int]], dict[int, list[str]]]:
    by_token: dict[str, list[int]] = {}
    by_slide: dict[int, list[str]] = {}
    known = set(KNOWN_TOKENS)
    for slide_num, _name, xml in slides:
        present = sorted(token for token in known if token in xml)
        if present:
            by_slide[slide_num] = present
            for token in present:
                _append_location(by_token, token, slide_num)
    return by_token, by_slide


def _scan_unsupported_tokens(slides: Iterable[tuple[int, str, str]]) -> tuple[dict[str, list[int]], dict[int, list[str]]]:
    by_token: dict[str, list[int]] = {}
    by_slide: dict[int, list[str]] = {}
    known = set(KNOWN_TOKENS)
    for slide_num, _name, xml in slides:
        present = sorted(set(PLACEHOLDER_RE.findall(xml)) - known)
        if present:
            by_slide[slide_num] = present
            for token in present:
                _append_location(by_token, token, slide_num)
    return by_token, by_slide


def _scan_shape_names(slides: Iterable[tuple[int, str, str]]) -> tuple[dict[str, list[int]], dict[int, list[str]]]:
    by_name: dict[str, list[int]] = {}
    by_slide: dict[int, list[str]] = {}
    supported = supported_shape_names()
    for slide_num, _name, xml in slides:
        names = sorted({html.unescape(match) for match in SHAPE_NAME_RE.findall(xml)})
        present = [name for name in names if name in supported]
        if present:
            by_slide[slide_num] = present
            for name in present:
                _append_location(by_name, name, slide_num)
    return by_name, by_slide


def scan_pptx(path: str | Path) -> dict[str, Any]:
    pptx_path = Path(path)
    slides = _read_slide_xml(pptx_path)
    literal_by_token, literal_by_slide = _scan_literal_tokens(slides)
    unsupported_by_token, unsupported_by_slide = _scan_unsupported_tokens(slides)
    shape_by_name, shape_by_slide = _scan_shape_names(slides)

    seed_locations: dict[str, dict[str, list[int]]] = {}
    simple_locations: dict[str, dict[str, list[int]]] = {}

    for token in WATERFALL_TOKENS:
        seed_locations[token] = {
            "literal": literal_by_token.get(token, []),
            "shape": shape_by_name.get(seed_shape_name(token), []),
        }
    for token in SIMPLE_TOKENS:
        simple_locations[token] = {
            "literal": literal_by_token.get(token, []),
            "shape": shape_by_name.get(token_shape_name(token), []),
        }

    return {
        "path": str(pptx_path),
        "slide_count": len(slides),
        "slides": [{"number": num, "name": name} for num, name, _xml in slides],
        "literal_tokens": {
            "by_token": {token: sorted(slides) for token, slides in sorted(literal_by_token.items())},
            "by_slide": {str(num): tokens for num, tokens in sorted(literal_by_slide.items())},
        },
        "shape_names": {
            "by_name": {name: sorted(slides) for name, slides in sorted(shape_by_name.items())},
            "by_slide": {str(num): names for num, names in sorted(shape_by_slide.items())},
        },
        "unsupported_tokens": {
            "by_token": {token: sorted(slides) for token, slides in sorted(unsupported_by_token.items())},
            "by_slide": {str(num): tokens for num, tokens in sorted(unsupported_by_slide.items())},
        },
        "waterfall_seeds": seed_locations,
        "simple_placeholders": simple_locations,
        "known_tokens": KNOWN_TOKENS,
        "waterfall_tokens": WATERFALL_TOKENS,
    }


def has_placeholder(scan: dict[str, Any], token: str) -> bool:
    locations = scan["waterfall_seeds"].get(token) or scan["simple_placeholders"].get(token) or {}
    return bool(locations.get("literal") or locations.get("shape"))


def seed_count(scan: dict[str, Any], token: str) -> int:
    locations = scan["waterfall_seeds"].get(token, {})
    return len(set(locations.get("literal", []) + locations.get("shape", [])))


def validate_with_officecli(path: str | Path, executable: str = "officecli") -> ValidationResult:
    exe = shutil.which(executable)
    if exe is None:
        return ValidationResult(
            attempted=False,
            ok=False,
            message=f"{executable} is not on PATH",
        )
    proc = subprocess.run(
        [exe, "validate", str(path)],
        capture_output=True,
        text=True,
    )
    return ValidationResult(
        attempted=True,
        ok=proc.returncode == 0,
        message="OfficeCLI validation passed" if proc.returncode == 0 else "OfficeCLI validation failed",
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )


def dump_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
