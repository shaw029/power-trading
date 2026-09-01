"""Tests for the poster figure export.

A poster panel is printed a metre wide and read from half a metre, so the
export has to produce vectors and a high-resolution raster rather than the
120 DPI the notebook renders inline. These check the contract the notebooks
rely on, without asserting anything about how a figure looks.
"""

import matplotlib
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from research import figexport as poster  # noqa: E402


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


def test_text_is_enlarged_for_export_and_restored_after(tmp_path):
    """A notebook figure carries 9-10pt labels, which vanish at poster size.

    Scaling text rather than the figure keeps the layout the notebook already
    balanced. Restoring afterwards matters because a cell typically shows the
    figure after saving it, and it should not suddenly render at poster type.
    """
    import matplotlib.text

    fig = _figure()
    fig.axes[0].set_title("title")
    before = [t.get_fontsize() for t in fig.findobj(matplotlib.text.Text)]

    poster.save_poster_fig(fig, "demo", tmp_path, text_scale=2.0)
    after = [t.get_fontsize() for t in fig.findobj(matplotlib.text.Text)]
    plt.close(fig)

    assert after == before, "figure left at poster type sizes"


def test_scale_of_one_leaves_a_print_ready_figure_alone(tmp_path):
    fig = _figure()
    written = poster.save_poster_fig(fig, "demo", tmp_path, text_scale=1.0)
    plt.close(fig)
    assert len(written) == 3


def test_legend_anchored_below_the_axes_moves_with_the_text(tmp_path):
    """Clearance under an axis was measured at the original type size.

    A legend at ``bbox_to_anchor=(1.0, -0.32)`` sits just below the tick labels.
    Double the type and the two grow into each other, and the layout engine will
    not intervene because an explicit anchor is an instruction, not a
    preference. The anchor has to move by the same factor — and be put back.
    """
    fig = _figure()
    ax = fig.axes[0]
    ax.legend(["series"], loc="lower right", bbox_to_anchor=(1.0, -0.32))

    poster.save_poster_fig(fig, "demo", tmp_path, text_scale=2.0)
    restored = ax.get_legend().get_bbox_to_anchor()._bbox.bounds
    plt.close(fig)

    assert restored[1] == pytest.approx(-0.32), "anchor left at poster offset"


def test_legend_inside_the_axes_is_left_alone(tmp_path):
    """Only anchors outside the axes collide; an inside one must not move."""
    fig = _figure()
    ax = fig.axes[0]
    ax.legend(["series"], loc="upper left", bbox_to_anchor=(0.02, 0.98))

    poster.save_poster_fig(fig, "demo", tmp_path, text_scale=2.0)
    y = ax.get_legend().get_bbox_to_anchor()._bbox.bounds[1]
    plt.close(fig)

    assert y == pytest.approx(0.98)


def test_notebook_figure_numbers_are_dropped_for_the_poster(tmp_path):
    """A notebook numbers figures in its sequence; a poster in reading order.

    Both are right and they disagree, so a panel titled "Figure 4" sitting under
    a caption reading "Fig 5" makes the reader resolve a contradiction. The
    panel gives up its number, and gets it back afterwards.
    """
    fig = _figure()
    ax = fig.axes[0]
    ax.set_title("Figure 4 — fleet response by system state")

    poster.save_poster_fig(fig, "demo", tmp_path)
    restored = ax.get_title()
    plt.close(fig)

    assert restored == "Figure 4 — fleet response by system state"


def test_a_title_without_a_figure_number_is_untouched(tmp_path):
    fig = _figure()
    ax = fig.axes[0]
    ax.set_title("What a site earns")
    poster.save_poster_fig(fig, "demo", tmp_path)
    assert ax.get_title() == "What a site earns"
    plt.close(fig)


def _dark_modules(svg_text):
    """The set of dark module coordinates an SVG QR actually draws."""
    import re

    return {
        (round(float(x)), round(float(y)))
        for x, y in re.findall(r"M\s*([\d.]+)\s*,?\s*([\d.]+)", svg_text)
    }


def test_qr_encodes_the_url_it_claims_to(tmp_path):
    """The whole reason the QR is generated rather than committed.

    Nobody proofreads a QR code. This rebuilds the expected matrix from the
    URL and compares it against what was written, so a silently wrong link
    fails here rather than in someone's phone at the poster board.
    """
    qrcode = pytest.importorskip("qrcode")
    url = "https://example.invalid/dashboard"
    svg, png = poster.save_qr(url=url, name="qr", directory=tmp_path)

    code = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_Q,
        border=poster.QR_BORDER,
    )
    code.add_data(url)
    code.make(fit=True)
    expected = {
        (x + poster.QR_BORDER, y + poster.QR_BORDER)
        for y, row in enumerate(code.modules)
        for x, dark in enumerate(row)
        if dark
    }

    assert _dark_modules(svg.read_text()) == expected
    assert png.exists()


def test_qr_for_a_different_url_is_a_different_code(tmp_path):
    """Guards against the encoder being handed a constant by accident."""
    pytest.importorskip("qrcode")
    a, _ = poster.save_qr(url="https://example.invalid/a", name="a",
                          directory=tmp_path)
    b, _ = poster.save_qr(url="https://example.invalid/b", name="b",
                          directory=tmp_path)
    assert _dark_modules(a.read_text()) != _dark_modules(b.read_text())


def test_qr_keeps_the_quiet_zone_the_spec_requires(tmp_path):
    """Scanners need >= 4 modules of margin to find the code on a busy page."""
    pytest.importorskip("qrcode")
    svg, _ = poster.save_qr(url="https://example.invalid", name="qr",
                            directory=tmp_path)
    modules = _dark_modules(svg.read_text())
    assert min(x for x, _ in modules) >= poster.QR_BORDER
    assert min(y for _, y in modules) >= poster.QR_BORDER
    assert poster.QR_BORDER >= 4
