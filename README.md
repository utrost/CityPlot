# CityPlot

Generate plotter-ready SVGs from OpenStreetMap data. No rasterization, no pixel-to-vector conversion — pure vector from source to output.

## How It Works

OpenStreetMap stores geographic data as nodes (points) and ways (polylines). CityPlot fetches this data via the Overpass API, projects it to metric coordinates (UTM), and writes SVG paths directly. Every street, building outline, waterway, and park boundary becomes a native vector path.

The output is layered: each feature type (streets, buildings, water, parks, railways) lives in its own SVG group. This enables multi-color plotting — pause the plotter, swap the pen, resume on the next layer.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
# City center, 2km radius, default style
python cityplot.py "Bremen, Germany" --radius 2000 --output bremen.svg

# Bounding box (west,south,east,north)
python cityplot.py --bbox 8.78,53.06,8.84,53.09 --output bremen-center.svg

# Minimal style (streets + water only)
python cityplot.py "London, UK" --radius 3000 --style minimal --output london.svg

# Circular clip mask (prettymaps-style)
python cityplot.py "Paris, France" --radius 1500 --style mono --circle --output paris.svg

# A4 landscape
python cityplot.py "Münster, Germany" --paper a4l --output muenster.svg
```

## Styles

| Style | Layers |
|---|---|
| `default` | Streets (3 levels), water, buildings, parks, railways — colored |
| `minimal` | Streets + water only |
| `buildings` | Building footprints + major streets + water |
| `mono` | All layers in black (single-pen plotting) |

```bash
python cityplot.py --list-styles
```

## Paper Sizes

`a4`, `a4l` (landscape), `a3`, `a3l`, `letter`

SVG units are millimeters — output is 1:1 for plotter software.

## Options

| Flag | Default | Description |
|---|---|---|
| `--radius` | 2000 | Radius in meters from city center |
| `--style` | default | Visual style preset |
| `--paper` | a3l | Paper size |
| `--margin` | 15 | Margin in mm |
| `--circle` | off | Apply circular clip mask |
| `-o` / `--output` | output.svg | Output file |

## Architecture

```
Overpass API → GeoJSON → osmnx/geopandas → UTM projection → SVG paths
```

No raster step. No intermediate PNG. Geographic coordinates are projected to metric space, then mapped directly to SVG canvas coordinates with correct aspect ratio and margins.

## License

Copyright © 2026 Uwe Trostheide

Licensed under the [GNU Affero General Public License v3.0](LICENSE).
