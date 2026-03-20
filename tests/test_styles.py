"""Tests for style presets and layer configuration."""

import pytest
from cityplot import STYLES, LAYER_LABELS, PAPER_SIZES


class TestStylePresets:
    """Validate structure and completeness of style presets."""

    def test_all_expected_styles_exist(self):
        expected = {"default", "minimal", "buildings", "mono"}
        assert set(STYLES.keys()) == expected

    def test_each_style_has_layers(self):
        for name, style in STYLES.items():
            assert "layers" in style, f"Style '{name}' missing 'layers' key"
            assert len(style["layers"]) > 0, f"Style '{name}' has no layers"

    @pytest.mark.parametrize("style_name", STYLES.keys())
    def test_layer_config_has_required_fields(self, style_name):
        for layer_name, cfg in STYLES[style_name]["layers"].items():
            assert "tags" in cfg, f"{style_name}.{layer_name} missing 'tags'"
            assert "stroke" in cfg, f"{style_name}.{layer_name} missing 'stroke'"
            assert "width" in cfg, f"{style_name}.{layer_name} missing 'width'"

    @pytest.mark.parametrize("style_name", STYLES.keys())
    def test_stroke_colors_are_hex(self, style_name):
        for layer_name, cfg in STYLES[style_name]["layers"].items():
            stroke = cfg["stroke"]
            assert stroke.startswith("#") and len(stroke) == 7, (
                f"{style_name}.{layer_name} stroke '{stroke}' is not valid hex"
            )

    @pytest.mark.parametrize("style_name", STYLES.keys())
    def test_stroke_widths_are_positive(self, style_name):
        for layer_name, cfg in STYLES[style_name]["layers"].items():
            assert cfg["width"] > 0, f"{style_name}.{layer_name} width must be positive"

    def test_default_style_has_all_layers(self):
        expected = {"streets_primary", "streets_secondary", "streets_minor",
                    "water", "buildings", "parks", "railway"}
        assert set(STYLES["default"]["layers"].keys()) == expected

    def test_mono_style_has_all_layers(self):
        """Mono should have same layers as default, just in black."""
        assert set(STYLES["mono"]["layers"].keys()) == set(STYLES["default"]["layers"].keys())

    def test_mono_strokes_are_black_or_gray(self):
        for layer_name, cfg in STYLES["mono"]["layers"].items():
            stroke = cfg["stroke"]
            assert stroke in ("#000000", "#444444", "#666666"), (
                f"mono.{layer_name} stroke '{stroke}' should be black/gray"
            )

    def test_minimal_has_fewer_layers_than_default(self):
        assert len(STYLES["minimal"]["layers"]) < len(STYLES["default"]["layers"])

    def test_fill_colors_are_valid_hex(self):
        for style_name, style in STYLES.items():
            for layer_name, cfg in style["layers"].items():
                fill = cfg.get("fill")
                if fill and fill != "none":
                    assert fill.startswith("#") and len(fill) == 7, (
                        f"{style_name}.{layer_name} fill '{fill}' is not valid hex"
                    )


class TestLayerLabels:
    """Validate human-readable layer labels."""

    def test_all_default_layers_have_labels(self):
        for layer_name in STYLES["default"]["layers"]:
            assert layer_name in LAYER_LABELS, f"Missing label for '{layer_name}'"

    def test_labels_are_non_empty_strings(self):
        for name, label in LAYER_LABELS.items():
            assert isinstance(label, str) and len(label) > 0


class TestPaperSizes:
    """Validate paper size definitions."""

    def test_all_expected_sizes_exist(self):
        expected = {"a4", "a4l", "a3", "a3l", "letter"}
        assert set(PAPER_SIZES.keys()) == expected

    def test_dimensions_are_positive(self):
        for name, (w, h) in PAPER_SIZES.items():
            assert w > 0 and h > 0, f"Paper '{name}' has invalid dimensions"

    def test_landscape_wider_than_tall(self):
        for name in ("a4l", "a3l"):
            w, h = PAPER_SIZES[name]
            assert w > h, f"Landscape paper '{name}' should be wider than tall"

    def test_portrait_taller_than_wide(self):
        for name in ("a4", "a3"):
            w, h = PAPER_SIZES[name]
            assert h > w, f"Portrait paper '{name}' should be taller than wide"

    def test_a3_is_larger_than_a4(self):
        a4_area = PAPER_SIZES["a4"][0] * PAPER_SIZES["a4"][1]
        a3_area = PAPER_SIZES["a3"][0] * PAPER_SIZES["a3"][1]
        assert a3_area > a4_area
