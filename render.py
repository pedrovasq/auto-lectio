from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence
from zipfile import ZipFile

from chunking import rebalance_chunks


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

SONGS_CHUNK_TOKENS = {
    "{PSALM_TXT}",
    *HYMN_TOKENS,
}

SONGS_PLACEHOLDER_OVERRIDE_TOKENS = {
    "{PSALM_REF}",
    "{PSALM_TXT}",
    "{ACCLAMATION_RES}",
    "{ACCLAMATION_VERSE}",
}

WATERFALL_KEYS = [
    "{FIRST_READING_TXT}",
    "{PSALM_TXT}",
    "{SECOND_READING_TXT}",
    "{GOSPEL_TXT}",
    *HYMN_TOKENS,
]

KNOWN_TOKENS = {
    "{LITURGICAL_DAY}",
    "{FIRST_READING_REF}",
    "{FIRST_READING_TXT}",
    "{PSALM_REF}",
    "{PSALM_TXT}",
    "{SECOND_READING_REF}",
    "{SECOND_READING_TXT}",
    "{ACCLAMATION_RES}",
    "{ACCLAMATION_VERSE}",
    "{GOSPEL_REF}",
    "{GOSPEL_TXT}",
    "{ENTRANCE_REF}",
    "{OFFERTORY_REF}",
    "{COMMUNION_REF}",
    "{MEDITATION_REF}",
    "{RECESSIONAL_REF}",
    *HYMN_TOKENS,
}

INTERESTED_TOKENS = [
    "{FIRST_READING_REF}",
    "{FIRST_READING_TXT}",
    "{PSALM_REF}",
    "{PSALM_TXT}",
    "{SECOND_READING_REF}",
    "{SECOND_READING_TXT}",
    "{ACCLAMATION_RES}",
    "{ACCLAMATION_VERSE}",
    "{GOSPEL_REF}",
    "{GOSPEL_TXT}",
    *HYMN_TOKENS,
    "{ENTRANCE_REF}",
    "{OFFERTORY_REF}",
    "{COMMUNION_REF}",
    "{MEDITATION_REF}",
    "{RECESSIONAL_REF}",
]


class OfficeCliError(RuntimeError):
    pass


@dataclass
class OfficeCliResult:
    stdout: str
    stderr: str


@dataclass(frozen=True)
class SeedTarget:
    token: str
    slide_num: int
    mode: str


@dataclass(frozen=True)
class PrunePlan:
    reason: str
    slides: tuple[int, ...]


class OfficeCli:
    def __init__(self, executable: str = "officecli", verbose: bool = False) -> None:
        self.executable = executable
        self.verbose = verbose

    def check_available(self) -> None:
        if shutil.which(self.executable) is None:
            raise OfficeCliError(
                "officecli is required to render PPTX files. Install OfficeCLI and ensure "
                f"'{self.executable}' is on PATH, then rerun render.py."
            )
        self.run(["--version"], allow_statuses={0})

    def run(self, args: Sequence[str], allow_statuses: set[int] | None = None) -> OfficeCliResult:
        allow_statuses = allow_statuses or {0}
        cmd = [self.executable, *[str(arg) for arg in args]]
        if self.verbose:
            print("officecli:", " ".join(_preview_arg(part) for part in cmd))
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode not in allow_statuses:
            raise OfficeCliError(
                "OfficeCLI command failed "
                f"(exit {proc.returncode}): {' '.join(_preview_arg(part) for part in cmd)}\n"
                f"stdout:\n{proc.stdout.strip()}\n"
                f"stderr:\n{proc.stderr.strip()}"
            )
        return OfficeCliResult(stdout=proc.stdout or "", stderr=proc.stderr or "")

    def open(self, deck_path: Path) -> None:
        self.run(["open", str(deck_path)])

    def close(self, deck_path: Path) -> None:
        self.run(["close", str(deck_path)])

    def replace(self, deck_path: Path, scope: str, token: str, value: str) -> None:
        self.run(["set", str(deck_path), scope, "--find", token, "--replace", value])

    def set_shape_text(self, deck_path: Path, slide_num: int, shape_name: str, value: str) -> None:
        self.run(
            [
                "set",
                str(deck_path),
                f"/slide[{slide_num}]/shape[@name={shape_name}]",
                "--prop",
                f"text={value}",
            ]
        )

    def clone_slide_after(self, deck_path: Path, source_slide_num: int, after_slide_num: int) -> int:
        result = self.run(
            [
                "add",
                str(deck_path),
                "/",
                "--from",
                f"/slide[{source_slide_num}]",
                "--json",
            ]
        )
        appended_path = _officecli_path_from_json(result.stdout)
        if not appended_path:
            raise OfficeCliError(f"OfficeCLI did not report a copied slide path:\n{result.stdout.strip()}")

        self.run(
            [
                "move",
                str(deck_path),
                appended_path,
                "--after",
                f"/slide[{after_slide_num}]",
                "--json",
            ]
        )
        inserted_slide_num = after_slide_num + 1
        return inserted_slide_num

    def remove_slide(self, deck_path: Path, slide_num: int) -> None:
        self.run(["remove", str(deck_path), f"/slide[{slide_num}]", "--json"])

    def validate(self, deck_path: Path) -> None:
        self.run(["validate", str(deck_path)])


def _preview_arg(value: str, limit: int = 80) -> str:
    compact = value.replace("\n", "\\n")
    if len(compact) > limit:
        compact = compact[: limit - 3] + "..."
    if re.search(r"\s|[{}[\]]", compact):
        return repr(compact)
    return compact


def _officecli_path_from_json(stdout: str) -> str | None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    for key in ("path", "data", "message"):
        value = payload.get(key)
        if not isinstance(value, str):
            continue
        match = re.search(r"(/slide\[\d+\])", value)
        if match:
            return match.group(1)
    return None


def _is_sunday_from_meta(meta: Dict[str, Any]) -> bool:
    dstr = (meta or {}).get("date")
    if dstr:
        try:
            d = date.fromisoformat(dstr)
            return d.weekday() == 6
        except Exception:
            pass
    title = (meta or {}).get("title") or ""
    return "domingo" in title.lower()


def _ensure_pptx(path: str) -> str:
    if os.path.isfile(path):
        return path
    if not os.path.splitext(path)[1]:
        cand = path + ".pptx"
        if os.path.isfile(cand):
            return cand
    return path


def resolve_template_path(args: Any, payload: Dict[str, Any]) -> str:
    meta = payload.get("meta", {})
    is_sunday = _is_sunday_from_meta(meta)

    if args.template:
        tpath = args.template
        if os.path.isdir(tpath):
            root = tpath
        else:
            return _ensure_pptx(tpath)
    else:
        root = args.template_root or "templates"

    chosen = "sunday-ord" if is_sunday else "daily-ord"
    cand = _ensure_pptx(os.path.join(root, chosen))
    if os.path.isfile(cand):
        return cand
    alt = os.path.join(root, chosen + ".pptx")
    if os.path.isfile(alt):
        return alt
    return cand


def load_payload(json_path: str) -> Dict[str, Any]:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def chunk_psalm_text(text: str) -> List[str]:
    if text is None:
        return []
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    lines = [ln for ln in lines if ln]
    chunks: List[str] = []
    current_verse: List[str] = []
    is_refrain = lambda s: re.match(r"^R[\./]?(?:\s*\([^)]*\))?\s", s) is not None or s.startswith("R.")

    for ln in lines:
        if is_refrain(ln):
            if current_verse:
                verse = "\n".join(current_verse).strip()
                if verse:
                    chunks.append(verse)
                current_verse = []
            chunks.append(ln)
        else:
            current_verse.append(ln)

    if current_verse:
        verse = "\n".join(current_verse).strip()
        if verse:
            chunks.append(verse)

    return [c for c in chunks if c and c.strip()]


def _sanitize_text(s: str | None) -> str:
    if s is None:
        return ""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\n", " ")
    return " ".join(s.split()).strip()


def token_slug(token: str) -> str:
    return token.strip("{}")


def token_shape_name(token: str) -> str:
    return f"AL_TOKEN_{token_slug(token)}"


def seed_shape_name(token: str) -> str:
    return f"AL_SEED_{token_slug(token)}"


def _stamp_output_path(out_path: str, stamp: bool) -> Path:
    if not stamp:
        return Path(out_path)
    base, ext = os.path.splitext(out_path)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    return Path(f"{base}.{ts}{ext or '.pptx'}")


def _load_songs(songs_path: str | None) -> tuple[Dict[str, List[str]], Dict[str, str]]:
    songs_chunks: Dict[str, List[str]] = {}
    songs_placeholders: Dict[str, str] = {}
    if not songs_path:
        return songs_chunks, songs_placeholders

    with open(songs_path, "r", encoding="utf-8") as sf:
        songs_payload = json.load(sf)
    if not isinstance(songs_payload, dict):
        return songs_chunks, songs_placeholders

    raw_chunks = songs_payload.get("chunks")
    if isinstance(raw_chunks, dict):
        for key, value in raw_chunks.items():
            if key in SONGS_CHUNK_TOKENS and isinstance(value, list):
                songs_chunks[key] = [item if isinstance(item, str) else str(item) for item in value]

    raw_placeholders = songs_payload.get("placeholders")
    if isinstance(raw_placeholders, dict):
        for key, value in raw_placeholders.items():
            if key in KNOWN_TOKENS and isinstance(value, str):
                songs_placeholders[key] = value

    return songs_chunks, songs_placeholders


def slide_xml_names(path: Path) -> List[str]:
    with ZipFile(path, "r") as zf:
        return sorted(
            [name for name in zf.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")],
            key=lambda name: int(Path(name).stem.replace("slide", "")),
        )


def slide_count(path: Path) -> int:
    return len(slide_xml_names(path))


def find_seed_slide_numbers(path: Path, token: str) -> List[int]:
    found: List[int] = []
    with ZipFile(path, "r") as zf:
        for slide_name in slide_xml_names(path):
            content = zf.read(slide_name).decode("utf-8", errors="ignore")
            if token in content:
                num = int(Path(slide_name).stem.replace("slide", ""))
                found.append(num)
    return sorted(found)


def find_shape_slide_numbers(path: Path, shape_name: str) -> List[int]:
    pattern = re.compile(r'<p:cNvPr\b[^>]*\bname="' + re.escape(shape_name) + r'"')
    found: List[int] = []
    with ZipFile(path, "r") as zf:
        for slide_name in slide_xml_names(path):
            content = zf.read(slide_name).decode("utf-8", errors="ignore")
            if pattern.search(content):
                num = int(Path(slide_name).stem.replace("slide", ""))
                found.append(num)
    return sorted(found)


def _slide_xml_by_number(path: Path) -> Dict[int, str]:
    slides: Dict[int, str] = {}
    with ZipFile(path, "r") as zf:
        for slide_name in slide_xml_names(path):
            num = int(Path(slide_name).stem.replace("slide", ""))
            slides[num] = zf.read(slide_name).decode("utf-8", errors="ignore")
    return slides


def _slide_text(xml: str) -> str:
    text_nodes = re.findall(r"<a:t[^>]*>(.*?)</a:t>", xml, flags=re.DOTALL)
    if text_nodes:
        text = " ".join(re.sub(r"<[^>]+>", "", node) for node in text_nodes)
    else:
        text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\{[A-Z][A-Z0-9_]*\}", " ", text)
    return " ".join(text.split()).strip()


def _slide_has_placeholder(xml: str) -> bool:
    if re.search(r"\{[A-Z][A-Z0-9_]*\}", xml):
        return True
    return re.search(r'\bname="AL_(?:TOKEN|SEED)_[A-Z0-9_]+"', xml) is not None


def _is_blank_spacer_slide(xml: str) -> bool:
    return not _slide_has_placeholder(xml) and not _slide_text(xml)


def _is_second_reading_response_slide(xml: str) -> bool:
    text = _slide_text(xml).lower()
    return "palabra de dios" in text or "te alabamos" in text


def _token_slide_numbers(path: Path, token: str, *, seed: bool) -> List[int]:
    slide_nums = set(find_seed_slide_numbers(path, token))
    shape = seed_shape_name(token) if seed else token_shape_name(token)
    slide_nums.update(find_shape_slide_numbers(path, shape))
    return sorted(slide_nums)


def tokens_by_slide(path: Path, tokens: Iterable[str]) -> Dict[int, List[str]]:
    token_list = list(tokens)
    found: Dict[int, List[str]] = {}
    with ZipFile(path, "r") as zf:
        for slide_name in slide_xml_names(path):
            content = zf.read(slide_name).decode("utf-8", errors="ignore")
            present = sorted(token for token in token_list if token in content)
            if present:
                num = int(Path(slide_name).stem.replace("slide", ""))
                found[num] = present
    return found


def _chunks_have_content(chunks: Iterable[Any] | None) -> bool:
    if not chunks:
        return False
    return any(str(chunk or "").strip() for chunk in chunks)


def _token_has_content(token: str, placeholders: Dict[str, str], chunks_map: Dict[str, List[str]]) -> bool:
    value = placeholders.get(token)
    if value is not None and str(value).strip():
        return True
    return _chunks_have_content(chunks_map.get(token))


def _append_following_blank_spacers(
    slides_to_delete: set[int],
    xml_by_slide: Dict[int, str],
    start_slide: int,
) -> None:
    slide_num = start_slide + 1
    while slide_num in xml_by_slide and _is_blank_spacer_slide(xml_by_slide[slide_num]):
        slides_to_delete.add(slide_num)
        slide_num += 1


def build_prune_plans(
    deck_path: Path,
    placeholders: Dict[str, str],
    chunks_map: Dict[str, List[str]],
) -> List[PrunePlan]:
    xml_by_slide = _slide_xml_by_number(deck_path)
    plans: List[PrunePlan] = []

    if not _token_has_content("{SECOND_READING_TXT}", placeholders, chunks_map):
        slides_to_delete = set(_token_slide_numbers(deck_path, "{SECOND_READING_REF}", seed=False))
        slides_to_delete.update(_token_slide_numbers(deck_path, "{SECOND_READING_TXT}", seed=True))
        if slides_to_delete:
            last_slide = max(slides_to_delete)
            response_slide = last_slide + 1
            if response_slide in xml_by_slide and _is_second_reading_response_slide(xml_by_slide[response_slide]):
                slides_to_delete.add(response_slide)
                last_slide = response_slide
            _append_following_blank_spacers(slides_to_delete, xml_by_slide, last_slide)
            plans.append(
                PrunePlan(
                    reason="empty {SECOND_READING_TXT}",
                    slides=tuple(sorted(slides_to_delete)),
                )
            )

    for token in HYMN_TOKENS:
        if _token_has_content(token, placeholders, chunks_map):
            continue
        slides_to_delete = set(_token_slide_numbers(deck_path, token, seed=True))
        if not slides_to_delete:
            continue
        _append_following_blank_spacers(slides_to_delete, xml_by_slide, max(slides_to_delete))
        plans.append(PrunePlan(reason=f"empty {token}", slides=tuple(sorted(slides_to_delete))))

    return plans


def prune_empty_sections(
    office: OfficeCli,
    deck_path: Path,
    placeholders: Dict[str, str],
    chunks_map: Dict[str, List[str]],
    log: Any,
) -> List[PrunePlan]:
    plans = build_prune_plans(deck_path, placeholders, chunks_map)
    slide_nums = sorted({slide for plan in plans for slide in plan.slides}, reverse=True)
    if not slide_nums:
        log("Empty-section pruning: no slides removed")
        return plans

    for plan in plans:
        slides = ", ".join(str(slide) for slide in plan.slides)
        log(f"Empty-section pruning: {plan.reason}; removing slides {slides}")

    opened = False
    try:
        office.open(deck_path)
        opened = True
        for slide_num in slide_nums:
            office.remove_slide(deck_path, slide_num)
    finally:
        if opened:
            office.close(deck_path)
    return plans


def _adjust_slide_num_after_removals(slide_num: int, removed_slides: set[int]) -> int | None:
    if slide_num in removed_slides:
        return None
    return slide_num - sum(1 for removed in removed_slides if removed < slide_num)


def _adjust_seed_targets_after_removals(targets: Iterable[SeedTarget], removed_slides: set[int]) -> List[SeedTarget]:
    adjusted: List[SeedTarget] = []
    for target in targets:
        slide_num = _adjust_slide_num_after_removals(target.slide_num, removed_slides)
        if slide_num is not None:
            adjusted.append(SeedTarget(token=target.token, slide_num=slide_num, mode=target.mode))
    return adjusted


def _simple_shape_slide_map(path: Path, removed_slides: set[int]) -> Dict[str, List[int]]:
    mapping: Dict[str, List[int]] = {}
    for token in KNOWN_TOKENS - set(WATERFALL_KEYS):
        adjusted = [
            slide_num
            for original in find_shape_slide_numbers(path, token_shape_name(token))
            for slide_num in [_adjust_slide_num_after_removals(original, removed_slides)]
            if slide_num is not None
        ]
        if adjusted:
            mapping[token] = adjusted
    return mapping


def get_unique_seed_slide_number(deck_path: Path, token: str) -> int | None:
    nums = find_seed_slide_numbers(deck_path, token)
    if not nums:
        return None
    if len(nums) > 1:
        slides = ", ".join(str(num) for num in nums)
        raise RuntimeError(f"Expected exactly one seed slide for {token}, found {len(nums)}: slides {slides}")
    return nums[0]


def get_unique_seed_target(deck_path: Path, token: str) -> SeedTarget | None:
    named_nums = find_shape_slide_numbers(deck_path, seed_shape_name(token))
    if named_nums:
        if len(named_nums) > 1:
            slides = ", ".join(str(num) for num in named_nums)
            raise RuntimeError(
                f"Expected exactly one named seed shape for {token}, found {len(named_nums)}: slides {slides}"
            )
        return SeedTarget(token=token, slide_num=named_nums[0], mode="shape")

    seed_num = get_unique_seed_slide_number(deck_path, token)
    if seed_num is None:
        return None
    return SeedTarget(token=token, slide_num=seed_num, mode="token")


def build_simple_mapping(placeholders: Dict[str, str]) -> Dict[str, str]:
    simple_mapping = {k: _sanitize_text(v) for k, v in placeholders.items() if k not in WATERFALL_KEYS}
    for token in KNOWN_TOKENS:
        if token not in placeholders and token not in WATERFALL_KEYS:
            simple_mapping[token] = ""
    return simple_mapping


def chunks_for_key(
    key: str,
    placeholders: Dict[str, str],
    chunks_map: Dict[str, List[str]],
    exact_chunk_tokens: set[str] | None = None,
) -> List[str]:
    exact_chunk_tokens = exact_chunk_tokens or set()
    if key == "{PSALM_TXT}":
        chunks = chunks_map.get(key)
        if not chunks:
            chunks = chunk_psalm_text(placeholders.get(key, "") or "")
    elif key in HYMN_TOKENS:
        chunks = chunks_map.get(key)
        if not chunks:
            raw = placeholders.get(key, "")
            chunks = [raw] if raw is not None and str(raw).strip() else []
    else:
        chunks = chunks_map.get(key)
        if not chunks:
            raw = placeholders.get(key, "")
            chunks = [raw] if raw is not None else [""]

    if key in HYMN_TOKENS:
        return [
            str(chunk).replace("\r\n", "\n").replace("\r", "\n").strip()
            for chunk in chunks
            if chunk and str(chunk).strip()
        ]

    cleaned = [_sanitize_text(chunk) for chunk in chunks if chunk and str(chunk).strip()]
    if key != "{PSALM_TXT}" and key not in exact_chunk_tokens:
        return rebalance_chunks(cleaned)
    return cleaned


def replace_simple_placeholder(office: OfficeCli, deck_path: Path, token: str, value: str) -> None:
    replace_simple_placeholder_on_slides(office, deck_path, token, value, None)


def replace_simple_placeholder_on_slides(
    office: OfficeCli,
    deck_path: Path,
    token: str,
    value: str,
    shape_slide_nums: List[int] | None,
) -> None:
    shape_name = token_shape_name(token)
    slide_nums = shape_slide_nums if shape_slide_nums is not None else find_shape_slide_numbers(deck_path, shape_name)
    if slide_nums:
        for slide_num in slide_nums:
            office.set_shape_text(deck_path, slide_num, shape_name, value)
        return
    office.replace(deck_path, "/", token, value)


def replace_waterfall_placeholder(
    office: OfficeCli,
    deck_path: Path,
    target: SeedTarget,
    slide_num: int,
    value: str,
) -> None:
    if target.mode == "shape":
        office.set_shape_text(deck_path, slide_num, seed_shape_name(target.token), value)
        return
    office.replace(deck_path, f"/slide[{slide_num}]", target.token, value)


def render_with_officecli(
    *,
    template_path: Path,
    out_path: Path,
    placeholders: Dict[str, str],
    chunks_map: Dict[str, List[str]],
    verbose: bool = False,
    office: OfficeCli | None = None,
    prune_empty: bool = True,
) -> None:
    office = office or OfficeCli(verbose=verbose)
    office.check_available()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template_path, out_path)

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    log(f"Using template: {template_path}")
    log(f"Writing output copy: {out_path}")

    if verbose:
        for slide_num, tokens in tokens_by_slide(out_path, INTERESTED_TOKENS).items():
            log(f"Initial slide {slide_num}: tokens={tokens}")
        for token in INTERESTED_TOKENS:
            idxs = find_seed_slide_numbers(out_path, token)
            if idxs:
                log(f"Initial positions {token}: {idxs} (1-based)")

    prune_plans = build_prune_plans(out_path, placeholders, chunks_map) if prune_empty else []
    removed_slides = {slide for plan in prune_plans for slide in plan.slides}

    original_seeds: List[SeedTarget] = []
    for key in WATERFALL_KEYS:
        seed_target = get_unique_seed_target(out_path, key)
        if seed_target is None:
            log(f"No seed for {key}; skipping waterfall expansion")
            continue
        original_seeds.append(seed_target)

    simple_mapping = build_simple_mapping(placeholders)
    simple_shape_slides = _simple_shape_slide_map(out_path, removed_slides)

    if prune_empty:
        prune_empty_sections(office, out_path, placeholders, chunks_map, log)
    else:
        log("Empty-section pruning disabled; blanking empty placeholders in place")

    seeds = _adjust_seed_targets_after_removals(original_seeds, removed_slides)
    removed_seed_tokens = {target.token for target in original_seeds if target.slide_num in removed_slides}
    for token in sorted(removed_seed_tokens):
        log(f"Seed for {token} was removed by empty-section pruning")
    for seed in seeds:
        log(f"Seed for {seed.token} at slide {seed.slide_num} ({seed.mode})")

    seeds.sort(key=lambda item: item.slide_num, reverse=True)

    opened = False
    try:
        office.open(out_path)
        opened = True

        for token, value in simple_mapping.items():
            replace_simple_placeholder_on_slides(
                office,
                out_path,
                token,
                value,
                simple_shape_slides.get(token),
            )

        has_second = _token_has_content("{SECOND_READING_TXT}", placeholders, chunks_map)
        if not has_second:
            log("No second reading detected; blanking any remaining second-reading placeholders.")

        for seed in seeds:
            key = seed.token
            seed_num = seed.slide_num
            chunks = chunks_for_key(key, placeholders, chunks_map)
            log(f"{key}: {len(chunks)} chunk(s)")

            if not chunks:
                replace_waterfall_placeholder(office, out_path, seed, seed_num, "")
                continue

            sequence = [seed_num]
            current_num = seed_num
            for _ in range(len(chunks) - 1):
                new_num = office.clone_slide_after(out_path, current_num, current_num)
                sequence.append(new_num)
                current_num = new_num
                log(f"{key}: cloned slide {new_num}")

            log(f"{key}: sequence slide numbers: {sequence}")
            for slide_num, chunk in zip(sequence, chunks):
                replace_waterfall_placeholder(office, out_path, seed, slide_num, chunk)
                preview = chunk[:80].replace("\n", "|")
                log(f"{key}: slide {slide_num} text set preview: {preview}...")
    finally:
        if opened:
            office.close(out_path)

    if verbose:
        remaining = tokens_by_slide(out_path, INTERESTED_TOKENS)
        if remaining:
            log(f"Remaining supported tokens: {remaining}")
        log(f"Final slide count: {slide_count(out_path)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render PPTX from JSON payload with OfficeCLI waterfall duplication.")
    parser.add_argument("--template", required=False, help="Path to template PPTX or directory (auto-pick sunday/daily)")
    parser.add_argument("--template-root", default="templates", help="Directory containing sunday-ord/daily-ord templates")
    parser.add_argument("--json", dest="json_path", required=True, help="Path to payload JSON")
    parser.add_argument("--out", required=True, help="Path to output PPTX")
    parser.add_argument("--stamp", action="store_true", help="Append timestamp to output filename")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--songs", required=False, help="Path to songs JSON providing hymn lyric chunks")
    parser.add_argument(
        "--keep-empty-sections",
        action="store_true",
        help="Keep slides for missing optional sections and blank their placeholders instead of deleting them",
    )
    args = parser.parse_args()

    payload = load_payload(args.json_path)
    template_path = Path(resolve_template_path(args, payload))
    placeholders: Dict[str, str] = dict(payload.get("placeholders", {}))
    chunks_map: Dict[str, List[str]] = dict(payload.get("chunks", {}))

    if args.songs:
        try:
            songs_chunks, songs_placeholders = _load_songs(args.songs)
            if songs_chunks and args.verbose:
                print(f"Songs provided for tokens: {sorted(songs_chunks)}")
            chunks_map = {**chunks_map, **songs_chunks}
            for key, value in songs_placeholders.items():
                if key in SONGS_PLACEHOLDER_OVERRIDE_TOKENS or not placeholders.get(key):
                    placeholders[key] = value
        except Exception as exc:
            if args.verbose:
                print(f"Warning: failed to load songs JSON '{args.songs}': {exc}")

    out_path = _stamp_output_path(args.out, args.stamp)
    try:
        render_with_officecli(
            template_path=template_path,
            out_path=out_path,
            placeholders=placeholders,
            chunks_map=chunks_map,
            verbose=args.verbose,
            prune_empty=not args.keep_empty_sections,
        )
    except OfficeCliError as exc:
        print(f"Render failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
