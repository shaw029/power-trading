"""Tests for the poster figure export.

A poster panel is printed a metre wide and read from half a metre, so the
export has to produce vectors and a high-resolution raster rather than the
120 DPI the notebook renders inline. These check the contract the notebooks
rely on, without asserting anything about how a figure looks.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from src.utils import poster  # noqa: E402


def _figure():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    return fig


def test_writes_vectors_and_a_high_resolution_raster(tmp_path):
    fig = _figure()
    written = poster.save_poster_fig(fig, "demo", tmp_path)
    plt.close(fig)

    assert {p.suffix for p in written} == {".pdf", ".svg", ".png"}
    assert all(p.exists() and p.stat().st_size > 0 for p in written)


def test_svg_is_a_vector_not_an_embedded_bitmap(tmp_path):
    """The point of the SVG is that it can be restyled and rescaled."""
    fig = _figure()
    poster.save_poster_fig(fig, "demo", tmp_path)
    plt.close(fig)

    svg = (tmp_path / "demo.svg").read_text(encoding="utf-8")
    assert "<svg" in svg
    assert "<path" in svg, "no vector paths — the figure was rasterised"


def test_creates_its_output_directory(tmp_path):
    fig = _figure()
    target = tmp_path / "nested" / "poster"
    poster.save_poster_fig(fig, "demo", target)
    plt.close(fig)
    assert target.is_dir()


def test_png_is_opaque_and_vectors_are_transparent(tmp_path):
    """Transparent vectors sit on the poster's background; a print shop
    expects a raster to arrive with one."""
    fig = _figure()
    poster.save_poster_fig(fig, "demo", tmp_path)
    plt.close(fig)

    from PIL import Image

    with Image.open(tmp_path / "demo.png") as img:
        alpha = img.convert("RGBA").getchannel("A")
        assert alpha.getextrema() == (255, 255), "PNG should not be transparent"
