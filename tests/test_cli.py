"""Tests for CLI argument parsing."""

import pytest
import sys
from unittest.mock import patch, MagicMock

from cityplot import main, STYLES, PAPER_SIZES, parse_center


class TestParseCenter:
    """Test GPS coordinate parsing."""

    def test_valid_gps_coords(self):
        assert parse_center("53.07,8.80") == (53.07, 8.80)

    def test_negative_coords(self):
        assert parse_center("-33.87,151.21") == (-33.87, 151.21)

    def test_coords_with_spaces(self):
        assert parse_center("53.07, 8.80") == (53.07, 8.80)

    def test_place_name_returns_none(self):
        assert parse_center("Bremen, Germany") is None

    def test_none_input(self):
        assert parse_center(None) is None

    def test_empty_string(self):
        assert parse_center("") is None

    def test_three_part_string_returns_none(self):
        assert parse_center("1,2,3") is None

    def test_lat_out_of_range(self):
        assert parse_center("91,0") is None

    def test_lon_out_of_range(self):
        assert parse_center("0,181") is None

    def test_non_numeric_parts(self):
        assert parse_center("abc,def") is None


class TestCLIArgumentParsing:
    """Test argument parsing via main()."""

    def _run_main(self, args):
        """Run main() with given args, mocking generate_svg."""
        with patch("cityplot.generate_svg") as mock_gen, \
             patch("sys.argv", ["cityplot"] + args):
            main()
            return mock_gen

    def test_basic_place_argument(self):
        mock = self._run_main(["Bremen"])
        mock.assert_called_once()
        call_kwargs = mock.call_args[1]
        assert call_kwargs["place"] == "Bremen"

    def test_default_radius(self):
        mock = self._run_main(["Bremen"])
        assert mock.call_args[1]["radius"] == 2000

    def test_radius_in_meters(self):
        mock = self._run_main(["Bremen", "--radius", "3000"])
        assert mock.call_args[1]["radius"] == 3000

    def test_radius_in_km_suffix(self):
        mock = self._run_main(["Bremen", "--radius", "1.5km"])
        assert mock.call_args[1]["radius"] == 1500

    def test_radius_in_k_suffix(self):
        mock = self._run_main(["Bremen", "--radius", "2k"])
        assert mock.call_args[1]["radius"] == 2000

    def test_style_option(self):
        mock = self._run_main(["Bremen", "--style", "minimal"])
        assert mock.call_args[1]["style_name"] == "minimal"

    def test_paper_option(self):
        mock = self._run_main(["Bremen", "--paper", "a4"])
        assert mock.call_args[1]["paper"] == "a4"

    def test_output_option(self):
        mock = self._run_main(["Bremen", "--output", "test.svg"])
        assert mock.call_args[1]["output"] == "test.svg"

    def test_output_short_option(self):
        mock = self._run_main(["Bremen", "-o", "test.svg"])
        assert mock.call_args[1]["output"] == "test.svg"

    def test_circle_flag(self):
        mock = self._run_main(["Bremen", "--circle"])
        assert mock.call_args[1]["clip_circle"] is True

    def test_no_circle_by_default(self):
        mock = self._run_main(["Bremen"])
        assert mock.call_args[1]["clip_circle"] is False

    def test_single_margin(self):
        mock = self._run_main(["Bremen", "--margin", "20"])
        assert mock.call_args[1]["margins"] == (20, 20, 20, 20)

    def test_two_value_margin(self):
        mock = self._run_main(["Bremen", "--margin", "10,20"])
        assert mock.call_args[1]["margins"] == (10, 20, 10, 20)

    def test_four_value_margin(self):
        mock = self._run_main(["Bremen", "--margin", "10,20,30,40"])
        assert mock.call_args[1]["margins"] == (10, 20, 30, 40)

    def test_bbox_option(self):
        mock = self._run_main(["--bbox", "8.78,53.06,8.84,53.09"])
        call_kwargs = mock.call_args[1]
        assert call_kwargs["bbox"] == [8.78, 53.06, 8.84, 53.09]

    def test_layers_filter(self):
        mock = self._run_main(["Bremen", "--layers", "water,buildings"])
        assert mock.call_args[1]["layer_filter"] == ["water", "buildings"]

    def test_missing_place_and_bbox_exits(self):
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["cityplot"]):
                main()

    def test_invalid_style_exits(self):
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["cityplot", "Bremen", "--style", "nonexistent"]):
                main()

    def test_list_styles(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["cityplot", "--list-styles"]):
                main()
        assert exc_info.value.code == 0
        output = capsys.readouterr().out
        for style_name in STYLES:
            assert style_name in output
