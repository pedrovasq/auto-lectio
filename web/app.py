from __future__ import annotations

import os
import sys
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, Dict

from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

# Ensure project root is importable when running as `python web/app.py`
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import fetch helpers directly so we don't have to shell out for fetch
import fetch as fetch_mod


app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 65 * 1024 * 1024  # 65 MB upload limit


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
    {"placeholder": "{ACCLAMATION_REF}", "description": "Referencia breve de la aclamación antes del Evangelio", "category": "ref", "waterfall": False},
    {"placeholder": "{ACCLAMATION_TXT}", "description": "Verso de la aclamación (sin 'R.'/Aleluya)", "category": "text", "waterfall": False},
    {"placeholder": "{GOSPEL_REF}", "description": "Referencia del Evangelio", "category": "ref", "waterfall": False},
    {"placeholder": "{GOSPEL_TXT}", "description": "Texto del Evangelio (con expansión en cascada si es largo)", "category": "text", "waterfall": True},
    # Reservados para uso futuro (no se rellenan en esta fase)
    {"placeholder": "{ENTRANCE_HYMN}", "description": "Himno de entrada (no utilizado por ahora)", "category": "hymn", "waterfall": False},
    {"placeholder": "{OFFERTORY_HYMN}", "description": "Ofertorio (no utilizado por ahora)", "category": "hymn", "waterfall": False},
    {"placeholder": "{MYSTERY_OF_FAITH}", "description": "Misterio de la Fe (no utilizado por ahora)", "category": "misc", "waterfall": False},
    {"placeholder": "{COMMUNION_HYMN}", "description": "Comunión (no utilizado por ahora)", "category": "hymn", "waterfall": False},
    {"placeholder": "{RECESSIONAL_HYMN}", "description": "Salida (no utilizado por ahora)", "category": "hymn", "waterfall": False},
]


@app.get("/placeholders")
def placeholders_help():
    """Return supported placeholder tokens and guidance for custom templates.

    Notes for template authors:
    - Coloque exactamente estos tokens (con llaves) en cuadros de texto.
    - Los placeholders de texto marcados como waterfall pueden generar varias diapositivas.
    - PowerPoint puede dividir texto en múltiples runs; el renderizador reemplaza a nivel de párrafo.
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
                "Los himnos indicados no se rellenan todavía.",
            ],
        }
    )


def _default_json_path(d: date) -> Path:
    return Path("out") / f"{d.isoformat()}.es-US.json"


def _default_build_path(d: date) -> Path:
    return Path("build") / f"{d.isoformat()}.es-US.pptx"


@app.route("/")
def index():
    return render_template("index.html")


@app.post("/fetch")
def do_fetch():
    try:
        date_str = (request.json or {}).get("date") or request.form.get("date") or ""
        target_date = fetch_mod.parse_date_arg(date_str) if date_str else date.today()

        parsed = fetch_mod.feedparser.parse(fetch_mod.FEED_URL)
        entries = parsed.entries
        dt_key = fetch_mod.mmddyy(target_date)
        item = fetch_mod.pick_item(entries, dt_key)
        if item is None:
            return jsonify({"ok": False, "error": f"No RSS item found for {dt_key}"}), 404

        cleaned = fetch_mod.strip_footer(item.description)
        sections = fetch_mod.parse_sections(cleaned)

        placeholders = fetch_mod.to_placeholders(item.title, sections)
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
                "placeholders_count": len(payload.get("placeholders", {})),
                "chunks_keys": list((payload.get("chunks") or {}).keys()),
            }
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def _run_render(json_path: str, out_path: str | None, template: str | None, verbose: bool, stamp: bool) -> Dict[str, Any]:
    args = [sys.executable, "render.py", "--json", json_path, "--out", out_path or json_path.replace("out/", "build/").replace(".json", ".pptx")]
    if template:
        args += ["--template", template]
    if verbose:
        args += ["--verbose"]
    if stamp:
        args += ["--stamp"]
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
        if not json_path:
            return jsonify({"ok": False, "error": "json_path is required"}), 400
        res = _run_render(json_path, out_path, template, verbose, stamp)
        code = 200 if res["ok"] else 500
        return jsonify(res), code
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
        return jsonify({"ok": True, "template_path": rel_path})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/run")
def do_run():
    try:
        data = request.json or request.form
        date_str = data.get("date")
        template = data.get("template")
        stamp = str(data.get("stamp", "true")).lower() in ("1", "true", "yes", "on")
        verbose = str(data.get("verbose", "true")).lower() in ("1", "true", "yes", "on")

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
        r_res = _run_render(json_path, None, template, verbose, stamp)
        code = 200 if r_res["ok"] else 500
        return jsonify({"ok": r_res["ok"], "json_path": json_path, "output_path": r_res.get("output_path"), "stdout": r_res.get("stdout"), "stderr": r_res.get("stderr")}), code
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
