#!/usr/bin/env python3
"""
CityPlot — Generate plotter-ready SVGs from OpenStreetMap data.

Usage:
    python cityplot.py "Bremen, Germany" --radius 2000 --output bremen.svg
    python cityplot.py --bbox 8.78,53.06,8.84,53.09 --output bremen-center.svg
    python cityplot.py "London, UK" --radius 3000 --style minimal
"""

import argparse
import sys
from pathlib import Path

import osmnx as ox
import geopandas as gpd
import svgwrite
from shapely.geometry import MultiLineString, LineString, Polygon, MultiPolygon


# ── Style Presets ────────────────────────────────────────────────────────────

STYLES = {
    "default": {
        "layers": {
            "streets_primary":   {"tags": {"highway": ["motorway", "trunk", "primary"]}, "stroke": "#000000", "width": 1.2},
            "streets_secondary": {"tags": {"highway": ["secondary", "tertiary"]}, "stroke": "#000000", "width": 0.7},
            "streets_minor":     {"tags": {"highway": ["residential", "living_street", "unclassified", "pedestrian"]}, "stroke": "#000000", "width": 0.3},
            "water":             {"tags": {"natural": "water", "waterway": True}, "stroke": "#3366aa", "width": 0.5},
            "buildings":         {"tags": {"building": True}, "stroke": "#666666", "width": 0.15},
            "parks":             {"tags": {"leisure": "park", "landuse": ["forest", "grass"]}, "stroke": "#228833", "width": 0.3},
            "railway":           {"tags": {"railway": "rail"}, "stroke": "#444444", "width": 0.4, "dasharray": "4,2"},
        },
    },
    "minimal": {
        "layers": {
            "streets_primary":   {"tags": {"highway": ["motorway", "trunk", "primary"]}, "stroke": "#000000", "width": 1.0},
            "streets_secondary": {"tags": {"highway": ["secondary", "tertiary"]}, "stroke": "#000000", "width": 0.5},
            "streets_minor":     {"tags": {"highway": ["residential", "living_street", "unclassified"]}, "stroke": "#000000", "width": 0.2},
            "water":             {"tags": {"natural": "water", "waterway": True}, "stroke": "#000000", "width": 0.4},
        },
    },
    "buildings": {
        "layers": {
            "buildings":         {"tags": {"building": True}, "stroke": "#000000", "width": 0.15},
            "streets_primary":   {"tags": {"highway": ["motorway", "trunk", "primary", "secondary"]}, "stroke": "#000000", "width": 0.5},
            "water":             {"tags": {"natural": "water", "waterway": True}, "stroke": "#000000", "width": 0.3},
        },
    },
    "mono": {
        "layers": {
            "streets_primary":   {"tags": {"highway": ["motorway", "trunk", "primary"]}, "stroke": "#000000", "width": 1.2},
            "streets_secondary": {"tags": {"highway": ["secondary", "tertiary"]}, "stroke": "#000000", "width": 0.7},
            "streets_minor":     {"tags": {"highway": ["residential", "living_street", "unclassified", "pedestrian"]}, "stroke": "#000000", "width": 0.3},
            "water":             {"tags": {"natural": "water", "waterway": True}, "stroke": "#000000", "width": 0.5},
            "buildings":         {"tags": {"building": True}, "stroke": "#000000", "width": 0.15},
            "parks":             {"tags": {"leisure": "park", "landuse": ["forest", "grass"]}, "stroke": "#000000", "width": 0.3},
            "railway":           {"tags": {"railway": "rail"}, "stroke": "#000000", "width": 0.4, "dasharray": "4,2"},
        },
    },
}


# ── Paper Sizes (mm) ────────────────────────────────────────────────────────

PAPER_SIZES = {
    "a4":     (210, 297),
    "a4l":    (297, 210),
    "a3":     (297, 420),
    "a3l":    (420, 297),
    "letter": (216, 279),
}


# ── Geometry Helpers ─────────────────────────────────────────────────────────

def geometry_to_lines(geom):
    """Extract line coordinates from any geometry type."""
    if geom is None:
        return []
    if isinstance(geom, (LineString, )):
        return [list(geom.coords)]
    if isinstance(geom, MultiLineString):
        return [list(line.coords) for line in geom.geoms]
    if isinstance(geom, Polygon):
        lines = [list(geom.exterior.coords)]
        for interior in geom.interiors:
            lines.append(list(interior.coords))
        return lines
    if isinstance(geom, MultiPolygon):
        lines = []
        for poly in geom.geoms:
            lines.extend(geometry_to_lines(poly))
        return lines
    # GeometryCollection etc.
    if hasattr(geom, 'geoms'):
        lines = []
        for g in geom.geoms:
            lines.extend(geometry_to_lines(g))
        return lines
    return []


def transform_coords(lines, bounds, canvas_w, canvas_h, margin):
    """Transform geographic coordinates to SVG canvas coordinates."""
    minx, miny, maxx, maxy = bounds
    geo_w = maxx - minx
    geo_h = maxy - miny

    if geo_w == 0 or geo_h == 0:
        return []

    draw_w = canvas_w - 2 * margin
    draw_h = canvas_h - 2 * margin

    # Maintain aspect ratio
    scale_x = draw_w / geo_w
    scale_y = draw_h / geo_h
    scale = min(scale_x, scale_y)

    # Center on canvas
    offset_x = margin + (draw_w - geo_w * scale) / 2
    offset_y = margin + (draw_h - geo_h * scale) / 2

    transformed = []
    for line in lines:
        coords = []
        for x, y in line:
            sx = offset_x + (x - minx) * scale
            sy = offset_y + (maxy - y) * scale  # flip Y axis
            coords.append((round(sx, 2), round(sy, 2)))
        transformed.append(coords)
    return transformed


# ── Data Fetching ────────────────────────────────────────────────────────────

def fetch_features(place=None, bbox=None, radius=None, tags=None):
    """Fetch OSM features as GeoDataFrame, projected to UTM."""
    try:
        if bbox:
            west, south, east, north = bbox
            gdf = ox.features_from_bbox(bbox=(north, south, east, west), tags=tags)
        elif place and radius:
            gdf = ox.features_from_point(
                ox.geocode(place), dist=radius, tags=tags
            )
        elif place:
            gdf = ox.features_from_place(place, tags=tags)
        else:
            return gpd.GeoDataFrame()

        if gdf.empty:
            return gdf

        # Project to UTM for metric coordinates
        gdf = ox.projection.project_gdf(gdf)
        return gdf

    except Exception as e:
        print(f"  Warning: Could not fetch {tags}: {e}", file=sys.stderr)
        return gpd.GeoDataFrame()


# ── SVG Generation ───────────────────────────────────────────────────────────

def generate_svg(place=None, bbox=None, radius=None, style_name="default",
                 paper="a3l", margin_mm=15, output="output.svg", clip_circle=False):
    """Main pipeline: fetch data → project → write SVG."""

    style = STYLES.get(style_name, STYLES["default"])
    paper_w, paper_h = PAPER_SIZES.get(paper, PAPER_SIZES["a3l"])

    # Use mm as SVG units (1:1 for plotter)
    canvas_w = paper_w
    canvas_h = paper_h

    print(f"CityPlot: {place or bbox}")
    print(f"  Style: {style_name}, Paper: {paper} ({paper_w}×{paper_h}mm)")

    # ── Fetch all layers ──
    all_lines = {}
    all_bounds = []

    for layer_name, layer_cfg in style["layers"].items():
        print(f"  Fetching {layer_name}...")
        gdf = fetch_features(place=place, bbox=bbox, radius=radius, tags=layer_cfg["tags"])

        if gdf.empty:
            print(f"    → empty")
            continue

        lines = []
        for geom in gdf.geometry:
            lines.extend(geometry_to_lines(geom))

        if lines:
            all_lines[layer_name] = (lines, layer_cfg)
            # Collect bounds from all coordinates
            for line in lines:
                for x, y in line:
                    all_bounds.append((x, y))

        print(f"    → {len(lines)} paths")

    if not all_bounds:
        print("Error: No data found.", file=sys.stderr)
        sys.exit(1)

    # ── Calculate global bounds ──
    xs = [p[0] for p in all_bounds]
    ys = [p[1] for p in all_bounds]
    bounds = (min(xs), min(ys), max(xs), max(ys))

    # ── Create SVG ──
    dwg = svgwrite.Drawing(
        output,
        size=(f"{canvas_w}mm", f"{canvas_h}mm"),
        viewBox=f"0 0 {canvas_w} {canvas_h}",
    )

    # Background (optional, comment out for transparent)
    # dwg.add(dwg.rect(insert=(0, 0), size=(canvas_w, canvas_h), fill="white"))

    # ── Render layers ──
    for layer_name, (lines, cfg) in all_lines.items():
        group = dwg.g(id=layer_name)

        transformed = transform_coords(lines, bounds, canvas_w, canvas_h, margin_mm)

        for coords in transformed:
            if len(coords) < 2:
                continue

            path_data = f"M {coords[0][0]},{coords[0][1]}"
            for x, y in coords[1:]:
                path_data += f" L {x},{y}"

            extra = {}
            if "dasharray" in cfg:
                extra["stroke_dasharray"] = cfg["dasharray"]

            group.add(dwg.path(
                d=path_data,
                stroke=cfg["stroke"],
                stroke_width=cfg["width"],
                fill="none",
                stroke_linecap="round",
                stroke_linejoin="round",
                **extra,
            ))

        dwg.add(group)

    # ── Optional circular clip ──
    if clip_circle:
        cx, cy = canvas_w / 2, canvas_h / 2
        r = min(canvas_w, canvas_h) / 2 - margin_mm
        clip = dwg.defs.add(dwg.clipPath(id="circle-clip"))
        clip.add(dwg.circle(center=(cx, cy), r=r))
        # Wrap all content in clipped group
        wrapper = dwg.g(clip_path="url(#circle-clip)")
        for element in list(dwg.elements):
            if element != dwg.defs:
                dwg.elements.remove(element)
                wrapper.add(element)
        dwg.add(wrapper)

    dwg.save()

    file_size = Path(output).stat().st_size / 1024
    print(f"  → {output} ({file_size:.0f} KB)")
    print(f"  Layers: {', '.join(all_lines.keys())}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CityPlot — Generate plotter-ready SVGs from OpenStreetMap data."
    )
    parser.add_argument("place", nargs="?", help='Place name, e.g. "Bremen, Germany"')
    parser.add_argument("--bbox", help="Bounding box: west,south,east,north")
    parser.add_argument("--radius", type=int, default=2000, help="Radius in meters (default: 2000)")
    parser.add_argument("--style", choices=STYLES.keys(), default="default", help="Visual style preset")
    parser.add_argument("--paper", choices=PAPER_SIZES.keys(), default="a3l", help="Paper size (default: a3l)")
    parser.add_argument("--margin", type=int, default=15, help="Margin in mm (default: 15)")
    parser.add_argument("--output", "-o", default="output.svg", help="Output SVG file")
    parser.add_argument("--circle", action="store_true", help="Apply circular clip mask")
    parser.add_argument("--list-styles", action="store_true", help="List available styles")

    args = parser.parse_args()

    if args.list_styles:
        for name, style in STYLES.items():
            layers = ", ".join(style["layers"].keys())
            print(f"  {name}: {layers}")
        sys.exit(0)

    if not args.place and not args.bbox:
        parser.error("Provide a place name or --bbox")

    bbox = None
    if args.bbox:
        bbox = [float(x) for x in args.bbox.split(",")]
        if len(bbox) != 4:
            parser.error("--bbox requires exactly 4 values: west,south,east,north")

    generate_svg(
        place=args.place,
        bbox=bbox,
        radius=args.radius,
        style_name=args.style,
        paper=args.paper,
        margin_mm=args.margin,
        output=args.output,
        clip_circle=args.circle,
    )


if __name__ == "__main__":
    main()
