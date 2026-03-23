"""Tests for fetch_features and generate_svg edge cases."""

import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest
import geopandas as gpd
from shapely.geometry import LineString, Polygon, Point

from cityplot import fetch_features, generate_svg, STYLES


class TestFetchFeatures:
    """Test fetch_features with mocked osmnx calls."""

    def _make_gdf(self, geometries=None):
        if geometries is None:
            geometries = [LineString([(0, 0), (1, 1)])]
        gdf = gpd.GeoDataFrame(geometry=geometries, crs="EPSG:4326")
        return gdf

    @patch("cityplot.ox")
    def test_bbox_mode(self, mock_ox):
        """Test fetching with bbox."""
        mock_ox.features_from_bbox.return_value = self._make_gdf()
        mock_ox.projection.project_gdf.return_value = self._make_gdf()
        result = fetch_features(bbox=[8.78, 53.06, 8.84, 53.09],
                                tags={"highway": "primary"})
        mock_ox.features_from_bbox.assert_called_once()
        assert not result.empty

    @patch("cityplot.ox")
    def test_center_radius_mode(self, mock_ox):
        """Test fetching with center + radius."""
        mock_ox.features_from_point.return_value = self._make_gdf()
        mock_ox.projection.project_gdf.return_value = self._make_gdf()
        result = fetch_features(center=(53.07, 8.80), radius=2000,
                                tags={"highway": "primary"})
        mock_ox.features_from_point.assert_called_once_with(
            (53.07, 8.80), dist=2000, tags={"highway": "primary"})
        assert not result.empty

    @patch("cityplot.ox")
    def test_place_radius_mode(self, mock_ox):
        """Test fetching with place name + radius."""
        mock_ox.geocode.return_value = (53.07, 8.80)
        mock_ox.features_from_point.return_value = self._make_gdf()
        mock_ox.projection.project_gdf.return_value = self._make_gdf()
        result = fetch_features(place="Bremen", radius=2000,
                                tags={"highway": "primary"})
        mock_ox.geocode.assert_called_once_with("Bremen")
        assert not result.empty

    @patch("cityplot.ox")
    def test_place_only_mode(self, mock_ox):
        """Test fetching with place name only (no radius)."""
        mock_ox.features_from_place.return_value = self._make_gdf()
        mock_ox.projection.project_gdf.return_value = self._make_gdf()
        result = fetch_features(place="Bremen",
                                tags={"highway": "primary"})
        mock_ox.features_from_place.assert_called_once_with(
            "Bremen", tags={"highway": "primary"})
        assert not result.empty

    def test_no_args_returns_empty(self):
        """No place, center, or bbox should return empty GDF."""
        result = fetch_features(tags={"highway": "primary"})
        assert result.empty

    @patch("cityplot.ox")
    def test_empty_result_returns_early(self, mock_ox):
        """Empty GDF from API should be returned as-is."""
        mock_ox.features_from_bbox.return_value = gpd.GeoDataFrame()
        result = fetch_features(bbox=[8.78, 53.06, 8.84, 53.09],
                                tags={"highway": "primary"})
        assert result.empty
        # project_gdf should not be called for empty results
        mock_ox.projection.project_gdf.assert_not_called()

    @patch("cityplot.ox")
    def test_exception_returns_empty(self, mock_ox):
        """API errors should be caught and return empty GDF."""
        mock_ox.features_from_bbox.side_effect = Exception("Network error")
        result = fetch_features(bbox=[8.78, 53.06, 8.84, 53.09],
                                tags={"highway": "primary"})
        assert result.empty

    @patch("cityplot.ox")
    def test_rectangular_clip_landscape(self, mock_ox):
        """Test rectangular clipping with landscape aspect ratio."""
        geoms = [Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])]
        gdf = gpd.GeoDataFrame(geometry=geoms, crs="EPSG:32632")
        mock_ox.features_from_point.return_value = gdf
        mock_ox.projection.project_gdf.return_value = gdf

        result = fetch_features(
            center=(53.07, 8.80), radius=1000,
            tags={"building": True},
            clip_center_utm=(50, 50), clip_radius=1000,
            clip_circle=False, paper_aspect=1.5,  # landscape
        )
        assert not result.empty

    @patch("cityplot.ox")
    def test_rectangular_clip_portrait(self, mock_ox):
        """Test rectangular clipping with portrait aspect ratio."""
        geoms = [Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])]
        gdf = gpd.GeoDataFrame(geometry=geoms, crs="EPSG:32632")
        mock_ox.features_from_point.return_value = gdf
        mock_ox.projection.project_gdf.return_value = gdf

        result = fetch_features(
            center=(53.07, 8.80), radius=1000,
            tags={"building": True},
            clip_center_utm=(50, 50), clip_radius=1000,
            clip_circle=False, paper_aspect=0.7,  # portrait
        )
        assert not result.empty

    @patch("cityplot.ox")
    def test_circle_clip(self, mock_ox):
        """Test circular clipping."""
        geoms = [Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])]
        gdf = gpd.GeoDataFrame(geometry=geoms, crs="EPSG:32632")
        mock_ox.features_from_point.return_value = gdf
        mock_ox.projection.project_gdf.return_value = gdf

        result = fetch_features(
            center=(53.07, 8.80), radius=1000,
            tags={"building": True},
            clip_center_utm=(50, 50), clip_radius=1000,
            clip_circle=True,
        )
        assert not result.empty

    @patch("cityplot.ox")
    def test_clip_removes_empty_geometries(self, mock_ox):
        """Geometries fully outside clip region should be removed."""
        # Geometry far from clip center
        geoms = [Polygon([(9999, 9999), (10000, 9999),
                          (10000, 10000), (9999, 10000)])]
        gdf = gpd.GeoDataFrame(geometry=geoms, crs="EPSG:32632")
        mock_ox.features_from_point.return_value = gdf
        mock_ox.projection.project_gdf.return_value = gdf

        result = fetch_features(
            center=(53.07, 8.80), radius=10,
            tags={"building": True},
            clip_center_utm=(0, 0), clip_radius=10,
            clip_circle=False, paper_aspect=1.0,
        )
        assert result.empty
