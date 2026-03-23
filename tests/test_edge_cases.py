"""Tests for edge cases and uncovered code paths in cityplot."""

import copy
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

import pytest
import geopandas as gpd
from shapely.geometry import LineString, Polygon, Point

import cityplot
from cityplot import generate_svg, main, STYLES, PAPER_SIZES


@pytest.fixture(autouse=True)
def restore_styles():
    """Restore STYLES after each test since generate_svg mutates it."""
    original = copy.deepcopy(cityplot.STYLES)
    yield
    cityplot.STYLES.update(original)


def _make_mock_gdf(geometries):
    return gpd.GeoDataFrame(geometry=geometries, crs="EPSG:32632")


def _mock_fetch_factory(layer_data):
    def mock_fetch(place=None, center=None, bbox=None, radius=None, tags=None, **kwargs):
        for layer_name, cfg in layer_data.items():
            if tags == cfg["tags"]:
                return cfg["gdf"]
        return gpd.GeoDataFrame()
    return mock_fetch


def _build_layer_data(style_name="default", empty_layers=None):
    """Build mock layer data, optionally making some layers empty."""
    style = STYLES[style_name]
    layer_data = {}
    for layer_name, cfg in style["layers"].items():
        if empty_layers and layer_name in empty_layers:
            layer_data[layer_name] = {
                "tags": cfg["tags"],
                "gdf": gpd.GeoDataFrame(),
            }
        else:
            geoms = [
                LineString([(500000 + i * 10, 5800000 + i * 10) for i in range(5)]),
                Polygon([(500050, 5800050), (500100, 5800050),
                         (500100, 5800100), (500050, 5800100)]),
            ]
            layer_data[layer_name] = {
                "tags": cfg["tags"],
                "gdf": _make_mock_gdf(geoms),
            }
    return layer_data


class TestGenerateSVGBboxMode:
    """Test generate_svg with bbox input (covers line 259)."""

    def test_bbox_prints_bbox(self, capsys):
        layer_data = _build_layer_data("minimal")
        fd, svg_path = tempfile.mkstemp(suffix=".svg")
        os.close(fd)
        try:
            with patch("cityplot.fetch_features",
                       side_effect=_mock_fetch_factory(layer_data)):
                generate_svg(
                    bbox=[8.78, 53.06, 8.84, 53.09],
                    radius=2000,
                    style_name="minimal",
                    output=svg_path,
                )
            output = capsys.readouterr().out
            assert "[8.78, 53.06, 8.84, 53.09]" in output
        finally:
            if os.path.exists(svg_path):
                os.unlink(svg_path)


class TestGenerateSVGEmptyLayers:
    """Test generate_svg when some layers return empty data."""

    def test_empty_layer_is_skipped(self, capsys):
        """Layers that return empty GDF should be skipped (covers line 306-307)."""
        layer_data = _build_layer_data("minimal", empty_layers=["streets_minor"])
        fd, svg_path = tempfile.mkstemp(suffix=".svg")
        os.close(fd)
        try:
            with patch("cityplot.fetch_features",
                       side_effect=_mock_fetch_factory(layer_data)):
                generate_svg(
                    place="53.07,8.80",
                    radius=2000,
                    style_name="minimal",
                    output=svg_path,
                )
            output = capsys.readouterr().out
            assert "empty" in output
        finally:
            if os.path.exists(svg_path):
                os.unlink(svg_path)


class TestGenerateSVGNoData:
    """Test generate_svg when no data is found (covers line 323-324)."""

    def test_no_data_exits(self):
        """All empty layers should cause sys.exit(1)."""
        layer_data = _build_layer_data("minimal",
                                        empty_layers=list(STYLES["minimal"]["layers"].keys()))
        fd, svg_path = tempfile.mkstemp(suffix=".svg")
        os.close(fd)
        try:
            with patch("cityplot.fetch_features",
                       side_effect=_mock_fetch_factory(layer_data)):
                with pytest.raises(SystemExit) as exc_info:
                    generate_svg(
                        place="53.07,8.80",
                        radius=2000,
                        style_name="minimal",
                        output=svg_path,
                    )
                assert exc_info.value.code == 1
        finally:
            if os.path.exists(svg_path):
                os.unlink(svg_path)


class TestGenerateSVGInvalidLayerFilter:
    """Test layer filter with no matching layers (covers line 264-265)."""

    def test_empty_filter_result_exits(self):
        fd, svg_path = tempfile.mkstemp(suffix=".svg")
        os.close(fd)
        try:
            with pytest.raises(SystemExit) as exc_info:
                generate_svg(
                    place="53.07,8.80",
                    radius=2000,
                    style_name="default",
                    output=svg_path,
                    layer_filter=["nonexistent_layer"],
                )
            assert exc_info.value.code == 1
        finally:
            if os.path.exists(svg_path):
                os.unlink(svg_path)


class TestGenerateSVGSinglePointPaths:
    """Test that single-point paths are skipped (covers line 356)."""

    def test_single_coord_path_skipped(self):
        """Lines with < 2 coords after transform should be skipped."""
        style = STYLES["minimal"]
        layer_data = {}
        for layer_name, cfg in style["layers"].items():
            # Create a geometry that will produce a single-point line
            geoms = [
                LineString([(500000, 5800000), (500000, 5800000)]),  # degenerate
                LineString([(500000, 5800000), (500050, 5800050)]),  # valid
            ]
            layer_data[layer_name] = {
                "tags": cfg["tags"],
                "gdf": _make_mock_gdf(geoms),
            }

        fd, svg_path = tempfile.mkstemp(suffix=".svg")
        os.close(fd)
        try:
            with patch("cityplot.fetch_features",
                       side_effect=_mock_fetch_factory(layer_data)):
                generate_svg(
                    place="53.07,8.80",
                    radius=2000,
                    style_name="minimal",
                    output=svg_path,
                )
            assert os.path.exists(svg_path)
        finally:
            if os.path.exists(svg_path):
                os.unlink(svg_path)


class TestGenerateSVGFallbackStyle:
    """Test that invalid style name falls back to default."""

    def test_unknown_style_uses_default(self):
        layer_data = _build_layer_data("default")
        fd, svg_path = tempfile.mkstemp(suffix=".svg")
        os.close(fd)
        try:
            with patch("cityplot.fetch_features",
                       side_effect=_mock_fetch_factory(layer_data)):
                generate_svg(
                    place="53.07,8.80",
                    radius=2000,
                    style_name="nonexistent_style",
                    output=svg_path,
                )
            assert os.path.exists(svg_path)
        finally:
            if os.path.exists(svg_path):
                os.unlink(svg_path)


class TestCLIErrorPaths:
    """Test CLI error paths."""

    def test_three_value_margin_exits(self):
        """3 margin values should cause parser error (covers line 461)."""
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["cityplot", "Bremen", "--margin", "10,20,30"]):
                main()

    def test_invalid_bbox_count_exits(self):
        """bbox with != 4 values should cause parser error (covers line 467)."""
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["cityplot", "--bbox", "8.78,53.06,8.84"]):
                main()

    def test_invalid_bbox_five_values_exits(self):
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["cityplot", "--bbox", "1,2,3,4,5"]):
                main()


class TestGenerateSVGDasharray:
    """Test that railway layer gets stroke-dasharray."""

    def test_railway_has_dasharray(self):
        layer_data = _build_layer_data("default")
        fd, svg_path = tempfile.mkstemp(suffix=".svg")
        os.close(fd)
        try:
            with patch("cityplot.fetch_features",
                       side_effect=_mock_fetch_factory(layer_data)):
                generate_svg(
                    place="53.07,8.80",
                    radius=2000,
                    style_name="default",
                    output=svg_path,
                )
            with open(svg_path) as f:
                content = f.read()
            assert "stroke-dasharray" in content
        finally:
            if os.path.exists(svg_path):
                os.unlink(svg_path)
