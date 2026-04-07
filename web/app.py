from __future__ import annotations

import os
import re
import sys
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict
from zipfile import ZipFile

from flask import Flask, jsonify, render_template, request, send_from_directory
import json
from werkzeug.utils import secure_filename

# Ensure project root is importable when running as `python web/app.py`
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import fetch helpers directly so we don't have to shell out for fetch
import fetch as fetch_mod


app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 65 * 1024 * 1024  # 65 MB upload limit

TEMPLATE_DIR_SPECS = [
    ("library", ROOT / "templates" / "library", "Library"),
    ("custom", ROOT / "templates" / "custom", "Custom"),
    ("uploads", ROOT / "templates" / "uploads", "Uploads"),
]


# ---- Songs helpers: build JSON from UI config (reads parts from songs/parts) ----
def _split_chunks(text: str) -> list[str]:
    if not text:
        return []
    t = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not t:
        return []
    parts = [p.strip() for p in t.split("\n\n")]
    return [p for p in parts if p]


def _part_path(kind: str, lang: str | None = None, version: str | None = None) -> Path:
    base = ROOT / "songs" / "parts"
    if kind == "mysterium":
        if not lang or not version:
            return Path("")
        return base / f"mysterium.{lang}.{version}.json"
    if kind == "gloria":
        if not lang:
            return Path("")
        return base / f"gloria.{lang}.json"
    # kyrie, sanctus, agnus
    if not lang:
        return Path("")
    return base / f"{kind}.{lang}.json"


def _load_chunks_from_file(path: Path) -> Dict[str, list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("chunks"), dict):
            # Coerce all list values to list[str]
            out: Dict[str, list[str]] = {}
            for k, v in data["chunks"].items():
                if isinstance(v, list):
                    out[k] = [x if isinstance(x, str) else str(x) for x in v]
            return out
    except Exception:
        pass
    return {}


def _merge_chunks(dst: Dict[str, list[str]], src: Dict[str, list[str]]) -> None:
    for k, v in (src or {}).items():
        if not isinstance(v, list):
            continue
        if k in dst:
            # extend without duplicates
            for x in v:
                if x not in dst[k]:
                    dst[k].append(x)
        else:
            dst[k] = list(v)


def _write_songs_from_cfg(cfg: Dict[str, Any] | None) -> str | None:
    """Given a UI 'songs' config dict, write a songs JSON file and return its path.

    cfg shape (expected keys):
      - entranceText, offertoryText, communionText, meditationText, recessionalText: multiline strings (blank line separates chunks)
      - gloriaEnabled: boolean-like flag to include fixed Gloria text
      - kyrieLang, sanctusLang, agnusLang: 'es' or 'la'
      - mysteriumLang: 'es' or 'la'; mysteriumVersion: '1'|'2'|'3'
    Reads fixed parts from songs/parts/*.json
    """
    if not cfg or not isinstance(cfg, dict):
        return None

    chunks: Dict[str, list[str]] = {}

    # Free-text hymns (split into stanzas)
    ft_map = [
        ("{ENTRANCE_TXT}", cfg.get("entranceText")),
        ("{OFFERTORY_TXT}", cfg.get("offertoryText")),
        ("{COMMUNION_TXT}", cfg.get("communionText")),
        ("{MEDITATION_TXT}", cfg.get("meditationText")),
        ("{RECESSIONAL_TXT}", cfg.get("recessionalText")),
    ]
    for key, text in ft_map:
        parts = _split_chunks(text or "")
        if parts:
            chunks[key] = parts

    # Optional song references (simple placeholders)
    placeholders: Dict[str, str] = {}
    ref_map = [
        ("{ENTRANCE_REF}", cfg.get("entranceRef")),
        ("{OFFERTORY_REF}", cfg.get("offertoryRef")),
        ("{COMMUNION_REF}", cfg.get("communionRef")),
        ("{MEDITATION_REF}", cfg.get("meditationRef")),
        ("{RECESSIONAL_REF}", cfg.get("recessionalRef")),
    ]
    for key, ref in ref_map:
        if ref and str(ref).strip():
            placeholders[key] = str(ref).strip()

    # Fixed parts from songs/parts
    k_lang = (cfg.get("kyrieLang") or "").lower()[:2]
    g_lang = (cfg.get("gloriaLang") or "es").lower()[:2]
    s_lang = (cfg.get("sanctusLang") or "").lower()[:2]
    a_lang = (cfg.get("agnusLang") or "").lower()[:2]
    m_lang = (cfg.get("mysteriumLang") or "").lower()[:2]
    m_ver = str(cfg.get("mysteriumVersion") or "").strip() or '1'

    if k_lang in ("es", "la"):
        _merge_chunks(chunks, _load_chunks_from_file(_part_path("kyrie", k_lang)))
    if str(cfg.get("gloriaEnabled", "")).lower() in ("1", "true", "yes", "on") and g_lang in ("es",):
        _merge_chunks(chunks, _load_chunks_from_file(_part_path("gloria", g_lang)))
    if s_lang in ("es", "la"):
        _merge_chunks(chunks, _load_chunks_from_file(_part_path("sanctus", s_lang)))
    if a_lang in ("es", "la"):
        _merge_chunks(chunks, _load_chunks_from_file(_part_path("agnus", a_lang)))
    if m_lang in ("es", "la") and m_ver in ("1", "2", "3"):
        _merge_chunks(chunks, _load_chunks_from_file(_part_path("mysterium", m_lang, m_ver)))

    if not chunks and not placeholders:
        return None

    payload = {
        "meta": {"name": "UI songs", "language": cfg.get("language") or m_lang or "es"},
        "chunks": chunks,
        "placeholders": placeholders,
    }
    songs_dir = ROOT / "songs"
    songs_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = songs_dir / f"ui_{ts}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(out_path)


def _list_templates() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    for key, base_dir, label in TEMPLATE_DIR_SPECS:
        if not base_dir.exists() or not base_dir.is_dir():
            continue

        files = [p for p in base_dir.rglob("*.pptx") if p.is_file()]
        if key == "uploads":
            files.sort(key=lambda p: (p.stat().st_mtime, p.name.lower()), reverse=True)
        else:
            files.sort(key=lambda p: str(p.relative_to(base_dir)).lower())

        for path in files:
            stat = path.stat()
            rel_path = path.relative_to(ROOT).as_posix()
            rel_label = path.relative_to(base_dir).as_posix()
            entries.append(
                {
                    "id": rel_path,
                    "path": rel_path,
                    "name": path.stem,
                    "filename": path.name,
                    "group": key,
                    "group_label": label,
                    "label": rel_label,
                    "modified_ts": stat.st_mtime,
                }
            )

    return entries


def _extract_feed_date(entry: Any) -> date | None:
    link = str(getattr(entry, "link", "") or "")
    for pattern in (r"/(\d{6})\.cfm\b", r"\b(\d{6})\.cfm\b", r"\b(\d{6})\b"):
        match = re.search(pattern, link)
        if match:
            try:
                return datetime.strptime(match.group(1), "%m%d%y").date()
            except ValueError:
                return None
    return None


def _list_feed_dates() -> dict[str, Any]:
    parsed = fetch_mod.feedparser.parse(fetch_mod.FEED_URL)
    entries = getattr(parsed, "entries", []) or []
    options: list[dict[str, str]] = []
    seen: set[str] = set()

    for entry in entries:
        entry_date = _extract_feed_date(entry)
        if not entry_date:
            continue
        iso = entry_date.isoformat()
        if iso in seen:
            continue
        seen.add(iso)
        title = str(getattr(entry, "title", "") or "").strip()
        link = str(getattr(entry, "link", "") or "").strip()
        options.append(
            {
                "date": iso,
                "label": f"{iso} — {title}" if title else iso,
                "title": title,
                "link": link,
            }
        )

    options.sort(key=lambda item: item["date"], reverse=True)

    today_obj = date.today()
    selected = ""
    if options:
        if any(item["date"] == today_obj.isoformat() for item in options):
            selected = today_obj.isoformat()
        else:
            selected = min(
                options,
                key=lambda item: abs(date.fromisoformat(item["date"]) - today_obj),
            )["date"]

    return {
        "options": options,
        "selected": selected,
        "count": len(options),
    }


def _list_payloads() -> list[dict[str, Any]]:
    out_dir = ROOT / "out"
    if not out_dir.exists() or not out_dir.is_dir():
        return []

    entries: list[dict[str, Any]] = []
    for path in sorted(out_dir.rglob("*.json"), key=lambda p: (p.stat().st_mtime, p.name.lower()), reverse=True):
        if not path.is_file():
            continue
        rel_path = path.relative_to(ROOT).as_posix()
        stat = path.stat()
        entries.append(
            {
                "id": rel_path,
                "path": rel_path,
                "name": path.stem,
                "label": path.relative_to(out_dir).as_posix(),
                "modified_ts": stat.st_mtime,
            }
        )
    return entries


def _load_payload_file(payload_path: str) -> dict[str, Any]:
    allowed = {item["path"]: item for item in _list_payloads()}
    selected = allowed.get(payload_path)
    if not selected:
        raise ValueError("Payload not found in approved payload list")

    path = ROOT / payload_path
    if not path.exists() or not path.is_file():
        raise ValueError("Payload file does not exist")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Payload JSON must be an object")

    return {
        "payload": payload,
        "selected": selected,
    }


def _build_fetch_preview(payload: Dict[str, Any]) -> Dict[str, Any]:
    placeholders = payload.get("placeholders") or {}
    chunks = payload.get("chunks") or {}

    preview_sections = [
        ("first_reading", "{FIRST_READING_REF}", "{FIRST_READING_TXT}", "Primera lectura"),
        ("psalm", "{PSALM_REF}", "{PSALM_TXT}", "Salmo"),
        ("second_reading", "{SECOND_READING_REF}", "{SECOND_READING_TXT}", "Segunda lectura"),
        ("acclamation", "{ACCLAMATION_RES}", "{ACCLAMATION_VERSE}", "Aclamación"),
        ("gospel", "{GOSPEL_REF}", "{GOSPEL_TXT}", "Evangelio"),
    ]

    sections = []
    for key, ref_key, body_key, label in preview_sections:
        body_text = str(placeholders.get(body_key) or "").strip()
        chunk_list = chunks.get(body_key) if isinstance(chunks.get(body_key), list) else []
        sections.append(
            {
                "key": key,
                "label": label,
                "ref": str(placeholders.get(ref_key) or "").strip(),
                "has_body": bool(body_text),
                "chunk_count": len(chunk_list),
            }
        )

    return {
        "meta": payload.get("meta") or {},
        "sections": sections,
    }


def _get_acclamation_mode(data: Dict[str, Any] | Any) -> str:
    raw = ""
    if data is not None:
        raw = data.get("acclamation_mode") or data.get("acclamationMode") or ""
    return fetch_mod.normalize_acclamation_mode(raw or "ordinary")


def _known_placeholder_tokens() -> list[str]:
    return [item["placeholder"] for item in PLACEHOLDER_HELP]


def _inspect_template(template_path: str) -> Dict[str, Any]:
    allowed = {item["path"]: item for item in _list_templates()}
    selected = allowed.get(template_path)
    if not selected:
        raise ValueError("Template not found in approved template list")

    path = ROOT / template_path
    if not path.exists() or not path.is_file():
        raise ValueError("Template file does not exist")

    tokens = _known_placeholder_tokens()
    waterfall_tokens = {item["placeholder"] for item in PLACEHOLDER_HELP if item.get("waterfall")}
    slide_matches: dict[str, int] = {token: 0 for token in tokens}
    total_slides = 0

    with ZipFile(path, "r") as zf:
        slide_names = sorted(
            [name for name in zf.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")],
            key=lambda name: int(Path(name).stem.replace("slide", "")),
        )
        total_slides = len(slide_names)
        for slide_name in slide_names:
            content = zf.read(slide_name).decode("utf-8", errors="ignore")
            for token in tokens:
                if token in content:
                    slide_matches[token] += 1

    present = []
    missing = []
    for item in PLACEHOLDER_HELP:
        token = item["placeholder"]
        entry = {
            "placeholder": token,
            "description": item["description"],
            "category": item["category"],
            "waterfall": item["waterfall"],
            "slide_count": slide_matches[token],
        }
        if slide_matches[token] > 0:
            present.append(entry)
        else:
            missing.append(entry)

    waterfall_seeds = [
        {
            "placeholder": item["placeholder"],
            "slide_count": slide_matches[item["placeholder"]],
        }
        for item in PLACEHOLDER_HELP
        if item["placeholder"] in waterfall_tokens
    ]

    return {
        "template": selected,
        "slide_count": total_slides,
        "present": present,
        "missing": missing,
        "waterfall_seeds": waterfall_seeds,
    }


# Supported template placeholders (see AGENTS.md)
# These tokens can be placed in a custom PPTX template and will be
# replaced by render.py. Some text placeholders support waterfall
# expansion (slide duplication for chunked text).
PLACEHOLDER_HELP = [
    {
        "placeholder": "{LITURGICAL_DAY}",
        "description": "Título del día litúrgico (ej. Domingo III del Tiempo Ordinario)",
        "category": "meta",
        "waterfall": False,
    },
    {"placeholder": "{FIRST_READING_REF}", "description": "Referencia de la primera lectura", "category": "ref", "waterfall": False},
    {"placeholder": "{FIRST_READING_TXT}", "description": "Texto de la primera lectura (se expande en varias diapositivas si es largo)", "category": "text", "waterfall": True},
    {"placeholder": "{PSALM_REF}", "description": "Referencia del salmo responsorial", "category": "ref", "waterfall": False},
    {"placeholder": "{PSALM_TXT}", "description": "Texto del salmo (alternando R. y versos; puede generar múltiples diapositivas)", "category": "text", "waterfall": True},
    {"placeholder": "{SECOND_READING_REF}", "description": "Referencia de la segunda lectura", "category": "ref", "waterfall": False},
    {"placeholder": "{SECOND_READING_TXT}", "description": "Texto de la segunda lectura (con posible expansión en cascada)", "category": "text", "waterfall": True},
    {"placeholder": "{ACCLAMATION_RES}", "description": "Respuesta de la aclamación antes del Evangelio", "category": "text", "waterfall": False},
    {"placeholder": "{ACCLAMATION_VERSE}", "description": "Verso de la aclamación antes del Evangelio", "category": "text", "waterfall": False},
    {"placeholder": "{GOSPEL_REF}", "description": "Referencia del Evangelio", "category": "ref", "waterfall": False},
    {"placeholder": "{GOSPEL_TXT}", "description": "Texto del Evangelio (con expansión en cascada si es largo)", "category": "text", "waterfall": True},
    # Himnos (rellenados vía UI; cada trozo genera una diapositiva)
    {"placeholder": "{ENTRANCE_TXT}", "description": "Canto de entrada (estrofas: separa con línea en blanco)", "category": "hymn", "waterfall": True},
    {"placeholder": "{GLORIA_TXT}", "description": "Gloria fijo (se incluye u omite desde la UI)", "category": "hymn", "waterfall": True},
    {"placeholder": "{OFFERTORY_TXT}", "description": "Ofertorio (estrofas)", "category": "hymn", "waterfall": True},
    {"placeholder": "{COMMUNION_TXT}", "description": "Comunión (estrofas)", "category": "hymn", "waterfall": True},
    {"placeholder": "{MEDITATION_TXT}", "description": "Meditación (estrofas)", "category": "hymn", "waterfall": True},
    {"placeholder": "{RECESSIONAL_TXT}", "description": "Salida (estrofas)", "category": "hymn", "waterfall": True},
    {"placeholder": "{ENTRANCE_REF}", "description": "Referencia/identificador del canto de entrada (opcional)", "category": "hymn", "waterfall": False},
    {"placeholder": "{OFFERTORY_REF}", "description": "Referencia del ofertorio (opcional)", "category": "hymn", "waterfall": False},
    {"placeholder": "{COMMUNION_REF}", "description": "Referencia de comunión (opcional)", "category": "hymn", "waterfall": False},
    {"placeholder": "{MEDITATION_REF}", "description": "Referencia de la meditación (opcional)", "category": "hymn", "waterfall": False},
    {"placeholder": "{RECESSIONAL_REF}", "description": "Referencia de salida (opcional)", "category": "hymn", "waterfall": False},
    {"placeholder": "{KYRIE_TXT}", "description": "Kyrie (Español o Latín)", "category": "hymn", "waterfall": True},
    {"placeholder": "{SANCTUS_TXT}", "description": "Santo (Español o Latín)", "category": "hymn", "waterfall": True},
    {"placeholder": "{AGNUS_TXT}", "description": "Cordero de Dios (Español o Latín)", "category": "hymn", "waterfall": True},
    {"placeholder": "{MYSTERIUM_TXT}", "description": "Misterio de la Fe (Español/Latín; 3 opciones)", "category": "hymn", "waterfall": True},
]


@app.get("/placeholders")
def placeholders_help():
    """Return supported placeholder tokens and guidance for custom templates.

    Notes for template authors:
    - Coloque exactamente estos tokens (con llaves) en cuadros de texto.
    - Los placeholders de texto marcados como waterfall pueden generar varias diapositivas.
    - PowerPoint puede dividir texto en múltiples runs; el renderizador funciona mejor cuando cada token está en un solo run.
    - Los saltos de línea se normalizan a espacios y el espacio en blanco se colapsa.
    """
    return jsonify(
        {
            "ok": True,
            "placeholders": PLACEHOLDER_HELP,
            "notes": [
                "Inserte los tokens tal cual, p. ej. {FIRST_READING_TXT}.",
                "Para lecturas largas, se usa 'waterfall' duplicando la diapositiva semilla.",
                "El Salmo alterna R. y versos en diapositivas separadas.",
                "La aclamación antes del Evangelio usa placeholders separados para la respuesta y el verso.",
                "Los himnos y el Gloria se pueden configurar en la sección 'Cantos' de esta UI.",
            ],
        }
    )


@app.get("/templates")
def list_templates():
    templates = _list_templates()
    return jsonify({"ok": True, "templates": templates})


@app.get("/feed/dates")
def list_feed_dates():
    try:
        return jsonify({"ok": True, **_list_feed_dates()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/payloads")
def list_payloads():
    return jsonify({"ok": True, "payloads": _list_payloads()})


@app.get("/payloads/load")
def load_payload():
    payload_path = (request.args.get("path") or "").strip()
    if not payload_path:
        return jsonify({"ok": False, "error": "path is required"}), 400
    try:
        loaded = _load_payload_file(payload_path)
        payload = loaded["payload"]
        return jsonify(
            {
                "ok": True,
                "json_path": payload_path,
                "meta": payload.get("meta", {}),
                "preview": _build_fetch_preview(payload),
                "payload_file": loaded["selected"],
                "placeholders_count": len(payload.get("placeholders", {})),
                "chunks_keys": list((payload.get("chunks") or {}).keys()),
            }
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.get("/templates/inspect")
def inspect_template():
    template_path = (request.args.get("path") or "").strip()
    if not template_path:
        return jsonify({"ok": False, "error": "path is required"}), 400
    try:
        return jsonify({"ok": True, "inspection": _inspect_template(template_path)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


def _default_json_path(d: date) -> Path:
    return Path("out") / f"{d.isoformat()}.es-US.json"


def _default_build_path(d: date) -> Path:
    return Path("build") / f"{d.isoformat()}.es-US.pptx"


@app.route("/")
def index():
    return render_template("home.html")


@app.route("/docs")
def docs():
    return render_template("docs.html")


@app.route("/guided")
def guided():
    return render_template("guided.html")


@app.route("/advanced")
def advanced():
    return render_template("advanced.html")


@app.post("/fetch")
def do_fetch():
    try:
        req_data = request.json or request.form
        date_str = req_data.get("date") or ""
        acclamation_mode = _get_acclamation_mode(req_data)
        target_date = fetch_mod.parse_date_arg(date_str) if date_str else date.today()

        parsed = fetch_mod.feedparser.parse(fetch_mod.FEED_URL)
        entries = parsed.entries
        dt_key = fetch_mod.mmddyy(target_date)
        item = fetch_mod.pick_item(entries, dt_key)
        if item is None:
            return jsonify({"ok": False, "error": f"No RSS item found for {dt_key}"}), 404

        cleaned = fetch_mod.strip_footer(item.description)
        sections = fetch_mod.parse_sections(cleaned)

        placeholders = fetch_mod.to_placeholders(item.title, sections, acclamation_mode=acclamation_mode)
        chunks = fetch_mod.make_chunks(placeholders)

        payload = fetch_mod.build_payload(
            d=target_date,
            language="es-US",
            source="usccb_rss",
            link=item.link,
            title=item.title,
            placeholders=placeholders,
            chunks=chunks,
        )

        out_path = _default_json_path(target_date)
        fetch_mod.write_payload_json(payload, out_path)

        return jsonify(
            {
                "ok": True,
                "json_path": str(out_path),
                "meta": payload.get("meta", {}),
                "preview": _build_fetch_preview(payload),
                "acclamation_mode": acclamation_mode,
                "placeholders_count": len(payload.get("placeholders", {})),
                "chunks_keys": list((payload.get("chunks") or {}).keys()),
            }
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def _run_render(json_path: str, out_path: str | None, template: str | None, verbose: bool, stamp: bool, songs_path: str | None = None) -> Dict[str, Any]:
    args = [sys.executable, "render.py", "--json", json_path, "--out", out_path or json_path.replace("out/", "build/").replace(".json", ".pptx")]
    if template:
        args += ["--template", template]
    if verbose:
        args += ["--verbose"]
    if stamp:
        args += ["--stamp"]
    if songs_path:
        args += ["--songs", songs_path]
    proc = subprocess.run(args, capture_output=True, text=True)
    ok = proc.returncode == 0
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    # Try to discover the final path from stdout "Wrote: ..."
    final = None
    for line in stdout.splitlines()[::-1]:
        if line.startswith("Wrote:"):
            final = line.split(":", 1)[1].strip()
            break
    return {"ok": ok, "stdout": stdout, "stderr": stderr, "output_path": final}


@app.post("/render")
def do_render():
    try:
        data = request.json or request.form
        json_path = data.get("json_path")
        template = data.get("template")
        stamp = str(data.get("stamp", "true")).lower() in ("1", "true", "yes", "on")
        verbose = str(data.get("verbose", "false")).lower() in ("1", "true", "yes", "on")
        out_path = data.get("out_path")
        # Optional: songs config from UI
        songs_cfg = data.get("songs") if isinstance(data, dict) else None
        songs_path = _write_songs_from_cfg(songs_cfg) if isinstance(songs_cfg, dict) else None
        if not json_path:
            return jsonify({"ok": False, "error": "json_path is required"}), 400
        res = _run_render(json_path, out_path, template, verbose, stamp, songs_path)
        code = 200 if res["ok"] else 500
        return jsonify({**res, "songs_path": songs_path}), code
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/upload")
def upload_template():
    try:
        file = request.files.get("file") or request.files.get("template")
        if not file or not getattr(file, "filename", ""):
            return jsonify({"ok": False, "error": "No file uploaded"}), 400
        ext = Path(file.filename).suffix.lower()
        if ext != ".pptx":
            return jsonify({"ok": False, "error": "Only .pptx files are allowed"}), 400
        # Save under templates/uploads to keep paths simple for render.py
        uploads_dir = ROOT / "templates" / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        safe_name = secure_filename(Path(file.filename).name)
        # Make name unique
        from datetime import datetime
        import uuid
        unique = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        final_name = f"{unique}_{safe_name}" if safe_name else f"{unique}.pptx"
        dest = uploads_dir / final_name
        file.save(str(dest))
        # Return a server-side path suitable for --template input
        rel_path = f"templates/uploads/{final_name}"
        return jsonify({"ok": True, "template_path": rel_path, "templates": _list_templates()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/run")
def do_run():
    try:
        data = request.json or request.form
        date_str = data.get("date")
        template = data.get("template")
        acclamation_mode = _get_acclamation_mode(data)
        stamp = str(data.get("stamp", "true")).lower() in ("1", "true", "yes", "on")
        verbose = str(data.get("verbose", "true")).lower() in ("1", "true", "yes", "on")
        songs_cfg = data.get("songs") if isinstance(data, dict) else None
        songs_path = _write_songs_from_cfg(songs_cfg) if isinstance(songs_cfg, dict) else None

        # 1) Fetch
        f_resp = do_fetch()
        if isinstance(f_resp, tuple):
            f_json, status = f_resp
            if status != 200:
                return f_resp
            f_json = f_json.get_json()
        else:
            f_json = f_resp.get_json()
        if not f_json.get("ok"):
            return jsonify(f_json), 500

        json_path = f_json["json_path"]

        # 2) Render
        r_res = _run_render(json_path, None, template, verbose, stamp, songs_path)
        code = 200 if r_res["ok"] else 500
        return jsonify({"ok": r_res["ok"], "json_path": json_path, "output_path": r_res.get("output_path"), "stdout": r_res.get("stdout"), "stderr": r_res.get("stderr"), "songs_path": songs_path, "acclamation_mode": acclamation_mode}), code
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/build/<path:filename>")
def download_build(filename: str):
    build_dir = ROOT / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    # If query param download=1 is present, force attachment download
    as_attachment = str(request.args.get("download", "0")).lower() in ("1", "true", "yes", "on")
    return send_from_directory(str(build_dir), filename, as_attachment=as_attachment)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
