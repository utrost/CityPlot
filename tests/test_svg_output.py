"""Tests for SVG output validation."""

import copy
import os
import tempfile
import xml.etree.ElementTree as ET
from unittest.mock import patch

import pytest
import geopandas as gpd
from shapely.geometry import LineString, Polygon, Point

import cityplot
from cityplot import generate_svg, STYLES, PAPER_SIZES, LAYER_LABELS, INKSCAPE_NS


@pytest.fixture(autouse=True)
def restore_styles():
    """Restore STYLES after each test since generate_svg mutates it."""
    original = copy.deepcopy(cityplot.STYLES)
    yield
    cityplot.STYLES.update(original)


def _make_mock_gdf(geometries):
    """Create a GeoDataFrame from a list of geometries with a CRS."""
    gdf = gpd.GeoDataFrame(geometry=geometries, crs="EPSG:32632")
    return gdf


def _mock_fetch_factory(layer_data):
    """Return a fetch_features mock that returns pre-built GeoDataFrames per tag set."""
    def mock_fetch(place=None, center=None, bbox=None, radius=None, tags=None, **kwargs):
        # Match by tags to decide which layer we're returning data for
        for layer_name, cfg in layer_data.items():
            if tags == cfg["tags"]:
                return cfg["gdf"]
        return gpd.GeoDataFrame()
    return mock_fetch


def _generate_test_svg(style_name="default", paper="a3l", margins=(15, 15, 15, 15),
                       clip_circle=False, layer_filter=None):
    """Generate a test SVG with mocked data and return (path, ElementTree root)."""
    style = STYLES[style_name]
    # Build mock data: simple geometries for each layer
    layer_data = {}
    for layer_name, cfg in style["layers"].items():
        if layer_filter and layer_name not in layer_filter:
            continue
        # Create simple line and polygon geometries in UTM-like coords
        geoms = [
            LineString([(500000 + i * 10, 5800000 + i * 10)
                        for i in range(5)]),
            Polygon([(500050, 5800050), (500100, 5800050),
                     (500100, 5800100), (500050, 5800100)]),
        ]
        layer_data[layer_name] = {
            "tags": cfg["tags"],
            "gdf": _make_mock_gdf(geoms),
        }

    fd, svg_path = tempfile.mkstemp(suffix=".svg")
    os.close(fd)

    try:
        with patch("cityplot.fetch_features", side_effect=_mock_fetch_factory(layer_data)):
            generate_svg(
                place="53.07,8.80",
                radius=2000,
                style_name=style_name,
                paper=paper,
                margins=margins,
                output=svg_path,
                clip_circle=clip_circle,
                layer_filter=layer_filter,
            )
        tree = ET.parse(svg_path)
        root = tree.getroot()
        return svg_path, root
    except Exception:
        os.unlink(svg_path)
        raise


class TestSVGStructure:
    """Test that generated SVGs have correct structure."""

    def setup_method(self):
        self.svg_path, self.root = _generate_test_svg()

    def teardown_method(self):
        if os.path.exists(self.svg_path):
            os.unlink(self.svg_path)

    def test_root_is_svg_element(self):
        assert self.root.tag.endswith("svg")

    def test_has_viewbox(self):
        assert "viewBox" in self.root.attrib

    def test_viewbox_matches_paper(self):
        vb = self.root.attrib["viewBox"]
        parts = vb.split()
        assert parts[0] == "0"
        assert parts[1] == "0"
        w, h = PAPER_SIZES["a3l"]
        assert parts[2] == str(w)
        assert parts[3] == str(h)

    def test_has_size_in_mm(self):
        w, h = PAPER_SIZES["a3l"]
        assert self.root.attrib.get("width") == f"{w}mm"
        assert self.root.attrib.get("height") == f"{h}mm"

    def test_has_inkscape_namespace(self):
        ns_attr = f"xmlns:inkscape"
        # Check in raw XML since ET may normalize namespace declarations
        with open(self.svg_path) as f:
            content = f.read()
        assert INKSCAPE_NS in content


class TestSVGLayers:
    """Test that SVG contains expected layers."""

    def setup_method(self):
        self.svg_path, self.root = _generate_test_svg()
        self.ns = {"svg": "http://www.w3.org/2000/svg"}

    def teardown_method(self):
        if os.path.exists(self.svg_path):
            os.unlink(self.svg_path)

    def _get_groups(self):
        return self.root.findall(".//{http://www.w3.org/2000/svg}g")

    def test_has_layer_groups(self):
        groups = self._get_groups()
        assert len(groups) > 0

    def test_layer_ids_match_style(self):
        groups = self._get_groups()
        group_ids = {g.attrib.get("id") for g in groups}
        for layer_name in STYLES["default"]["layers"]:
            assert layer_name in group_ids, f"Layer '{layer_name}' missing from SVG"

    def test_layers_have_inkscape_attributes(self):
        with open(self.svg_path) as f:
            content = f.read()
        for layer_name in STYLES["default"]["layers"]:
            label = LAYER_LABELS.get(layer_name, layer_name)
            assert f'inkscape:label="{label}"' in content
            assert 'inkscape:groupmode="layer"' in content

    def test_layers_contain_paths(self):
        groups = self._get_groups()
        for group in groups:
            paths = group.findall("{http://www.w3.org/2000/svg}path")
            assert len(paths) > 0, f"Layer '{group.attrib.get('id')}' has no paths"


class TestSVGPaths:
    """Test SVG path data correctness."""

    def setup_method(self):
        self.svg_path, self.root = _generate_test_svg()

    def teardown_method(self):
        if os.path.exists(self.svg_path):
            os.unlink(self.svg_path)

    def _get_all_paths(self):
        return self.root.findall(".//{http://www.w3.org/2000/svg}path")

    def test_paths_have_d_attribute(self):
        for path in self._get_all_paths():
            assert "d" in path.attrib

    def test_paths_start_with_M(self):
        for path in self._get_all_paths():
            assert path.attrib["d"].startswith("M ")

    def test_paths_have_stroke(self):
        for path in self._get_all_paths():
            assert "stroke" in path.attrib

    def test_paths_have_stroke_width(self):
        for path in self._get_all_paths():
            assert "stroke-width" in path.attrib

    def test_closed_polygons_end_with_Z(self):
        """Polygon paths (with fill) should end with Z."""
        for path in self._get_all_paths():
            fill = path.attrib.get("fill", "none")
            if fill != "none":
                assert path.attrib["d"].endswith("Z"), (
                    f"Filled path should be closed with Z"
                )


class TestSVGPaperSizes:
    """Test SVG generation with different paper sizes."""

    @pytest.mark.parametrize("paper", PAPER_SIZES.keys())
    def test_viewbox_matches_paper_size(self, paper):
        svg_path, root = _generate_test_svg(paper=paper, style_name="minimal")
        try:
            w, h = PAPER_SIZES[paper]
            vb = root.attrib["viewBox"]
            assert vb == f"0 0 {w} {h}"
        finally:
            os.unlink(svg_path)


class TestSVGStyleVariants:
    """Test SVG generation with different styles."""

    @pytest.mark.parametrize("style_name", STYLES.keys())
    def test_style_generates_valid_svg(self, style_name):
        svg_path, root = _generate_test_svg(style_name=style_name)
        try:
            assert root.tag.endswith("svg")
            groups = root.findall(".//{http://www.w3.org/2000/svg}g")
            expected_count = len(STYLES[style_name]["layers"])
            assert len(groups) == expected_count
        finally:
            os.unlink(svg_path)


class TestSVGCircleClip:
    """Test circle clip mode."""

    def test_circle_mode_adds_circle_element(self):
        svg_path, root = _generate_test_svg(clip_circle=True)
        try:
            circles = root.findall(".//{http://www.w3.org/2000/svg}circle")
            assert len(circles) == 1
        finally:
            os.unlink(svg_path)

    def test_no_circle_in_default_mode(self):
        svg_path, root = _generate_test_svg(clip_circle=False)
        try:
            circles = root.findall(".//{http://www.w3.org/2000/svg}circle")
            assert len(circles) == 0
        finally:
            os.unlink(svg_path)


class TestSVGLayerFilter:
    """Test layer filtering."""

    def test_filter_reduces_layers(self):
        svg_path, root = _generate_test_svg(layer_filter=["water", "buildings"])
        try:
            groups = root.findall(".//{http://www.w3.org/2000/svg}g")
            group_ids = {g.attrib.get("id") for g in groups}
            assert group_ids == {"water", "buildings"}
        finally:
            os.unlink(svg_path)
