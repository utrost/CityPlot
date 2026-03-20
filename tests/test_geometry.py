"""Tests for geometry helper functions."""

import pytest
from shapely.geometry import (
    LineString, MultiLineString, Polygon, MultiPolygon, Point,
    GeometryCollection,
)

from cityplot import geometry_to_lines, transform_coords


class TestGeometryToLines:
    """Test extraction of line coordinates from various geometry types."""

    def test_none_returns_empty(self):
        assert geometry_to_lines(None) == []

    def test_point_returns_empty(self):
        assert geometry_to_lines(Point(0, 0)) == []

    def test_linestring(self):
        ls = LineString([(0, 0), (1, 1), (2, 0)])
        result = geometry_to_lines(ls)
        assert len(result) == 1
        assert result[0] == [(0, 0), (1, 1), (2, 0)]

    def test_multilinestring(self):
        mls = MultiLineString([
            [(0, 0), (1, 1)],
            [(2, 2), (3, 3)],
        ])
        result = geometry_to_lines(mls)
        assert len(result) == 2

    def test_polygon_exterior_only(self):
        poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        result = geometry_to_lines(poly)
        assert len(result) == 1
        # Polygon exterior is auto-closed by Shapely (5 coords for a square)
        assert result[0][0] == result[0][-1]

    def test_polygon_with_hole(self):
        exterior = [(0, 0), (10, 0), (10, 10), (0, 10)]
        hole = [(2, 2), (8, 2), (8, 8), (2, 8)]
        poly = Polygon(exterior, [hole])
        result = geometry_to_lines(poly)
        assert len(result) == 2  # exterior + 1 interior ring

    def test_multipolygon(self):
        p1 = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        p2 = Polygon([(5, 5), (6, 5), (6, 6), (5, 6)])
        mp = MultiPolygon([p1, p2])
        result = geometry_to_lines(mp)
        assert len(result) == 2

    def test_geometry_collection(self):
        ls = LineString([(0, 0), (1, 1)])
        poly = Polygon([(2, 2), (3, 2), (3, 3), (2, 3)])
        gc = GeometryCollection([ls, poly])
        result = geometry_to_lines(gc)
        assert len(result) == 2  # 1 from linestring + 1 from polygon

    def test_empty_geometry_collection(self):
        gc = GeometryCollection()
        assert geometry_to_lines(gc) == []


class TestTransformCoords:
    """Test coordinate transformation from geographic to SVG canvas."""

    def test_basic_transform(self):
        lines = [[(0, 0), (100, 100)]]
        bounds = (0, 0, 100, 100)
        result = transform_coords(lines, bounds, 420, 297, (15, 15, 15, 15))
        assert len(result) == 1
        assert len(result[0]) == 2
        # All coords should be within canvas
        for x, y in result[0]:
            assert 0 <= x <= 420
            assert 0 <= y <= 297

    def test_zero_geo_width_returns_empty(self):
        lines = [[(5, 0), (5, 10)]]
        bounds = (5, 0, 5, 10)  # zero width
        result = transform_coords(lines, bounds, 420, 297, (15, 15, 15, 15))
        assert result == []

    def test_zero_geo_height_returns_empty(self):
        lines = [[(0, 5), (10, 5)]]
        bounds = (0, 5, 10, 5)  # zero height
        result = transform_coords(lines, bounds, 420, 297, (15, 15, 15, 15))
        assert result == []

    def test_y_axis_is_flipped(self):
        """In SVG, y increases downward; in geo coords, y increases upward."""
        lines = [[(0, 0), (0, 100)]]
        bounds = (0, 0, 100, 100)
        result = transform_coords(lines, bounds, 420, 297, (15, 15, 15, 15))
        # Point at geo y=0 should have higher SVG y than point at geo y=100
        assert result[0][0][1] > result[0][1][1]

    def test_margins_respected(self):
        lines = [[(0, 0), (100, 100)]]
        bounds = (0, 0, 100, 100)
        margin = (20, 20, 20, 20)
        result = transform_coords(lines, bounds, 420, 297, margin)
        for x, y in result[0]:
            assert x >= 20
            assert y >= 20

    def test_aspect_ratio_maintained(self):
        """Square input mapped to rectangular canvas should maintain aspect ratio."""
        lines = [[(0, 0), (100, 0), (100, 100), (0, 100)]]
        bounds = (0, 0, 100, 100)
        result = transform_coords(lines, bounds, 420, 297, (15, 15, 15, 15))
        coords = result[0]
        # Width and height of transformed result should be equal (square input)
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        assert abs(w - h) < 0.1

    def test_empty_lines_input(self):
        result = transform_coords([], (0, 0, 100, 100), 420, 297, (15, 15, 15, 15))
        assert result == []

    def test_asymmetric_margins(self):
        lines = [[(0, 0), (100, 100)]]
        bounds = (0, 0, 100, 100)
        margins = (10, 30, 20, 40)  # top, right, bottom, left
        result = transform_coords(lines, bounds, 420, 297, margins)
        assert len(result) == 1
        for x, y in result[0]:
            assert x >= 0
            assert y >= 0
