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
ox.settings.timeout = 60


# ── Style Presets ────────────────────────────────────────────────────────────

STYLES = {
    "default": {
        "layers": {
            "streets_primary":   {"tags": {"highway": ["motorway", "trunk", "primary"]}, "stroke": "#000000", "width": 0.6},
            "streets_secondary": {"tags": {"highway": ["secondary", "tertiary"]}, "stroke": "#000000", "width": 0.35},
            "streets_minor":     {"tags": {"highway": ["residential", "living_street", "unclassified", "pedestrian"]}, "stroke": "#000000", "width": 0.15},
            "water":             {"tags": {"natural": "water", "waterway": ["river", "canal", "stream"]}, "stroke": "#3366aa", "width": 0.3},
            "buildings":         {"tags": {"building": True}, "stroke": "#666666", "width": 0.1},
            "parks":             {"tags": {"leisure": "park"}, "stroke": "#228833", "width": 0.15},
            "railway":           {"tags": {"railway": "rail"}, "stroke": "#444444", "width": 0.25, "dasharray": "4,2"},
        },
    },
    "minimal": {
        "layers": {
            "streets_primary":   {"tags": {"highway": ["motorway", "trunk", "primary"]}, "stroke": "#000000", "width": 0.5},
            "streets_secondary": {"tags": {"highway": ["secondary", "tertiary"]}, "stroke": "#000000", "width": 0.25},
            "streets_minor":     {"tags": {"highway": ["residential", "living_street", "unclassified"]}, "stroke": "#000000", "width": 0.1},
            "water":             {"tags": {"natural": "water", "waterway": ["river", "canal", "stream"]}, "stroke": "#000000", "width": 0.25},
        },
    },
    "buildings": {
        "layers": {
            "buildings":         {"tags": {"building": True}, "stroke": "#000000", "width": 0.1},
            "streets_primary":   {"tags": {"highway": ["motorway", "trunk", "primary", "secondary"]}, "stroke": "#000000", "width": 0.3},
            "water":             {"tags": {"natural": "water", "waterway": ["river", "canal", "stream"]}, "stroke": "#000000", "width": 0.2},
        },
    },
    "mono": {
        "layers": {
            "streets_primary":   {"tags": {"highway": ["motorway", "trunk", "primary"]}, "stroke": "#000000", "width": 0.6},
            "streets_secondary": {"tags": {"highway": ["secondary", "tertiary"]}, "stroke": "#000000", "width": 0.35},
            "streets_minor":     {"tags": {"highway": ["residential", "living_street", "unclassified", "pedestrian"]}, "stroke": "#000000", "width": 0.15},
            "water":             {"tags": {"natural": "water", "waterway": ["river", "canal", "stream"]}, "stroke": "#000000", "width": 0.3},
            "buildings":         {"tags": {"building": True}, "stroke": "#000000", "width": 0.1},
            "parks":             {"tags": {"leisure": "park"}, "stroke": "#000000", "width": 0.15},
            "railway":           {"tags": {"railway": "rail"}, "stroke": "#000000", "width": 0.25, "dasharray": "4,2"},
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
                   clip_center_utm=None, clip_radius=None, clip_circle=False):
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
                clip_shape = Polygon([
                    (cx - clip_radius, cy - clip_radius),
                    (cx + clip_radius, cy - clip_radius),
                    (cx + clip_radius, cy + clip_radius),
                    (cx - clip_radius, cy + clip_radius),
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
                 paper="a3l", margin_mm=15, output="output.svg", clip_circle=False):
    """Main pipeline: fetch data → project → write SVG."""

    style = STYLES.get(style_name, STYLES["default"])
    paper_w, paper_h = PAPER_SIZES.get(paper, PAPER_SIZES["a3l"])

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
    print(f"  Style: {style_name}, Paper: {paper} ({paper_w}×{paper_h}mm)")
    print(f"  Radius: {radius}m")

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
                             clip_circle=clip_circle)

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

    # ── Optional circle border ──
    if clip_circle:
        cx, cy = canvas_w / 2, canvas_h / 2
        # Draw the clip circle as a visible border
        minx, miny, maxx, maxy = bounds
        geo_w = maxx - minx
        geo_h = maxy - miny
        draw_w = canvas_w - 2 * margin_mm
        draw_h = canvas_h - 2 * margin_mm
        scale = min(draw_w / geo_w, draw_h / geo_h) if geo_w and geo_h else 1
        r_svg = radius * scale if radius else min(draw_w, draw_h) / 2
        # Center of data on canvas
        offset_x = margin_mm + (draw_w - geo_w * scale) / 2
        offset_y = margin_mm + (draw_h - geo_h * scale) / 2
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
