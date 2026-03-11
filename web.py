#!/usr/bin/env python3
"""CityPlot Web UI — Flask + Leaflet frontend for cityplot.py"""

import os
import tempfile
import threading
from pathlib import Path

from flask import Flask, render_template, request, send_file, jsonify

from cityplot import generate_svg, STYLES, PAPER_SIZES

app = Flask(__name__)

# Store generation status
jobs = {}


@app.route("/")
def index():
    styles = list(STYLES.keys())
    papers = list(PAPER_SIZES.keys())
    paper_dims = {k: {"w": v[0], "h": v[1]} for k, v in PAPER_SIZES.items()}
    return render_template("index.html", styles=styles, papers=papers, paper_dims=paper_dims)


@app.route("/generate", methods=["POST"])
def generate():
    data = request.json

    lat = float(data["lat"])
    lon = float(data["lon"])
    radius = int(data.get("radius", 1000))
    style = data.get("style", "default")
    paper = data.get("paper", "a3l")
    circle = data.get("circle", False)

    # Parse margins
    m_top = float(data.get("margin_top", 15))
    m_right = float(data.get("margin_right", 15))
    m_bottom = float(data.get("margin_bottom", 15))
    m_left = float(data.get("margin_left", 15))
    margins = (m_top, m_right, m_bottom, m_left)

    # Generate in temp file
    fd, outpath = tempfile.mkstemp(suffix=".svg", prefix="cityplot_")
    os.close(fd)

    try:
        generate_svg(
            place=f"{lat},{lon}",
            radius=radius,
            style_name=style,
            paper=paper,
            margins=margins,
            output=outpath,
            clip_circle=circle,
        )
        return jsonify({"ok": True, "file": outpath, "size_kb": round(Path(outpath).stat().st_size / 1024)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/download")
def download():
    filepath = request.args.get("file")
    if not filepath or not filepath.startswith(tempfile.gettempdir()):
        return "Invalid path", 400
    if not Path(filepath).exists():
        return "File not found", 404
    return send_file(filepath, mimetype="image/svg+xml", as_attachment=True,
                     download_name="cityplot.svg")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5555, debug=False)
