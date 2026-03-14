from __future__ import annotations

import feedparser
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional
import unicodedata
from datetime import date
from bs4 import BeautifulSoup

from chunking import chunk_text

FEED_URL = "https://bible.usccb.org/lecturas.rss"


def mmddyy(d: date) -> str:
    return d.strftime("%m%d%y")

def pick_item(entries, target_mmddyy: str):
    for e in entries:
        if target_mmddyy in e.link:   # robust enough for this feed
            return e
    return None

def parse_sections(desc_html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(desc_html, "html.parser")
    sections: list[tuple[str, str,]] = []

    for h4 in soup.find_all("h4"):
        header = h4.get_text(" ", strip=True)
        div = h4.find_next_sibling(lambda tag: tag and tag.name == "div" and "poetry" in tag.get("class", []))
        if not div:
            continue

        body = div_to_text(div)
        sections.append((header, body))

    return sections

def div_to_text(div) -> str:
    # convert <br> to newlines
    for br in div.find_all("br"):
        br.replace_with("\n")

    paras = []
    for p in div.find_all("p"):
        txt = p.get_text()
        # normalize whitespace
        lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
        if lines:
            paras.append("\n".join(lines))

    # blank line between paragraphs
    return "\n\n".join(paras).strip()

def strip_footer(desc_html: str) -> str:
    sep = "- - -"
    i = desc_html.find(sep)
    return desc_html if i == -1 else desc_html[:i]

def classify(header: str) -> str:
    h = header.lower()
    if h.startswith("primera lectura"):
        return "FIRST"
    if h.startswith("segunda lectura"):
        return "SECOND"
    if h.startswith("salmo responsorial"):
        return "PSALM"
    if h.startswith("aclamación antes del evangelio"):
        return "ACCLAMATION"
    if h.startswith("evangelio"):
        return "GOSPEL"
    return "OTHER"


def extract_book_phrase(header: str) -> str:
    """Extract the book phrase (optionally with leading ordinal) and drop chapter/verse.

    Examples:
      - "Primera Lectura Sofonías 3, 1-2. 9-13" -> "Sofonías"
      - "Evangelio Mateo 21, 28-32" -> "Mateo"
      - "Segunda Lectura 1 Corintios 6, 13-20" -> "1 Corintios"
      - "Segunda Lectura Primera carta a los Corintios 1, 1-3" -> "Primera carta a los Corintios"
    """
    h = header.strip()
    # Drop leading category words (Primera/Segunda Lectura, Evangelio, Salmo Responsorial)
    h = re.sub(r"^(Primera Lectura|Segunda Lectura|Evangelio|Salmo Responsorial)\s+", "", h, flags=re.I)
    # Cut off from the first occurrence of a chapter reference like " 6," or " 12:"
    h = re.split(r"\s+\d{1,3}\s*[,.:]", h, maxsplit=1)[0]
    # If nothing left (e.g., string starts with digits), fall back to non-digit prefix
    if not h.strip():
        m = re.match(r"^([^\d]+)", header)
        if m:
            h = m.group(1)
    # Normalize spacing and trim punctuation
    return " ".join(h.split()).strip(" ,·—-\u2013\u2014")


PROPHETS = {
    "Isaías", "Jeremías", "Ezequiel", "Daniel", "Oseas", "Joel", "Amós",
    "Abdías", "Jonás", "Miqueas", "Nahúm", "Habacuc", "Sofonías", "Ageo",
    "Zacarías", "Malaquías", "Baruc"
}


def _norm_key(s: str) -> str:
    """Return a lenient key for book-name matching.

    - Lowercases, strips, removes diacritics.
    - Normalizes common Greek-accent glitch for Isaías (ί -> í) and similar.
    """
    if not s:
        return ""
    # Fix common Greek iota with tonos showing up in some feeds
    s = s.replace("ί", "í").replace("Ι", "I").replace("ι", "i")
    # Unicode normalize + strip combining marks (accents)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.category(ch).startswith("M"))
    return s.strip().lower()


# Normalized lookup for prophets and a map to their canonical display names
_PROPHETS_NORM = {_norm_key(b) for b in PROPHETS}
_PROPHET_CANON = {_norm_key(b): b for b in PROPHETS}


def first_reading_intro(header: str) -> str:
    book = extract_book_phrase(header)
    nkey = _norm_key(book)
    # Prophets: prefer canonical display name to avoid odd glyphs
    if nkey in _PROPHETS_NORM:
        canon = _PROPHET_CANON.get(nkey, book)
        # Per request: include "libro del profeta"
        return f"Lectura del libro del profeta {canon}"
    # Hechos de los Apóstoles
    if "hechos" in nkey:
        return "Lectura del libro de los Hechos de los Apóstoles"
    # Feminine article (Sabiduría)
    fem_books = {"Sabiduría"}
    if book in fem_books or nkey.startswith("la "):
        return f"Lectura del libro de la {book.replace('la ', '').strip()}"
    return f"Lectura del libro de {book}"


def gospel_ref_name_only(header: str) -> str:
    return extract_book_phrase(header)


def normalize_acclamation_text(body: str) -> str:
    """Remove Aleluya/R. lines, keep only the verse."""
    lines = [ln.strip() for ln in body.splitlines()]
    kept: list[str] = []
    for ln in lines:
        low = ln.lower()
        if not ln:
            continue
        if low.startswith("r.") or "aleluya" in low:
            continue
        kept.append(ln)
    return "\n".join(kept).strip()


def extract_bible_ref_from_text(text: str) -> Optional[str]:
    """Try to extract a scripture reference like 'Lucas 21:21' or 'Is 61, 1-2'.

    Returns a normalized string using colon between chapter and verse if possible.
    """
    # Common Spanish pattern: Book Chapter, Verses  e.g., "Mateo 21, 28-32"
    m = re.search(r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)\s+(\d{1,3})\s*[,.:]\s*([\d\-–, ]+)", text)
    if not m:
        return None
    book, chap, verses = m.group(1), m.group(2), m.group(3)
    verses = verses.replace(" ", "").replace("–", "-")
    # prefer colon between chapter and verses
    return f"{book} {chap}:{verses}"


def second_reading_intro(header: str) -> str:
    """Format the Second Reading reference as said in Mass.

    Examples:
      Romans -> "Lectura de la carta del apóstol san Pablo a los Romanos"
      Ephesians -> "... a los Efesios"
      Hebrews -> "Lectura de la carta a los Hebreos"
      1 John -> "Lectura de la primera carta del apóstol san Juan"
      Revelation -> "Lectura del libro del Apocalipsis"
      James (Santiago) -> "Lectura de la carta del apóstol Santiago"
    """
    book_raw = extract_book_phrase(header)  # e.g., "Santiago", "1 Juan", "Romanos", "Primera carta a los Corintios"
    book = book_raw.strip()

    # Split possible ordinal and base name: e.g., "1 Juan" -> ("1", "Juan")
    import re
    m = re.match(r"^(\d)\s+(.+)$", book)
    ord_num = None
    base = book
    if m:
        ord_num = m.group(1)
        base = m.group(2).strip()

    def ord_spanish(n: str) -> str:
        return {"1": "primera", "2": "segunda", "3": "tercera"}.get(n, "")

    def norm(s: str) -> str:
        t = s.lower()
        # crude accent normalization for matching
        repl = {
            "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n",
        }
        for k, v in repl.items():
            t = t.replace(k, v)
        return t

    nb = norm(base)
    # If no numeric ordinal, detect spelled ordinal words present in the phrase
    if not ord_num:
        whole = norm(book)
        # Also useful for special-case checks below
        if "primera" in whole:
            ord_num = "1"
        elif "segunda" in whole:
            ord_num = "2"
        elif "tercera" in whole:
            ord_num = "3"

    # Special cases not attributed to an apostle name
    # Acts of the Apostles appears sometimes as second reading (e.g., solemnities)
    if "hechos" in (nb or "") or "hechos" in (norm(book) or ""):
        return "Lectura del libro de los Hechos de los Apóstoles"
    if nb == "hebreos":
        return "Lectura de la carta a los Hebreos"
    if nb == "apocalipsis":
        return "Lectura del libro del Apocalipsis"

    # Apostle John letters
    if nb == "juan":
        if ord_num:
            return f"Lectura de la {ord_spanish(ord_num)} carta del apóstol san Juan"
        return "Lectura de la carta del apóstol san Juan"

    # Apostle Peter letters
    if nb == "pedro":
        if ord_num:
            return f"Lectura de la {ord_spanish(ord_num)} carta del apóstol san Pedro"
        return "Lectura de la carta del apóstol san Pedro"

    # Apostle Paul letters to communities/persons
    # Map Spanish plurals that take "a los ..." and singular "a ..."
    pauline_plurals = {
        "romanos": "Romanos",
        "corintios": "Corintios",
        "galatas": "Gálatas",
        "filipenses": "Filipenses",
        "colosenses": "Colosenses",
        "tesalonicenses": "Tesalonicenses",
        "efesios": "Efesios",
    }
    pauline_singulars = {
        "timoteo": "Timoteo",
        "tito": "Tito",
        "filemon": "Filemón",
    }
    # Sometimes the phrase can include extra words (e.g., "Primera carta a los Corintios").
    # Detect target names by presence rather than strict equality.
    def find_key(keys: dict, text: str) -> Optional[str]:
        for k in keys:
            if re.search(rf"\b{k}\b", text):
                return k
        return None

    key = find_key(pauline_plurals, nb) or find_key(pauline_plurals, norm(book))
    if key:
        if ord_num in ("1", "2"):
            return f"Lectura de la {ord_spanish(ord_num)} carta del apóstol san Pablo a los {pauline_plurals[key]}"
        return f"Lectura de la carta del apóstol san Pablo a los {pauline_plurals[key]}"

    key = find_key(pauline_singulars, nb) or find_key(pauline_singulars, norm(book))
    if key:
        if ord_num in ("1", "2"):
            return f"Lectura de la {ord_spanish(ord_num)} carta del apóstol san Pablo a {pauline_singulars[key]}"
        return f"Lectura de la carta del apóstol san Pablo a {pauline_singulars[key]}"

    # James (Santiago), Jude (Judas), etc.
    if nb == "santiago":
        return "Lectura de la carta del apóstol Santiago"
    if nb == "judas":
        return "Lectura de la carta del apóstol Judas"

    # Fallback: generic "Lectura de la carta de {Book}"
    return f"Lectura de la carta de {base}"

def to_placeholders(item_title: str, sections: list[tuple[str, str]]) -> dict[str, str]:
    ph = {"{LITURGICAL_DAY}": item_title}

    for header, body in sections:
        kind = classify(header)

        if kind == "FIRST":
            ph["{FIRST_READING_REF}"] = first_reading_intro(header)
            ph["{FIRST_READING_TXT}"] = body
        elif kind == "PSALM":
            # Remove leading 'Salmo Responsorial' while keeping the psalm reference
            ps_ref = re.sub(r"^Salmo\s+Responsorial\s+", "", header, flags=re.I).strip()
            ph["{PSALM_REF}"] = ps_ref
            ph["{PSALM_TXT}"] = body
        elif kind == "SECOND":
            ph["{SECOND_READING_REF}"] = second_reading_intro(header)
            ph["{SECOND_READING_TXT}"] = body
        elif kind == "ACCLAMATION":
            # Trim Aleluya/R. lines; attempt to derive a reference
            verse_only = normalize_acclamation_text(body)
            acc_ref = extract_bible_ref_from_text(body) or ""
            ph["{ACCLAMATION_REF}"] = acc_ref
            ph["{ACCLAMATION_TXT}"] = verse_only
        elif kind == "GOSPEL":
            ph["{GOSPEL_REF}"] = gospel_ref_name_only(header)
            ph["{GOSPEL_TXT}"] = body

    return ph

def normalize_text(s: str) -> str:
    # normalize line endings + trim trailing spaces on each line
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in s.split("\n")]
    # collapse 3+ blank lines to at most 2
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def chunkify(
    text: str,
    max_chars: int = 210,
    min_chars: int = 90,
) -> List[str]:
    return chunk_text(text, min_chars=min_chars, hard_max_chars=max_chars)


def build_payload(
    d: date,
    language: str,
    source: str,
    link: str,
    title: str,
    placeholders: Dict[str, str],
    chunks: Optional[Dict[str, List[str]]] = None,
) -> Dict:
    payload = {
        "meta": {
            "date": d.isoformat(),
            "language": language,
            "source": source,
            "link": link,
            "title": title,
        },
        "placeholders": {k: normalize_text(v) for k, v in placeholders.items()},
    }
    if chunks:
        payload["chunks"] = {k: [normalize_text(x) for x in v] for k, v in chunks.items()}
    return payload


def write_payload_json(payload: Dict, out_path: str | Path) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

def make_chunks(placeholders: Dict[str, str]) -> Dict[str, List[str]]:
    """
    only chunk the long body fields that can span multiple slides.
    you can add/remove keys as your template grows.
    """
    keys_to_chunk = [
        "{FIRST_READING_TXT}",
        "{SECOND_READING_TXT}",
        "{PSALM_TXT}",
        "{GOSPEL_TXT}",
    ]

    out: Dict[str, List[str]] = {}
    for k in keys_to_chunk:
        txt = placeholders.get(k, "")
        if txt.strip():
            out[k] = chunkify(txt)
    return out


def parse_date_arg(s: str) -> date:
    """Parse a date string. Supports:
    - YYYY-MM-DD (ISO)
    - MM-DD-YY (e.g., 12-14-25 -> 2025-12-14)
    - MM/DD/YY
    """
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%m-%d-%y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unrecognized date format: {s}")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Fetch USCCB RSS item and build JSON payload.")
    ap.add_argument("--date", dest="date_str", help="Target date (YYYY-MM-DD or MM-DD-YY)")
    ap.add_argument("--out", dest="out_path", help="Output JSON path (default: out/YYYY-MM-DD.es-US.json)")
    args = ap.parse_args()

    target_date = parse_date_arg(args.date_str) if args.date_str else date.today()

    parsed = feedparser.parse(FEED_URL)
    entries = parsed.entries

    dt_key = mmddyy(target_date)

    item = pick_item(entries, dt_key)
    if item is None:
        raise RuntimeError(f"No RSS item found for {dt_key}")

    # parse readings from description html
    cleaned = strip_footer(item.description)
    sections = parse_sections(cleaned)

    # placeholders for your pptx replacements
    placeholders = to_placeholders(item.title, sections)

    # chunk only the long text fields
    chunks = make_chunks(placeholders)

    payload = build_payload(
        d=target_date,
        language="es-US",
        source="usccb_rss",
        link=item.link,
        title=item.title,
        placeholders=placeholders,
        chunks=chunks,
    )

    default_out = Path("out") / f"{target_date.isoformat()}.es-US.json"
    out_path = Path(args.out_path) if args.out_path else default_out
    write_payload_json(payload, out_path)

    print(f"wrote: {out_path}")
    print(f"title: {item.title}")
    print(f"sections: {len(sections)}")
    for k, v in chunks.items():
        print(f"{k}: {len(v)} chunks")


if __name__ == "__main__":
    main()
