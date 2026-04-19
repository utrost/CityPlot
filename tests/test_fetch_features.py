"""Tests for fetch_features and retry logic."""

import os
import tempfile
from unittest.mock import patch, MagicMock, call

import pytest
import geopandas as gpd
from shapely.geometry import LineString, Polygon, Point

from cityplot import fetch_features, _fetch_with_retry, generate_svg, STYLES


class TestFetchFeatures:
    """Test fetch_features with mocked osmnx calls."""

    def _make_gdf(self, geometries=None):
        if geometries is None:
            geometries = [LineString([(0, 0), (1, 1)])]
        gdf = gpd.GeoDataFrame(geometry=geometries, crs="EPSG:4326")
        return gdf

    @patch("cityplot.ox")
    def test_bbox_mode(self, mock_ox):
        mock_ox.features_from_bbox.return_value = self._make_gdf()
        mock_ox.projection.project_gdf.return_value = self._make_gdf()
        result = fetch_features(bbox=[8.78, 53.06, 8.84, 53.09],
                                tags={"highway": "primary"})
        mock_ox.features_from_bbox.assert_called_once()
        assert not result.empty

    @patch("cityplot.ox")
    def test_center_radius_mode(self, mock_ox):
        mock_ox.features_from_point.return_value = self._make_gdf()
        mock_ox.projection.project_gdf.return_value = self._make_gdf()
        result = fetch_features(center=(53.07, 8.80), radius=2000,
                                tags={"highway": "primary"})
        mock_ox.features_from_point.assert_called_once_with(
            (53.07, 8.80), dist=2000, tags={"highway": "primary"})
        assert not result.empty

    @patch("cityplot.ox")
    def test_place_radius_mode(self, mock_ox):
        mock_ox.geocode.return_value = (53.07, 8.80)
        mock_ox.features_from_point.return_value = self._make_gdf()
        mock_ox.projection.project_gdf.return_value = self._make_gdf()
        result = fetch_features(place="Bremen", radius=2000,
                                tags={"highway": "primary"})
        mock_ox.geocode.assert_called_once_with("Bremen")
        assert not result.empty

    @patch("cityplot.ox")
    def test_place_only_mode(self, mock_ox):
        mock_ox.features_from_place.return_value = self._make_gdf()
        mock_ox.projection.project_gdf.return_value = self._make_gdf()
        result = fetch_features(place="Bremen",
                                tags={"highway": "primary"})
        mock_ox.features_from_place.assert_called_once_with(
            "Bremen", tags={"highway": "primary"})
        assert not result.empty

    def test_no_args_returns_empty(self):
        result = fetch_features(tags={"highway": "primary"})
        assert result.empty

    @patch("cityplot.ox")
    def test_empty_result_returns_early(self, mock_ox):
        mock_ox.features_from_bbox.return_value = gpd.GeoDataFrame()
        result = fetch_features(bbox=[8.78, 53.06, 8.84, 53.09],
                                tags={"highway": "primary"})
        assert result.empty
        mock_ox.projection.project_gdf.assert_not_called()

    @patch("cityplot.time.sleep")
    @patch("cityplot.ox")
    def test_exception_retries_then_returns_empty(self, mock_ox, mock_sleep):
        """All retries exhausted should return empty GDF."""
        mock_ox.features_from_bbox.side_effect = Exception("Network error")
        result = fetch_features(bbox=[8.78, 53.06, 8.84, 53.09],
                                tags={"highway": "primary"})
        assert result.empty
        assert mock_ox.features_from_bbox.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("cityplot.ox")
    def test_rectangular_clip_landscape(self, mock_ox):
        geoms = [Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])]
        gdf = gpd.GeoDataFrame(geometry=geoms, crs="EPSG:32632")
        mock_ox.features_from_point.return_value = gdf
        mock_ox.projection.project_gdf.return_value = gdf

        result = fetch_features(
            center=(53.07, 8.80), radius=1000,
            tags={"building": True},
            clip_center_utm=(50, 50), clip_radius=1000,
            clip_circle=False, paper_aspect=1.5,
        )
        assert not result.empty

    @patch("cityplot.ox")
    def test_rectangular_clip_portrait(self, mock_ox):
        geoms = [Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])]
        gdf = gpd.GeoDataFrame(geometry=geoms, crs="EPSG:32632")
        mock_ox.features_from_point.return_value = gdf
        mock_ox.projection.project_gdf.return_value = gdf

        result = fetch_features(
            center=(53.07, 8.80), radius=1000,
            tags={"building": True},
            clip_center_utm=(50, 50), clip_radius=1000,
            clip_circle=False, paper_aspect=0.7,
        )
        assert not result.empty

    @patch("cityplot.ox")
    def test_circle_clip(self, mock_ox):
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


class TestFetchWithRetry:
    """Test the retry mechanism."""

    @patch("cityplot.time.sleep")
    def test_succeeds_on_first_try(self, mock_sleep):
        fn = MagicMock(return_value="ok")
        result = _fetch_with_retry(fn, tags={"test": True})
        assert result == "ok"
        assert fn.call_count == 1
        mock_sleep.assert_not_called()

    @patch("cityplot.time.sleep")
    def test_succeeds_on_second_try(self, mock_sleep):
        fn = MagicMock(side_effect=[Exception("fail"), "ok"])
        result = _fetch_with_retry(fn, tags={"test": True})
        assert result == "ok"
        assert fn.call_count == 2
        mock_sleep.assert_called_once_with(2)

    @patch("cityplot.time.sleep")
    def test_succeeds_on_third_try(self, mock_sleep):
        fn = MagicMock(side_effect=[Exception("fail"), Exception("fail"), "ok"])
        result = _fetch_with_retry(fn, tags={"test": True})
        assert result == "ok"
        assert fn.call_count == 3
        assert mock_sleep.call_args_list == [call(2), call(4)]

    @patch("cityplot.time.sleep")
    def test_all_retries_exhausted_returns_none(self, mock_sleep):
        fn = MagicMock(side_effect=Exception("always fails"))
        result = _fetch_with_retry(fn, tags={"test": True})
        assert result is None
        assert fn.call_count == 3

    @patch("cityplot.time.sleep")
    def test_exponential_backoff_delays(self, mock_sleep):
        fn = MagicMock(side_effect=Exception("fail"))
        _fetch_with_retry(fn, tags={"test": True})
        assert mock_sleep.call_args_list == [call(2), call(4)]


class TestLayerFetchDelay:
    """Test that delays are inserted between layer fetches."""

    @patch("cityplot.time.sleep")
    @patch("cityplot.fetch_features")
    def test_delay_between_layers(self, mock_fetch, mock_sleep):
        """generate_svg should sleep between layer fetches."""
        geoms = [LineString([(500000 + i * 10, 5800000 + i * 10) for i in range(5)])]
        gdf = gpd.GeoDataFrame(geometry=geoms, crs="EPSG:32632")
        mock_fetch.return_value = gdf

        fd, svg_path = tempfile.mkstemp(suffix=".svg")
        os.close(fd)
        try:
            generate_svg(
                place="53.07,8.80",
                radius=2000,
                style_name="minimal",
                output=svg_path,
            )
            num_layers = len(STYLES["minimal"]["layers"])
            sleep_calls = [c for c in mock_sleep.call_args_list if c == call(1.0)]
            assert len(sleep_calls) == num_layers - 1
        finally:
            if os.path.exists(svg_path):
                os.unlink(svg_path)
