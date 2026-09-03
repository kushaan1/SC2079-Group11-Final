import os

from PIL import Image

from simulator import arena_view as av
from simulator.arena import load
from simulator.snapshot import render, write

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")


def test_render_has_the_arena_size_plus_margin():
    image = render(load(os.path.join(TESTDATA, "02-four-obstacles.json")), frame=None, source_name=None, scale=2.0)
    assert image.size == (400 + av.AXIS_MARGIN_PX, 400 + av.AXIS_MARGIN_PX)
    # start zone corner is tinted, an obstacle cell is ink
    assert image.getpixel((5, 395)) != image.getpixel((5, 5))
    assert image.getpixel((103, 203)) == (0x1B, 0x2A, 0x2F)   # inside obstacle 11's body, clear of its label


def test_write_creates_a_png(tmp_path):
    out = tmp_path / "shot.png"
    write(os.path.join(TESTDATA, "01-single-obstacle.json"), out, frame=0, scale=2.0)
    assert out.exists() and Image.open(out).format == "PNG"
