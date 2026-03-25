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
from shapely.geometry import MultiLineString, LineString, Polygon, MultiPolygon, Point

# Configure osmnx timeout (Overpass API can be slow for large queries)
ox.settings.timeout = 180

# Inkscape namespace for layer support
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"

# Human-readable layer labels
LAYER_LABELS = {
    "streets_primary":   "Primary Streets",
    "streets_secondary": "Secondary Streets",
    "streets_minor":     "Minor Streets",
    "water":             "Water",
    "buildings":         "Buildings",
    "parks":             "Parks",
    "railway":           "Railway",
}


# ── Style Presets ────────────────────────────────────────────────────────────

STYLES = {
    # Stroke widths calibrated from Axidraw plotter test (2026-03-19):
    # Buildings 0.1mm, minor streets 0.2mm, secondary 0.4mm,
    # primary+railway 0.8mm, water 1.0mm, parks 0.6mm
    "default": {
        "layers": {
            "streets_primary":   {"tags": {"highway": ["motorway", "trunk", "primary"]}, "stroke": "#000000", "width": 0.8},
            "streets_secondary": {"tags": {"highway": ["secondary", "tertiary"]}, "stroke": "#000000", "width": 0.4},
            "streets_minor":     {"tags": {"highway": ["residential", "living_street", "unclassified", "pedestrian"]}, "stroke": "#000000", "width": 0.2},
            "water":             {"tags": {"natural": "water", "waterway": ["river", "canal", "stream"]}, "stroke": "#3366aa", "width": 1.0, "fill": "#cce0f0"},
            "buildings":         {"tags": {"building": True}, "stroke": "#666666", "width": 0.1},
            "parks":             {"tags": {"leisure": "park"}, "stroke": "#228833", "width": 0.6, "fill": "#d4edda"},
            "railway":           {"tags": {"railway": "rail"}, "stroke": "#444444", "width": 0.8, "dasharray": "4,2"},
        },
    },
    "minimal": {
        "layers": {
            "streets_primary":   {"tags": {"highway": ["motorway", "trunk", "primary"]}, "stroke": "#000000", "width": 0.8},
            "streets_secondary": {"tags": {"highway": ["secondary", "tertiary"]}, "stroke": "#000000", "width": 0.4},
            "streets_minor":     {"tags": {"highway": ["residential", "living_street", "unclassified"]}, "stroke": "#000000", "width": 0.2},
            "water":             {"tags": {"natural": "water", "waterway": ["river", "canal", "stream"]}, "stroke": "#000000", "width": 1.0, "fill": "#e0e0e0"},
        },
    },
    "buildings": {
        "layers": {
            "buildings":         {"tags": {"building": True}, "stroke": "#000000", "width": 0.1},
            "streets_primary":   {"tags": {"highway": ["motorway", "trunk", "primary", "secondary"]}, "stroke": "#000000", "width": 0.8},
            "water":             {"tags": {"natural": "water", "waterway": ["river", "canal", "stream"]}, "stroke": "#000000", "width": 1.0, "fill": "#e0e0e0"},
        },
    },
    "mono": {
        "layers": {
            "streets_primary":   {"tags": {"highway": ["motorway", "trunk", "primary"]}, "stroke": "#000000", "width": 0.8},
            "streets_secondary": {"tags": {"highway": ["secondary", "tertiary"]}, "stroke": "#000000", "width": 0.4},
            "streets_minor":     {"tags": {"highway": ["residential", "living_street", "unclassified", "pedestrian"]}, "stroke": "#000000", "width": 0.2},
            "water":             {"tags": {"natural": "water", "waterway": ["river", "canal", "stream"]}, "stroke": "#000000", "width": 1.0, "fill": "#e0e0e0"},
            "buildings":         {"tags": {"building": True}, "stroke": "#000000", "width": 0.1},
            "parks":             {"tags": {"leisure": "park"}, "stroke": "#000000", "width": 0.6, "fill": "#e0e0e0"},
            "railway":           {"tags": {"railway": "rail"}, "stroke": "#000000", "width": 0.8, "dasharray": "4,2"},
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


def transform_coords(lines, bounds, canvas_w, canvas_h, margins):
    """Transform geographic coordinates to SVG canvas coordinates.
    
    margins: (top, right, bottom, left) in mm
    """
    margin_top, margin_right, margin_bottom, margin_left = margins
    minx, miny, maxx, maxy = bounds
    geo_w = maxx - minx
    geo_h = maxy - miny

    if geo_w == 0 or geo_h == 0:
        return []

    draw_w = canvas_w - margin_left - margin_right
    draw_h = canvas_h - margin_top - margin_bottom

    # Maintain aspect ratio
    scale_x = draw_w / geo_w
    scale_y = draw_h / geo_h
    scale = min(scale_x, scale_y)

    # Center within draw area
    offset_x = margin_left + (draw_w - geo_w * scale) / 2
    offset_y = margin_top + (draw_h - geo_h * scale) / 2

    transformed = []
    for line in lines:
        coords = []
        for x, y in line:
            sx = offset_x + (x - minx) * scale
            sy = offset_y + (maxy - y) * scale  # flip Y axis
            coords.append((round(sx, 2), round(sy, 2)))
        transformed.append(coords)
    return transformed


def optimize_path_order(paths):
    """Reorder paths using nearest-neighbor heuristic to minimize pen travel.
    
    Uses a KD-tree for O(n log n) lookups. For each path, considers both
    normal and reversed direction, picking whichever start/end point is
    closest to the current pen position.
    """
    if len(paths) <= 1:
        return paths

    valid = [p for p in paths if len(p) >= 2]
    if not valid:
        return paths

    try:
        from scipy.spatial import KDTree
        return _optimize_kdtree(valid)
    except ImportError:
        return _optimize_naive(valid)


def _optimize_kdtree(valid):
    """Fast path optimization using scipy KD-tree."""
    from scipy.spatial import KDTree
    import numpy as np

    n = len(valid)
    # Build points array: [start0, end0, start1, end1, ...]
    # Index i*2 = start of path i, i*2+1 = end of path i
    points = np.empty((n * 2, 2))
    for i, p in enumerate(valid):
        points[i * 2] = p[0]
        points[i * 2 + 1] = p[-1]

    tree = KDTree(points)
    used = set()
    ordered = []

    # Start with path 0
    used.add(0)
    ordered.append(valid[0])
    pen = np.array(valid[0][-1])

    for _ in range(n - 1):
        # Query increasing number of neighbors until we find an unused path
        k = min(10, n * 2)
        while True:
            dists, idxs = tree.query(pen, k=k)
            if isinstance(dists, float):
                dists, idxs = [dists], [idxs]
            found = False
            for dist, idx in zip(dists, idxs):
                path_idx = idx // 2
                if path_idx not in used:
                    is_end = (idx % 2 == 1)  # matched the end point → reverse
                    path = valid[path_idx]
                    if is_end:
                        path = list(reversed(path))
                    ordered.append(path)
                    pen = np.array(path[-1])
                    used.add(path_idx)
                    found = True
                    break
            if found:
                break
            k = min(k * 2, n * 2)

    return ordered


def _optimize_naive(valid):
    """Fallback O(n²) nearest-neighbor without scipy."""
    remaining = set(range(len(valid)))
    ordered = []

    current_idx = 0
    remaining.remove(current_idx)
    ordered.append(valid[current_idx])
    pen = valid[current_idx][-1]

    while remaining:
        best_dist = float('inf')
        best_idx = next(iter(remaining))
        best_reverse = False

        for idx in remaining:
            p = valid[idx]
            d_start = (pen[0] - p[0][0]) ** 2 + (pen[1] - p[0][1]) ** 2
            d_end = (pen[0] - p[-1][0]) ** 2 + (pen[1] - p[-1][1]) ** 2

            if d_start < best_dist:
                best_dist = d_start
                best_idx = idx
                best_reverse = False
            if d_end < best_dist:
                best_dist = d_end
                best_idx = idx
                best_reverse = True

        path = valid[best_idx]
        if best_reverse:
            path = list(reversed(path))
        ordered.append(path)
        pen = path[-1]
        remaining.remove(best_idx)

    return ordered


# ── Data Fetching ────────────────────────────────────────────────────────────

def parse_center(place):
    """Parse place as GPS coordinates (lat,lon) or geocode a name."""
    if place and "," in place:
        parts = place.split(",")
        if len(parts) == 2:
            try:
                lat, lon = float(parts[0].strip()), float(parts[1].strip())
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    return (lat, lon)
            except ValueError:
                pass
    return None


def fetch_features(place=None, center=None, bbox=None, radius=None, tags=None,
                   clip_center_utm=None, clip_radius=None, clip_circle=False,
                   paper_aspect=1.0):
    """Fetch OSM features as GeoDataFrame, projected to UTM and clipped."""
    try:
        if bbox:
            west, south, east, north = bbox
            gdf = ox.features_from_bbox(bbox=(north, south, east, west), tags=tags)
        elif center and radius:
            gdf = ox.features_from_point(center, dist=radius, tags=tags)
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

        # Clip geometries to region (prevents rivers/railways from extending bounds)
        if clip_center_utm is not None and clip_radius is not None:
            cx, cy = clip_center_utm
            if clip_circle:
                clip_shape = Point(clip_center_utm).buffer(clip_radius)
            else:
                # Rectangular clip matching paper aspect ratio
                # Radius defines the shorter half-dimension
                if paper_aspect >= 1:
                    # Landscape: radius = half-height, width stretches
                    half_h = clip_radius
                    half_w = clip_radius * paper_aspect
                else:
                    # Portrait: radius = half-width, height stretches
                    half_w = clip_radius
                    half_h = clip_radius / paper_aspect
                clip_shape = Polygon([
                    (cx - half_w, cy - half_h),
                    (cx + half_w, cy - half_h),
                    (cx + half_w, cy + half_h),
                    (cx - half_w, cy + half_h),
                ])
            gdf = gdf.copy()
            gdf["geometry"] = gdf["geometry"].intersection(clip_shape)
            # Remove empty geometries after clipping
            gdf = gdf[~gdf["geometry"].is_empty]

        return gdf

    except Exception as e:
        print(f"  Warning: Could not fetch {tags}: {e}", file=sys.stderr)
        return gpd.GeoDataFrame()


# ── SVG Generation ───────────────────────────────────────────────────────────

def generate_svg(place=None, bbox=None, radius=None, style_name="default",
                 paper="a3l", margins=(15, 15, 15, 15), output="output.svg", clip_circle=False,
                 layer_filter=None):
    """Main pipeline: fetch data → project → write SVG."""

    style = STYLES.get(style_name, STYLES["default"])
    paper_w, paper_h = PAPER_SIZES.get(paper, PAPER_SIZES["a3l"])
    paper_aspect = paper_w / paper_h  # >1 for landscape

    # Use mm as SVG units (1:1 for plotter)
    canvas_w = paper_w
    canvas_h = paper_h

    # Try to parse place as GPS coordinates
    center = None
    if place:
        center = parse_center(place)
        if center:
            print(f"CityPlot: ({center[0]}, {center[1]})")
        else:
            print(f"CityPlot: {place}")
    else:
        print(f"CityPlot: {bbox}")
    # Filter layers if requested
    if layer_filter:
        style["layers"] = {k: v for k, v in style["layers"].items() if k in layer_filter}
        if not style["layers"]:
            print(f"Error: No matching layers. Available: {', '.join(STYLES[style_name]['layers'].keys())}", file=sys.stderr)
            sys.exit(1)

    margin_top, margin_right, margin_bottom, margin_left = margins
    active_layers = ', '.join(style["layers"].keys())
    print(f"  Style: {style_name}, Paper: {paper} ({paper_w}×{paper_h}mm)")
    print(f"  Radius: {radius}m, Margins: {margin_top}/{margin_right}/{margin_bottom}/{margin_left}mm")
    print(f"  Layers: {active_layers}")

    # ── Compute clip center in UTM ──
    clip_center_utm = None
    if center:
        geocenter = center
    elif place:
        geocenter = ox.geocode(place)
    else:
        geocenter = None

    if geocenter and radius:
        # Create a tiny GeoDataFrame to project the center point to UTM
        center_gdf = gpd.GeoDataFrame(
            geometry=[Point(geocenter[1], geocenter[0])],  # lon, lat
            crs="EPSG:4326"
        )
        center_gdf = ox.projection.project_gdf(center_gdf)
        cp = center_gdf.geometry.iloc[0]
        clip_center_utm = (cp.x, cp.y)
        clip_mode = "circle" if clip_circle else "rect"
        print(f"  Clip center (UTM): {cp.x:.0f}, {cp.y:.0f} [{clip_mode}]")

    # ── Fetch all layers ──
    all_lines = {}
    all_bounds = []

    for layer_name, layer_cfg in style["layers"].items():
        print(f"  Fetching {layer_name}...")
        gdf = fetch_features(place=place, center=center, bbox=bbox, radius=radius,
                             tags=layer_cfg["tags"],
                             clip_center_utm=clip_center_utm, clip_radius=radius,
                             clip_circle=clip_circle, paper_aspect=paper_aspect)

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
        debug=False,
    )

    # Register Inkscape namespace for layer support
    dwg.attribs['xmlns:inkscape'] = INKSCAPE_NS

    # Background (optional, comment out for transparent)
    # dwg.add(dwg.rect(insert=(0, 0), size=(canvas_w, canvas_h), fill="white"))

    # ── Render layers ──
    for layer_name, (lines, cfg) in all_lines.items():
        label = LAYER_LABELS.get(layer_name, layer_name)
        group = dwg.g(id=layer_name)
        group.attribs['inkscape:groupmode'] = 'layer'
        group.attribs['inkscape:label'] = label

        transformed = transform_coords(lines, bounds, canvas_w, canvas_h, margins)
        transformed = optimize_path_order(transformed)

        for coords in transformed:
            if len(coords) < 2:
                continue

            path_data = f"M {coords[0][0]},{coords[0][1]}"
            for x, y in coords[1:]:
                path_data += f" L {x},{y}"

            # Close polygon paths (first ≈ last point, or layer has fill)
            is_closed = (coords[0][0] == coords[-1][0] and coords[0][1] == coords[-1][1])
            has_fill = cfg.get("fill", "none") != "none"
            if is_closed or has_fill:
                path_data += " Z"

            extra = {}
            if "dasharray" in cfg:
                extra["stroke_dasharray"] = cfg["dasharray"]

            group.add(dwg.path(
                d=path_data,
                stroke=cfg["stroke"],
                stroke_width=cfg["width"],
                fill=cfg.get("fill", "none"),
                stroke_linecap="round",
                stroke_linejoin="round",
                **extra,
            ))

        dwg.add(group)

    # ── Optional circle border ──
    if clip_circle:
        cx, cy = canvas_w / 2, canvas_h / 2
        # Draw the clip circle as a visible border
        minx, miny, maxx, maxy = bounds
        geo_w = maxx - minx
        geo_h = maxy - miny
        margin_top, margin_right, margin_bottom, margin_left = margins
        draw_w = canvas_w - margin_left - margin_right
        draw_h = canvas_h - margin_top - margin_bottom
        scale = min(draw_w / geo_w, draw_h / geo_h) if geo_w and geo_h else 1
        r_svg = radius * scale if radius else min(draw_w, draw_h) / 2
        # Center of data on canvas
        offset_x = margin_left + (draw_w - geo_w * scale) / 2
        offset_y = margin_top + (draw_h - geo_h * scale) / 2
        cx_svg = offset_x + geo_w * scale / 2
        cy_svg = offset_y + geo_h * scale / 2
        dwg.add(dwg.circle(
            center=(round(cx_svg, 2), round(cy_svg, 2)),
            r=round(r_svg, 2),
            stroke="#000000", stroke_width=0.3, fill="none"
        ))

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
    parser.add_argument("--radius", default="2000", help="Radius: meters (e.g. 2000) or km (e.g. 1.5k or 1.5km)")
    parser.add_argument("--style", choices=STYLES.keys(), default="default", help="Visual style preset")
    parser.add_argument("--paper", choices=PAPER_SIZES.keys(), default="a3l", help="Paper size (default: a3l)")
    parser.add_argument("--margin", default="15", help="Margin in mm: single value (all sides), 2 values 'V,H', or 4 values 'top,right,bottom,left'")
    parser.add_argument("--output", "-o", default="output.svg", help="Output SVG file")
    parser.add_argument("--layers", help="Comma-separated layer names to include (default: all). Use --list-styles to see layer names")
    parser.add_argument("--circle", action="store_true", help="Apply circular clip mask")
    parser.add_argument("--list-styles", action="store_true", help="List available styles and their layers")

    args = parser.parse_args()

    if args.list_styles:
        for name, style in STYLES.items():
            layers = ", ".join(style["layers"].keys())
            print(f"  {name}: {layers}")
        sys.exit(0)

    if not args.place and not args.bbox:
        parser.error("Provide a place name, GPS coordinates (lat,lon), or --bbox")

    # Parse radius (support m and km)
    radius_str = args.radius.strip().lower()
    if radius_str.endswith("km"):
        radius = int(float(radius_str[:-2]) * 1000)
    elif radius_str.endswith("k"):
        radius = int(float(radius_str[:-1]) * 1000)
    else:
        radius = int(float(radius_str))
    args.radius = radius

    # Parse margins (top, right, bottom, left — CSS order)
    margin_parts = [float(x) for x in args.margin.split(",")]
    if len(margin_parts) == 1:
        margins = (margin_parts[0],) * 4
    elif len(margin_parts) == 2:
        margins = (margin_parts[0], margin_parts[1], margin_parts[0], margin_parts[1])
    elif len(margin_parts) == 4:
        margins = tuple(margin_parts)
    else:
        parser.error("--margin: 1 value (all), 2 values (vertical,horizontal), or 4 values (top,right,bottom,left)")

    bbox = None
    if args.bbox:
        bbox = [float(x) for x in args.bbox.split(",")]
        if len(bbox) != 4:
            parser.error("--bbox requires exactly 4 values: west,south,east,north")

    layer_filter = None
    if args.layers:
        layer_filter = [l.strip() for l in args.layers.split(",")]

    generate_svg(
        place=args.place,
        bbox=bbox,
        radius=args.radius,
        style_name=args.style,
        paper=args.paper,
        margins=margins,
        output=args.output,
        clip_circle=args.circle,
        layer_filter=layer_filter,
    )


if __name__ == "__main__":
    main()
