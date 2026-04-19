#!/usr/bin/env python3
"""CityPlot Web UI — Flask + Leaflet frontend for cityplot.py"""

import atexit
import os
import tempfile
import threading
import time
from pathlib import Path

from flask import Flask, render_template, request, send_file, jsonify

from cityplot import generate_svg, STYLES, PAPER_SIZES

app = Flask(__name__)

TEMP_MAX_AGE_SECONDS = 3600


def _cleanup_temp_files():
    """Remove cityplot temp files older than TEMP_MAX_AGE_SECONDS."""
    tmpdir = tempfile.gettempdir()
    cutoff = time.time() - TEMP_MAX_AGE_SECONDS
    for entry in Path(tmpdir).glob("cityplot_*.svg"):
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            pass


def _start_cleanup_timer():
    _cleanup_temp_files()
    timer = threading.Timer(600, _start_cleanup_timer)
    timer.daemon = True
    timer.start()


_start_cleanup_timer()


@app.route("/")
def index():
    styles = list(STYLES.keys())
    papers = list(PAPER_SIZES.keys())
    paper_dims = {k: {"w": v[0], "h": v[1]} for k, v in PAPER_SIZES.items()}
    return render_template("index.html", styles=styles, papers=papers, paper_dims=paper_dims)


@app.route("/generate", methods=["POST"])
def generate():
    data = request.json
    if not data:
        return jsonify({"ok": False, "error": "Request body must be JSON"}), 400

    try:
        lat = float(data["lat"])
        lon = float(data["lon"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"ok": False, "error": "lat and lon are required numeric fields"}), 400

    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return jsonify({"ok": False, "error": "lat must be -90..90, lon must be -180..180"}), 400

    try:
        radius = int(data.get("radius", 1000))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "radius must be an integer"}), 400

    style = data.get("style", "default")
    if style not in STYLES:
        return jsonify({"ok": False, "error": f"Unknown style. Available: {', '.join(STYLES)}"}), 400

    paper = data.get("paper", "a3l")
    if paper not in PAPER_SIZES:
        return jsonify({"ok": False, "error": f"Unknown paper. Available: {', '.join(PAPER_SIZES)}"}), 400

    circle = data.get("circle", False)

    # Parse margins
    try:
        m_top = float(data.get("margin_top", 15))
        m_right = float(data.get("margin_right", 15))
        m_bottom = float(data.get("margin_bottom", 15))
        m_left = float(data.get("margin_left", 15))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Margins must be numeric"}), 400
    margins = (m_top, m_right, m_bottom, m_left)

    # Generate in temp file
    fd, outpath = tempfile.mkstemp(suffix=".svg", prefix="cityplot_")
    os.close(fd)

    # Parse layers
    layer_filter = data.get("layers", None)

    try:
        generate_svg(
            place=f"{lat},{lon}",
            radius=radius,
            style_name=style,
            paper=paper,
            margins=margins,
            output=outpath,
            layer_filter=layer_filter,
            clip_circle=circle,
        )
        return jsonify({"ok": True, "file": outpath, "size_kb": round(Path(outpath).stat().st_size / 1024)})
    except Exception as e:
        if os.path.exists(outpath):
            os.unlink(outpath)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/download")
def download():
    filepath = request.args.get("file")
    if not filepath:
        return "Invalid path", 400
    resolved = Path(filepath).resolve()
    tmpdir = Path(tempfile.gettempdir()).resolve()
    if not str(resolved).startswith(str(tmpdir) + os.sep) or not resolved.name.startswith("cityplot_"):
        return "Invalid path", 400
    if not resolved.exists():
        return "File not found", 404
    return send_file(str(resolved), mimetype="image/svg+xml", as_attachment=True,
                     download_name="cityplot.svg")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5555, debug=False)
