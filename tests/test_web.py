"""Tests for Flask web UI routes."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from web import app
from cityplot import STYLES, PAPER_SIZES


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestIndexRoute:
    """Test the index route."""

    def test_index_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_index_contains_styles(self, client):
        resp = client.get("/")
        html = resp.data.decode()
        for style_name in STYLES:
            assert style_name in html

    def test_index_contains_paper_sizes(self, client):
        resp = client.get("/")
        html = resp.data.decode()
        for paper in PAPER_SIZES:
            assert paper in html


class TestGenerateRoute:
    """Test the /generate POST endpoint."""

    @patch("web.generate_svg")
    def test_generate_success(self, mock_gen, client):
        """Test successful SVG generation."""
        def side_effect(**kwargs):
            # Create a dummy file at the output path
            Path(kwargs["output"]).write_text("<svg></svg>")

        mock_gen.side_effect = side_effect
        resp = client.post("/generate", json={
            "lat": 53.07,
            "lon": 8.80,
            "radius": 2000,
            "style": "default",
            "paper": "a3l",
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert "file" in data
        assert "size_kb" in data
        # Clean up
        if os.path.exists(data["file"]):
            os.unlink(data["file"])

    @patch("web.generate_svg")
    def test_generate_with_all_options(self, mock_gen, client):
        """Test generation with all optional parameters."""
        def side_effect(**kwargs):
            Path(kwargs["output"]).write_text("<svg></svg>")

        mock_gen.side_effect = side_effect
        resp = client.post("/generate", json={
            "lat": 53.07,
            "lon": 8.80,
            "radius": 3000,
            "style": "minimal",
            "paper": "a4",
            "circle": True,
            "margin_top": 10,
            "margin_right": 20,
            "margin_bottom": 10,
            "margin_left": 20,
            "layers": ["water", "buildings"],
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        # Verify args passed to generate_svg
        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["radius"] == 3000
        assert call_kwargs["style_name"] == "minimal"
        assert call_kwargs["paper"] == "a4"
        assert call_kwargs["clip_circle"] is True
        assert call_kwargs["margins"] == (10, 20, 10, 20)
        assert call_kwargs["layer_filter"] == ["water", "buildings"]
        if os.path.exists(data["file"]):
            os.unlink(data["file"])

    @patch("web.generate_svg", side_effect=Exception("Test error"))
    def test_generate_error_returns_500(self, mock_gen, client):
        resp = client.post("/generate", json={
            "lat": 53.07,
            "lon": 8.80,
        })
        data = resp.get_json()
        assert resp.status_code == 500
        assert data["ok"] is False
        assert "error" in data

    @patch("web.generate_svg")
    def test_generate_default_values(self, mock_gen, client):
        """Test that defaults are applied when optional fields missing."""
        def side_effect(**kwargs):
            Path(kwargs["output"]).write_text("<svg></svg>")

        mock_gen.side_effect = side_effect
        resp = client.post("/generate", json={
            "lat": 53.07,
            "lon": 8.80,
        })
        data = resp.get_json()
        assert resp.status_code == 200
        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["radius"] == 1000
        assert call_kwargs["style_name"] == "default"
        assert call_kwargs["paper"] == "a3l"
        assert call_kwargs["clip_circle"] is False
        assert call_kwargs["margins"] == (15, 15, 15, 15)
        if os.path.exists(data["file"]):
            os.unlink(data["file"])


class TestDownloadRoute:
    """Test the /download endpoint."""

    def test_download_valid_file(self, client):
        fd, path = tempfile.mkstemp(suffix=".svg")
        os.write(fd, b"<svg></svg>")
        os.close(fd)
        try:
            resp = client.get(f"/download?file={path}")
            assert resp.status_code == 200
            assert resp.mimetype == "image/svg+xml"
        finally:
            os.unlink(path)

    def test_download_missing_file_param(self, client):
        resp = client.get("/download")
        assert resp.status_code == 400

    def test_download_invalid_path(self, client):
        resp = client.get("/download?file=/etc/passwd")
        assert resp.status_code == 400

    def test_download_nonexistent_file(self, client):
        path = os.path.join(tempfile.gettempdir(), "nonexistent_12345.svg")
        resp = client.get(f"/download?file={path}")
        assert resp.status_code == 404
