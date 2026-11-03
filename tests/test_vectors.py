import io

import cairosvg
import numpy as np
import pytest
from PIL import Image

from stock_studio.metadata.compliance import ComplianceScanner
from stock_studio.producers import code_vectors as cv
from stock_studio.producers.vector_icons import ICON_SETS, ICONS


@pytest.mark.parametrize("kind", cv.PATTERN_KINDS)
def test_pattern_tiles_are_seamless(kind):
    T = 400
    tile = cv.pattern_tile_svg(kind, cv.VStyle("monsoon", "filled"), seed=7, T=T)
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{T}" height="{T}">{tile}</svg>'
    a = np.asarray(Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg.encode()))).convert("RGB")).astype(int)
    # the wrap seam (last column -> first column) should look like any other neighbouring column pair
    # (compared along the same axis, since stripes differ a lot between axes)
    inner_x = np.abs(np.diff(a, axis=1)).mean()
    inner_y = np.abs(np.diff(a, axis=0)).mean()
    seam_x = np.abs(a[:, -1] - a[:, 0]).mean()
    seam_y = np.abs(a[-1] - a[0]).mean()
    assert seam_x <= inner_x * 3 + 2, (kind, "vertical seam", inner_x, seam_x)
    assert seam_y <= inner_y * 3 + 2, (kind, "horizontal seam", inner_y, seam_y)


def test_every_icon_in_every_set_exists():
    for s in ICON_SETS.values():
        assert all(name in ICONS for name in s["icons"])


def test_generated_assets_have_svg_eps_and_large_preview(settings, store):
    made = cv.make_icon_sets(settings, store, sets=["business"], seed=1)
    made += cv.make_patterns(settings, store, count=1, seed=1)
    made += cv.make_infographics(settings, store, count=1, seed=1)
    for a in made:
        assert open(a.path).read().startswith("<?xml")
        assert open(a.qc["eps"], "rb").read(20).startswith(b"%!PS-Adobe")
        with Image.open(a.preview_path) as im:
            assert im.width * im.height >= 4_000_000          # Adobe's 4 MP minimum
    # descriptions feed the metadata agent, so they must be compliance-clean
    s = ComplianceScanner()
    assert all(s.scan_text(a.prompt).ok for a in made)


def test_vector_generation_is_idempotent(settings, store):
    a = cv.make_icon_sets(settings, store, sets=["food"], seed=3)
    b = cv.make_icon_sets(settings, store, sets=["food"], seed=3)
    assert [x.id for x in a] == [x.id for x in b]
    assert len(store.list()) == 1
