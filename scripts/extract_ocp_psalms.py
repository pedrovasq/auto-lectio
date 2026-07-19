from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fetch as fetch_mod
from render import chunk_psalm_text


DEFAULT_PDF = ROOT / "songs" / "Responde_Y_Aclama_2026_Libro_Electronico_Para_Imprimirse.pdf"
DEFAULT_OUT_DIR = ROOT / "songs" / "days"

SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

NOISE_LINES = {
    "Inicio | Páginas",
    "Inicio | Índices | Páginas",
    "Índice de Celebraciones",
    "Índice de Celebraciones | Índice Bíblico | Índice del Año Litúrgico | Índice Ritual | Índice Alfabético",
}

DATE_LINE_RE = re.compile(
    r"^(?P<day>\d{1,2})(?:º)?(?:\s+o\s+\d{1,2})?\s+de\s+"
    r"(?P<month>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)\s+(?P<page>\d{1,3})$"
)


@dataclass(frozen=True)
class OcpEntry:
    date: date
    title: str
    pdf_page: int
    date_text: str


@dataclass(frozen=True)
class PdfRefs:
    psalm_ref: str = ""
    acclamation_ref: str = ""


@dataclass(frozen=True)
class PdfEntryText:
    refs: PdfRefs
    psalm_text: str = ""
    acclamation_res: str = ""
    acclamation_verse: str = ""


def _run_pdftotext(pdf_path: Path, first_page: int, last_page: int, layout: bool = False) -> str:
    cmd = ["pdftotext", "-f", str(first_page), "-l", str(last_page)]
    if layout:
        cmd.append("-layout")
    else:
        cmd.append("-raw")
    cmd.extend([str(pdf_path), "-"])
    result = subprocess.run(cmd, check=True, text=True, capture_output=True)
    return result.stdout


def _clean_index_line(line: str) -> str:
    line = line.replace("\f", "").replace("\u0008", "")
    line = re.sub(r"\s+", " ", line).strip()
    return line


def _entry_year(month: int, season_start_year: int) -> int:
    return season_start_year if month in (11, 12) else season_start_year + 1


def parse_celebration_index(text: str, season_start_year: int = 2025) -> list[OcpEntry]:
    entries: list[OcpEntry] = []
    title_lines: list[str] = []
    current_year = season_start_year
    previous_month: int | None = None

    for raw_line in text.splitlines():
        line = _clean_index_line(raw_line)
        if not line or line in NOISE_LINES:
            continue
        if re.fullmatch(r"\d{3}", line):
            continue
        if line.startswith("ÍNDICE DE CELEBRACIONES"):
            continue
        if line.startswith("Salmo Selecto"):
            title_lines = []
            continue

        match = DATE_LINE_RE.match(line)
        if not match:
            if re.search(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\b", line):
                title_lines = []
                continue
            title_lines.append(line)
            continue

        month_name = match.group("month").lower()
        month = SPANISH_MONTHS.get(month_name)
        if not month or not title_lines:
            title_lines = []
            continue

        if previous_month is not None and month < previous_month:
            current_year += 1
        previous_month = month

        day = int(match.group("day"))
        pdf_page = int(match.group("page"))
        title = " ".join(title_lines).strip()
        entries.append(
            OcpEntry(
                date=date(current_year, month, day),
                title=title,
                pdf_page=pdf_page,
                date_text=line.rsplit(" ", 1)[0],
            )
        )
        title_lines = []

    return entries


def extract_refs_from_entry_text(text: str) -> PdfRefs:
    psalm_ref = ""
    acclamation_ref = ""

    for raw_line in text.splitlines():
        line = _clean_index_line(raw_line)
        if not line:
            continue
        if not psalm_ref:
            match = re.search(r"Salmo\s+Responsorial:\s*(.+?)(?:\s{2,}|$)", line, flags=re.I)
            if match:
                psalm_ref = _clean_pdf_ref(match.group(1))
        if not acclamation_ref:
            match = re.search(r"Aclamación\s+Antes\s+del\s+Evangelio:\s*(.+?)(?:\s{2,}|$)", line, flags=re.I)
            if match:
                acclamation_ref = _clean_pdf_ref(match.group(1))

    return PdfRefs(psalm_ref=psalm_ref, acclamation_ref=acclamation_ref)


def _clean_pdf_ref(value: str) -> str:
    value = value.replace("\u0008", " ")
    value = re.split(r"(?:Arr\.|Teclado|Música|Letra)", value, maxsplit=1)[0]
    value = re.sub(r"\s+", " ", value).strip(" .")
    psalm_match = re.match(r"^(Salmo\s+\d+(?:\s*\(\d+\))?(?:,\s*[0-9a-zº\s().,–\-y]+)?)", value)
    if psalm_match:
        value = psalm_match.group(1).strip(" .")
    return value


CHORD_RE = re.compile(
    r"^(?:[A-G](?:#|b)?(?:m|m7|maj7|sus4|dim7|7|9)?(?:/[A-G](?:#|b)?(?:m|7)?)?|"
    r"(?:Do|Re|Mi|Fa|Sol|La|Si)(?:\s?#|\sb|m|7|9|sus4|dis7)?(?:/(?:Do|Re|Mi|Fa|Sol|La|Si)(?:\s?#|\sb)?)?)$"
)

ENGLISH_CHORD_RE = re.compile(
    r"^[A-G](?:#|b)?(?:m|m7|maj7|sus4|dim7|7|9)?(?:/[A-G](?:#|b)?(?:m|7)?)?$"
)

NOISE_TEXT_RE = re.compile(
    r"(?:Inicio \| Índices|Teclado|Letra ©|Música|Derechos reservados|Administradora exclusiva|"
    r"Respuesta:|Estrofas:|Versículo:|cont\.|^\d{3}$|^\(?\s*\)?$|Pbro\.|Arr\.)"
)

CHORD_FRAGMENT_RE = re.compile(r"^(?:m|m7|sus4|7|9|m/Re|m7/Re|m/Mi|m/Si|7/Do|7/Sol)$", flags=re.I)
SPANISH_CHORD_TOKEN_RE = re.compile(
    r"^(?:Do|Re|Mi|Fa|Sol|La|Si)(?:#|b|m|m7|maj7|sus4|dim7|7|9|add9)?(?:/(?:Do|Re|Mi|Fa|Sol|La|Si)(?:#|b)?)?$"
)
BYLINE_RE = re.compile(r"^[A-ZÁÉÍÓÚÜÑ][\wÁÉÍÓÚÜÑáéíóúüñ.\-]+(?:,?\s+y\s+|\s+)[A-ZÁÉÍÓÚÜÑ]")

SYLLABLE_FIXES = [
    (r"\bSe\s+ñor\b", "Señor"),
    (r"\be\s+res\b", "eres"),
    (r"\bbue\s+no\b", "bueno"),
    (r"\bcle\s+men\s+te\b", "clemente"),
    (r"\bcle\s+mente\b", "clemente"),
    (r"\bmiseri\s+cor\s+dioso\b", "misericordioso"),
    (r"\bcor\s+dioso\b", "cordioso"),
    (r"\bin\s+vocan\b", "invocan"),
    (r"\bo\s+ra\s+ción\b", "oración"),
    (r"\bma\s+ra\s+villas\b", "maravillas"),
    (r"\ble\s+al\b", "leal"),
    (r"\búni\s+co\b", "único"),
    (r"\bsen\s+cilla\b", "sencilla"),
    (r"\bgen\s+te\b", "gente"),
]


def _strip_chords(line: str) -> str:
    words = line.split()
    kept = [
        word
        for word in words
        if not ENGLISH_CHORD_RE.match(word.strip("()"))
        and not CHORD_FRAGMENT_RE.match(word.strip("()"))
    ]
    return " ".join(kept)


def _strip_spanish_chord_noise(line: str) -> str:
    words = line.split()
    if not words:
        return line

    def is_chord_token(word: str) -> bool:
        return bool(SPANISH_CHORD_TOKEN_RE.match(word.strip("()")))

    remove: set[int] = set()
    start = 1 if words and words[0] == "R." else 0
    cluster_end = start
    while cluster_end < len(words) and (
        is_chord_token(words[cluster_end])
        or words[cluster_end] in {"b", "#", "Capo"}
        or re.fullmatch(r"\d+", words[cluster_end])
    ):
        cluster_end += 1
    if cluster_end - start >= 2:
        remove.update(range(start, cluster_end))

    for i, word in enumerate(words):
        bare = word.strip("()")
        if bare in {"Capo", "Final", "Fin", "%", "U"}:
            remove.add(i)
        if bare in {"Do", "Re", "Fa", "Sol"} and i != 0:
            remove.add(i)
        if is_chord_token(word) and ("/" in bare or any(ch.isdigit() for ch in bare)):
            remove.add(i)
        if bare in {"Mi", "La", "Si"}:
            prev_is_chord = i > 0 and is_chord_token(words[i - 1])
            next_is_chord = i + 1 < len(words) and is_chord_token(words[i + 1])
            if prev_is_chord or next_is_chord:
                remove.add(i)
        if bare in {"b", "#", "j", "J"}:
            prev_removed = i > 0 and (i - 1) in remove
            next_removed = i + 1 < len(words) and (
                (i + 1) in remove or is_chord_token(words[i + 1])
            )
            if prev_removed or next_removed:
                remove.add(i)

    return " ".join(word for i, word in enumerate(words) if i not in remove)


def _clean_pdf_lyric_line(line: str) -> str:
    line = line.replace("\u0008", " ")
    line = re.sub(r"\b\d{3}\b", " ", line)
    line = _strip_chords(line)
    line = re.sub(r"\s+", " ", line).strip()
    line = re.sub(r"\bá\s+Española\.\s+Inicio\s+\d+\s+j\b", " ", line)
    line = re.sub(r"\bInicio\s+\d+\s+j\b", " ", line)
    line = re.sub(r"\(\s*\)", " ", line)
    line = re.sub(r"(?<=\w)\s*-\s*(?=\w)", "", line)
    line = re.sub(r"\s+", " ", line).strip()
    line = _strip_spanish_chord_noise(line)
    line = line.strip("() ")
    for pattern, replacement in SYLLABLE_FIXES:
        line = re.sub(pattern, replacement, line, flags=re.I)
    line = re.sub(r"\s+([,.;:!?])", r"\1", line)
    line = re.sub(r"([¿¡])\s+", r"\1", line)
    return line.strip()


def _is_noise_or_chord_line(line: str) -> bool:
    cleaned = _clean_index_line(line)
    if not cleaned:
        return True
    if cleaned in {"j", "J"}:
        return True
    if NOISE_TEXT_RE.search(cleaned):
        return True
    if BYLINE_RE.match(cleaned) and not re.search(r"[,.;:!?¿¡“”]", cleaned):
        return True
    if all(CHORD_RE.match(word.strip("()")) for word in cleaned.split()):
        return True
    if re.search(r"[œ˙∑‰Œ&#?]+", cleaned):
        return True
    return False


def _section_between(text: str, start_pattern: str, end_patterns: list[str]) -> str:
    match = re.search(start_pattern, text, flags=re.I)
    if not match:
        return ""
    start = match.end()
    end = len(text)
    for pattern in end_patterns:
        end_match = re.search(pattern, text[start:], flags=re.I)
        if end_match:
            end = min(end, start + end_match.start())
    return text[start:end]


def _dedupe_keep_order(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = item.lower()
        if item and key not in seen:
            out.append(item)
            seen.add(key)
    return out


def extract_pdf_entry_text(text: str, acclamation_mode: str = "ordinary") -> PdfEntryText:
    refs = extract_refs_from_entry_text(text)

    response_section = _section_between(text, r"Respuesta:\s*(?:\([^)]*\))?", [r"\n\s*Estrofas:"])
    response_lines = [
        _clean_pdf_lyric_line(line)
        for line in response_section.splitlines()
        if not _is_noise_or_chord_line(line)
    ]
    response_lines = _dedupe_keep_order(line for line in response_lines if line)
    psalm_response = " ".join(response_lines).strip()
    if psalm_response:
        psalm_response = f"R. {psalm_response}"

    verse_section = _section_between(text, r"\n\s*Estrofas:\s*", [r"\n\s*Aclamación\s+Antes\s+del\s+Evangelio:"])
    stanza_parts: dict[str, list[str]] = {}
    last_num = ""
    for raw_line in verse_section.splitlines():
        if _is_noise_or_chord_line(raw_line):
            continue
        line = _clean_pdf_lyric_line(raw_line)
        if not line:
            continue
        match = re.match(r"^([1-9])\.\s*(.*)$", line)
        if match:
            last_num = match.group(1)
            text_part = match.group(2).strip()
        elif last_num:
            text_part = line
        else:
            continue
        if not text_part:
            continue
        stanza_parts.setdefault(last_num, []).append(text_part)

    stanzas: list[str] = []
    for stanza_num in sorted(stanza_parts, key=int):
        parts = _dedupe_keep_order(stanza_parts[stanza_num])
        stanza = " ".join(parts)
        stanza = _clean_pdf_lyric_line(stanza)
        if stanza:
            stanzas.append(stanza)

    psalm_lines = [line for line in [psalm_response, *stanzas] if line]

    acclamation_section = _section_between(text, r"Aclamación\s+Antes\s+del\s+Evangelio:.*", [r"\n\s*Versículo:"])
    if re.search(r"\bA\s+le\s+lu\s+ya\b|Aleluya", acclamation_section, flags=re.I):
        acclamation_res = "Aleluya, Aleluya, Aleluya"
    else:
        acclamation_res = fetch_mod.acclamation_response_for_mode(acclamation_mode)

    acclamation_verse_section = _section_between(text, r"\n\s*Versículo:\s*", [r"\n\s*Letra del versículo", r"\n\s*Letra ©"])
    acclamation_lines = [
        _clean_pdf_lyric_line(line)
        for line in acclamation_verse_section.splitlines()
        if not _is_noise_or_chord_line(line)
    ]
    acclamation_lines = _dedupe_keep_order(line for line in acclamation_lines if line)

    return PdfEntryText(
        refs=refs,
        psalm_text="\n".join(psalm_lines),
        acclamation_res=acclamation_res,
        acclamation_verse=" ".join(acclamation_lines).strip(),
    )


DIRECT_SECTION_HEADINGS = {
    "Primera lectura",
    "Salmo Responsorial",
    "Segunda lectura",
    "Aclamación antes del Evangelio",
    "Evangelio",
}


def parse_direct_usccb_sections(html: str) -> tuple[str, list[tuple[str, str]]]:
    soup = fetch_mod.BeautifulSoup(html, "html.parser")
    title = ""
    title_heading = soup.find("h1", class_="title-page")
    if title_heading:
        for heading in title_heading.find_all_next(["h2", "h3"]):
            if "visually-hidden" in (heading.get("class") or []):
                continue
            text = " ".join(heading.get_text(" ", strip=True).split())
            if text:
                title = text
                break
    if not title:
        for heading in soup.find_all(["h1", "h2"]):
            if "visually-hidden" in (heading.get("class") or []):
                continue
            text = " ".join(heading.get_text(" ", strip=True).split())
            if text and text not in {"Lecturas de Hoy"}:
                title = text
                break

    lines = [" ".join(line.split()) for line in soup.get_text("\n", strip=True).splitlines()]
    lines = [line for line in lines if line]
    sections: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        heading = lines[i]
        if heading not in DIRECT_SECTION_HEADINGS:
            i += 1
            continue

        i += 1
        body_lines: list[str] = []
        while i < len(lines) and lines[i] not in DIRECT_SECTION_HEADINGS and lines[i] != "O bien:":
            if lines[i].startswith("Lectionary:"):
                i += 1
                continue
            body_lines.append(lines[i])
            i += 1

        if not body_lines:
            continue
        ref = body_lines[0]
        body = "\n".join(body_lines[1:]).strip()
        if heading == "Salmo Responsorial":
            header = f"Salmo Responsorial {ref}"
        elif heading == "Aclamación antes del Evangelio":
            header = f"Aclamación antes del Evangelio {ref}"
        elif heading == "Primera lectura":
            header = f"Primera Lectura {ref}"
        elif heading == "Segunda lectura":
            header = f"Segunda Lectura {ref}"
        else:
            header = f"Evangelio {ref}"
        sections.append((header, body))

    return title, sections


def _curl_direct_usccb_html(link: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        cookie_path = Path(tmp) / "cookies.txt"
        subprocess.run(
            ["curl", "-sL", "-c", str(cookie_path), "-I", link],
            check=True,
            text=True,
            capture_output=True,
        )
        result = subprocess.run(
            ["curl", "-sL", "-b", str(cookie_path), "--compressed", link],
            check=True,
            text=True,
            capture_output=True,
        )
    return result.stdout


def fetch_direct_usccb_payload(target_date: date, acclamation_mode: str = "ordinary") -> dict[str, Any]:
    link = f"https://bible.usccb.org/es/bible/lecturas/{fetch_mod.mmddyy(target_date)}.cfm"
    html = ""
    errors: list[str] = []

    for attempt in range(3):
        try:
            html = _curl_direct_usccb_html(link)
            title, sections = parse_direct_usccb_sections(html)
            if sections:
                placeholders = fetch_mod.to_placeholders(
                    title or target_date.isoformat(),
                    sections,
                    acclamation_mode=acclamation_mode,
                )
                return fetch_mod.build_payload(
                    d=target_date,
                    language="es-US",
                    source="usccb_direct",
                    link=link,
                    title=title or target_date.isoformat(),
                    placeholders=placeholders,
                    chunks=fetch_mod.make_chunks(placeholders),
                )
            errors.append(f"attempt {attempt + 1}: no reading sections found")
        except Exception as exc:
            errors.append(f"attempt {attempt + 1}: {exc}")

    raise RuntimeError(f"No readings found on direct USCCB page for {target_date.isoformat()}: {'; '.join(errors)}")


def chunk_pdf_psalm_text(psalm_text: str) -> list[str]:
    lines = [line.strip() for line in psalm_text.splitlines() if line.strip()]
    if not lines:
        return []
    response = lines[0] if lines[0].startswith("R.") else ""
    if not response:
        return lines
    chunks = [response]
    for stanza in lines[1:]:
        chunks.append(stanza)
        chunks.append(response)
    if len(chunks) > 1:
        chunks.pop()
    return chunks


def fetch_reading_payload(
    target_date: date,
    acclamation_mode: str = "ordinary",
) -> dict[str, Any]:
    parsed = fetch_mod.feedparser.parse(fetch_mod.FEED_URL)
    item = fetch_mod.pick_item(parsed.entries, fetch_mod.mmddyy(target_date))
    if item is not None:
        sections = fetch_mod.parse_sections(fetch_mod.strip_footer(item.description))
        placeholders = fetch_mod.to_placeholders(item.title, sections, acclamation_mode=acclamation_mode)
        return fetch_mod.build_payload(
            d=target_date,
            language="es-US",
            source="usccb_rss",
            link=item.link,
            title=item.title,
            placeholders=placeholders,
            chunks=fetch_mod.make_chunks(placeholders),
        )

    return fetch_direct_usccb_payload(target_date, acclamation_mode=acclamation_mode)


def missing_reading_payload(target_date: date, error: Exception) -> dict[str, Any]:
    return {
        "meta": {
            "date": target_date.isoformat(),
            "language": "es-US",
            "source": "missing_usccb",
            "link": "",
            "title": "",
            "error": str(error),
        },
        "placeholders": {
            "{PSALM_REF}": "",
            "{PSALM_TXT}": "",
            "{ACCLAMATION_RES}": "",
            "{ACCLAMATION_VERSE}": "",
        },
        "chunks": {},
    }


def pdf_reading_payload(
    target_date: date,
    entry: OcpEntry,
    pdf_text: PdfEntryText,
) -> dict[str, Any]:
    placeholders = {
        "{PSALM_REF}": pdf_text.refs.psalm_ref,
        "{PSALM_TXT}": pdf_text.psalm_text,
        "{ACCLAMATION_RES}": pdf_text.acclamation_res,
        "{ACCLAMATION_VERSE}": pdf_text.acclamation_verse,
    }
    return {
        "meta": {
            "date": target_date.isoformat(),
            "language": "es-US",
            "source": "ocp_pdf_text",
            "link": "",
            "title": entry.title,
        },
        "placeholders": placeholders,
        "chunks": {"{PSALM_TXT}": chunk_pdf_psalm_text(placeholders["{PSALM_TXT}"])},
    }


def build_day_songs_payload(
    entry: OcpEntry,
    reading_payload: dict[str, Any],
    pdf_name: str,
    refs: PdfRefs | None = None,
) -> dict[str, Any]:
    placeholders = reading_payload.get("placeholders") or {}
    refs = refs or PdfRefs()

    day_placeholders = {
        key: str(placeholders.get(key) or "").strip()
        for key in ("{PSALM_REF}", "{PSALM_TXT}", "{ACCLAMATION_RES}", "{ACCLAMATION_VERSE}")
    }
    source = str((reading_payload.get("meta") or {}).get("source") or "")
    source_chunks = reading_payload.get("chunks") or {}
    if source == "ocp_pdf_text" and isinstance(source_chunks.get("{PSALM_TXT}"), list):
        psalm_chunks = [str(chunk) for chunk in source_chunks["{PSALM_TXT}"] if str(chunk).strip()]
    else:
        psalm_chunks = chunk_psalm_text(day_placeholders["{PSALM_TXT}"])

    return {
        "meta": {
            "date": entry.date.isoformat(),
            "language": "es-US",
            "source": f"ocp_pdf_index+{reading_payload.get('meta', {}).get('source', 'unknown')}",
            "title": entry.title,
            "pdf": pdf_name,
            "pdf_page": entry.pdf_page,
            "pdf_psalm_ref": refs.psalm_ref,
            "pdf_acclamation_ref": refs.acclamation_ref,
            "usccb_title": str((reading_payload.get("meta") or {}).get("title") or ""),
            "usccb_link": str((reading_payload.get("meta") or {}).get("link") or ""),
            "usccb_error": str((reading_payload.get("meta") or {}).get("error") or ""),
        },
        "placeholders": day_placeholders,
        "chunks": {
            "{PSALM_TXT}": psalm_chunks,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _normalize_ref(value: str) -> str:
    value = value.lower()
    value = value.replace("\u2013", "-").replace("\u2014", "-")
    value = re.sub(r"[^a-z0-9áéíóúüñ]+", "", value)
    return value


def _review_status(payload: dict[str, Any]) -> str:
    meta = payload.get("meta") or {}
    pdf_psalm = str(meta.get("pdf_psalm_ref") or "")
    usccb_psalm = str((payload.get("placeholders") or {}).get("{PSALM_REF}") or "")
    if not usccb_psalm:
        return "missing_usccb_psalm"
    if str(meta.get("source") or "").endswith("ocp_pdf_text"):
        return "pdf_text_review"
    if pdf_psalm and _normalize_ref(pdf_psalm) not in _normalize_ref(usccb_psalm):
        return "review_pdf_usccb_psalm_ref"
    return "ok"


def write_review_files(out_dir: Path, payloads: Iterable[dict[str, Any]]) -> None:
    payload_list = list(payloads)
    out_dir.mkdir(parents=True, exist_ok=True)
    index = [
        {
            "date": str((payload.get("meta") or {}).get("date") or ""),
            "title": str((payload.get("meta") or {}).get("title") or ""),
            "file": f"{(payload.get('meta') or {}).get('date')}.es-US.json",
            "pdf_page": (payload.get("meta") or {}).get("pdf_page"),
            "status": _review_status(payload),
        }
        for payload in payload_list
    ]
    write_json(out_dir / "index.json", {"entries": index})

    with (out_dir / "review.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "date",
                "title",
                "pdf_page",
                "pdf_psalm_ref",
                "usccb_psalm_ref",
                "pdf_acclamation_ref",
                "usccb_acclamation_verse",
                "status",
                "source",
            ],
        )
        writer.writeheader()
        for payload in payload_list:
            meta = payload.get("meta") or {}
            placeholders = payload.get("placeholders") or {}
            writer.writerow(
                {
                    "date": meta.get("date") or "",
                    "title": meta.get("title") or "",
                    "pdf_page": meta.get("pdf_page") or "",
                    "pdf_psalm_ref": meta.get("pdf_psalm_ref") or "",
                    "usccb_psalm_ref": placeholders.get("{PSALM_REF}") or "",
                    "pdf_acclamation_ref": meta.get("pdf_acclamation_ref") or "",
                    "usccb_acclamation_verse": placeholders.get("{ACCLAMATION_VERSE}") or "",
                    "status": _review_status(payload),
                    "source": meta.get("source") or "",
                }
            )


def generate_payloads(
    *,
    pdf_path: Path,
    start_date: date,
    season_start_year: int,
    acclamation_mode: str,
    index_first_page: int,
    index_last_page: int,
    limit: int | None,
    fetcher: Callable[[date, str], dict[str, Any]] = fetch_reading_payload,
) -> list[dict[str, Any]]:
    index_text = _run_pdftotext(pdf_path, index_first_page, index_last_page)
    entries = [
        entry
        for entry in parse_celebration_index(index_text, season_start_year=season_start_year)
        if entry.date >= start_date
    ]
    if limit is not None:
        entries = entries[:limit]

    payloads: list[dict[str, Any]] = []
    for entry in entries:
        entry_text = _run_pdftotext(pdf_path, entry.pdf_page, min(entry.pdf_page + 2, 245), layout=True)
        pdf_text = extract_pdf_entry_text(entry_text, acclamation_mode=acclamation_mode)
        try:
            reading_payload = fetcher(entry.date, acclamation_mode)
        except Exception as exc:
            reading_payload = pdf_reading_payload(entry.date, entry, pdf_text)
            reading_payload["meta"]["error"] = str(exc)
        payloads.append(build_day_songs_payload(entry, reading_payload, pdf_path.name, pdf_text.refs))
    return payloads


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate per-day psalm/acclamation JSON files from the OCP Responde y Aclama PDF index."
    )
    parser.add_argument("--pdf", default=str(DEFAULT_PDF), help="Path to Responde y Aclama PDF")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Directory for generated day JSON files")
    parser.add_argument("--start-date", default="2026-07-19", help="First date to generate, YYYY-MM-DD")
    parser.add_argument("--season-start-year", type=int, default=2025, help="Liturgical season start year")
    parser.add_argument("--index-first-page", type=int, default=232, help="First PDF page of Índice de Celebraciones")
    parser.add_argument("--index-last-page", type=int, default=234, help="Last PDF page of Índice de Celebraciones")
    parser.add_argument("--acclamation-mode", default="ordinary", choices=sorted(fetch_mod.ACCLAMATION_RESPONSES))
    parser.add_argument("--limit", type=int, help="Generate only the first N matching entries")
    parser.add_argument("--dry-run", action="store_true", help="Print planned outputs without writing JSON files")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_path = Path(args.pdf)
    out_dir = Path(args.out_dir)
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()

    payloads = generate_payloads(
        pdf_path=pdf_path,
        start_date=start_date,
        season_start_year=args.season_start_year,
        acclamation_mode=args.acclamation_mode,
        index_first_page=args.index_first_page,
        index_last_page=args.index_last_page,
        limit=args.limit,
    )

    if args.dry_run:
        for payload in payloads:
            meta = payload["meta"]
            print(f"{meta['date']} page {meta['pdf_page']}: {meta['title']}")
        print(f"Would generate {len(payloads)} day file(s) in {out_dir}")
        return

    for payload in payloads:
        out_path = out_dir / f"{payload['meta']['date']}.es-US.json"
        write_json(out_path, payload)
        print(f"wrote: {out_path}")
    write_review_files(out_dir, payloads)
    print(f"wrote: {out_dir / 'index.json'}")
    print(f"wrote: {out_dir / 'review.csv'}")


if __name__ == "__main__":
    main()
