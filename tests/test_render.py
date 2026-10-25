"""Smoke tests on the example event, without a DisplayLink Plus template folder (board slides are skipped)."""

from pathlib import Path

import av
import pytest
import zxingcpp
from PIL import Image

from loopgen import export_loop, export_pngs, load_event, render_slide, run_checks
from loopgen.loops import existing_exports
from loopgen.slides import BAR, MARGIN, Renderer
from loopgen.uploads import prepare_upload, shrink

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "dual-meet" / "event.yaml"


@pytest.fixture(name="event")
def fixture_event():
    return load_event(EXAMPLE)


def test_cards_and_images_render_at_board_size(event):
    for loop in event.loops:
        for i, slide in enumerate(loop.slides):
            if slide.type == "board" or slide.props.get("background"):
                continue
            assert render_slide(event, loop, i).size == (320, 176)


def test_one_card_loop_exports_ten_seconds_of_wmv2(event, tmp_path):
    (wmv,) = export_loop(event, event.loop("Raffle"), tmp_path)
    with av.open(str(wmv)) as container:
        stream = container.streams.video[0]
        assert stream.codec_context.name == "wmv2"
        assert (stream.width, stream.height) == (320, 176)
        assert round(float(container.duration / av.time_base)) == 10


def test_a_loop_name_with_slashes_and_colons_still_exports(tmp_path):
    event_file = tmp_path / "names.yaml"
    event_file.write_text(
        "event: Names\nloops:\n  - name: 'Raffle: 10/12'\n    slides:\n"
        "      - card: {layout: stack, lines: [{text: RAFFLE, size: L}]}\n",
        encoding="utf-8",
    )
    event = load_event(event_file)
    loop = event.loop("Raffle: 10/12")
    wmv, mp4 = export_loop(event, loop, tmp_path / "out", preview_mp4=True)
    assert (wmv.name, mp4.name) == ("Raffle- 10-12.wmv", "Raffle- 10-12 (preview).mp4") and wmv.is_file()
    assert existing_exports(loop, tmp_path / "out", preview_mp4=True) == [wmv, mp4]  # the replace check finds them


def test_qr_slide_decodes(tmp_path):
    event_file = tmp_path / "qr.yaml"
    event_file.write_text(
        "event: QR test\nloops:\n  - name: QR\n    slides:\n"
        "      - qr: {url: 'https://example.com/program', heading: [MEET, PROGRAM]}\n",
        encoding="utf-8",
    )
    event = load_event(event_file)
    img = render_slide(event, event.loops[0], 0).resize((960, 528), Image.Resampling.NEAREST)
    assert "https://example.com/program" in [r.text for r in zxingcpp.read_barcodes(img)]
    assert not [i for i in run_checks(event) if i.level == "error"]


def test_missing_board_template_is_an_error(event, tmp_path):
    event.templates = tmp_path  # an empty template folder
    errors = [i for i in run_checks(event, [event.loop("Welcome loop")]) if i.level == "error"]
    assert any("template" in e.message for e in errors)


def test_pictures_shrink_to_2048_and_keep_transparency(tmp_path):
    big = tmp_path / "photo.jpg"
    Image.new("RGB", (4000, 3000), "navy").save(big)
    assert shrink(Image.open(big)).size == (2048, 1536)
    logo = tmp_path / "logo.png"
    img = Image.new("RGBA", (3000, 3000), (0, 0, 0, 0))
    img.paste((200, 0, 0, 255), (500, 500, 2500, 2500))
    img.save(logo)
    assert prepare_upload(logo, tmp_path / "out").suffix == ".png"
    assert prepare_upload(big, tmp_path / "out").suffix == ".jpg"


def test_png_export_skips_moving_slides(tmp_path):
    event_file = tmp_path / "png.yaml"
    event_file.write_text(
        "event: PNG test\nloops:\n  - name: Mixed\n    slides:\n"
        "      - countdown: {label: WARM-UP, length: '0:05'}\n"
        "      - card: {layout: stack, lines: [{text: DIVING, size: L}]}\n",
        encoding="utf-8",
    )
    event = load_event(event_file)
    (png,), skipped = export_pngs(event, event.loops[0], tmp_path / "out")
    assert [n for n, _ in skipped] == [1]
    assert Image.open(png).size == (320, 176) and png.name == "Mixed 02 - DIVING.png"


def test_switching_layouts_never_breaks_a_card(tmp_path):
    """Every layout draws any card's lines; what a layout can't show is a warning, not a failure."""
    lines = "[{text: DIVING, size: L}, {text: Quiet please}, {text: during each dive}, {text: Cheer!}]"
    event_file = tmp_path / "layouts.yaml"
    event_file.write_text(
        "event: Layouts\nloops:\n  - name: L\n    slides:\n"
        + "".join(
            f"      - card: {{layout: {lay}, picture: none, lines: {lines}}}\n"
            for lay in ("stack", "logo-center", "text-qr", "banner", "text-picture")
        ),
        encoding="utf-8",
    )
    event = load_event(event_file)
    for i in range(5):
        assert render_slide(event, event.loops[0], i).size == (320, 176)
    found = [(i.slide, i.level, i.message) for i in run_checks(event)]
    assert any(s == 3 and "needs a QR link" in m for s, _, m in found)  # Text + QR without a link: drawn, flagged
    assert any(s == 3 and lvl == "error" for s, lvl, _ in found)  # ...and export stays blocked until it has one
    assert any(s == 4 and "kept but hidden" in m for s, _, m in found)  # Banner hides lines 3-4 without losing them
    assert any(s == 5 and "needs a picture" in m for s, _, m in found)  # Text + picture without one: drawn, flagged


def test_text_qr_can_show_its_link_and_warns_when_it_is_too_long(tmp_path):
    long = "https://example.org/donate?campaign=2026-swim-a-thon&team=riverside&source=scoreboard"
    event_file = tmp_path / "link.yaml"
    event_file.write_text(
        "event: Link\nloops:\n  - name: L\n    slides:\n"
        "      - card: {layout: text-qr, qr: 'https://example.org', show_url: true, lines: [{text: DONATE, size: L}]}\n"
        f"      - card: {{layout: text-qr, qr: '{long}', show_url: true, lines: [{{text: DONATE, size: L}}]}}\n",
        encoding="utf-8",
    )
    event = load_event(event_file)
    found = [(i.slide, i.level, i.message) for i in run_checks(event)]
    assert not [f for f in found if f[0] == 1]  # a short link fits under the code, and the code still scans
    assert [lvl for s, lvl, m in found if s == 2 and "too long to show under the QR" in m] == ["warning"]


def test_crawl_separator_uses_the_chosen_theme_colour(tmp_path):
    event_file = tmp_path / "sep.yaml"
    event_file.write_text(
        "event: Sep\nloops:\n  - name: L\n    slides:\n"
        "      - crawl: {length: '0:20', separator: '■', separator_color: accent, segments: [{text: 'GO '}]}\n",
        encoding="utf-8",
    )
    event = load_event(event_file)
    accent = (0xF0, 0xC8, 0x78)
    frames = [render_slide(event, event.loops[0], 0, t / 10) for t in range(0, 100, 5)]
    assert any(accent in (c for _, c in f.convert("RGB").getcolors(10000) or []) for f in frames)


def test_live_field_codes_are_described_in_plain_words():
    from loopgen.tpl import describe_fields  # pylint: disable=import-outside-toplevel

    assert describe_fields(["MM_SW_AF", "MM_SW_NM", "SCBD_SW_EV"]) == "teams, swimmer names, times and places"
    assert describe_fields(["SCBD_DV_AWD", "MM_DV_NM"]) == "diving scores, diver name"
    assert describe_fields([]) == ""


def test_a_template_is_found_by_name_under_a_parent_folder(tmp_path):
    (tmp_path / "Library" / "Riverside").mkdir(parents=True)
    tpl_file = tmp_path / "Library" / "Riverside" / "Welcome.tpl"
    tpl_file.write_bytes(b"x")
    event_file = tmp_path / "e.yaml"
    event_file.write_text(
        f"event: T\ntemplates: {tmp_path / 'Library'}\nloops:\n  - name: L\n    slides: [card: {{}}]\n",
        encoding="utf-8",
    )
    event = load_event(event_file)
    assert event.template("Welcome.tpl") == tpl_file  # one level down, found by name
    assert event.template("Missing.tpl") == tmp_path / "Library" / "Missing.tpl"  # not found: reported as missing


def test_fit_can_show_any_shaped_part_of_a_picture(tmp_path):
    pic = Image.new("RGB", (1000, 1000), "white")
    pic.paste((0, 0, 255), (0, 0, 500, 1000))  # left half blue
    pic.save(tmp_path / "pic.png")
    event_file = tmp_path / "e.yaml"
    event_file.write_text(
        "event: T\nloops:\n  - name: L\n    slides:\n"
        "      - image: {file: pic.png, fit: fit, crop: [0, 0, 0.5, 1]}\n"  # a tall strip: the blue half
        "      - image: {file: pic.png, fit: fit, crop: [0, 0, 0.05, 0.05]}\n",  # tiny: blocky
        encoding="utf-8",
    )
    event = load_event(event_file)
    img = render_slide(event, event.loops[0], 0).convert("RGB")
    assert img.getpixel((160, 88)) == (0, 0, 255)  # the strip, fitted in the middle, undistorted
    assert img.getpixel((5, 88)) == (0, 0, 0)  # background colour either side
    found = [(i.slide, i.message) for i in run_checks(event)]
    assert any(s == 2 and "blocky" in m for s, m in found) and not any(s == 1 for s, _ in found)


def test_pan_follows_the_arrow_in_fill_and_fit(tmp_path):
    pic = Image.new("RGB", (2000, 1000), "white")
    pic.paste((255, 0, 0), (0, 0, 500, 1000))  # red on the left
    pic.paste((0, 0, 255), (1500, 0, 2000, 1000))  # blue on the right
    pic.save(tmp_path / "pic.png")
    event_file = tmp_path / "e.yaml"
    event_file.write_text(
        "event: T\nloops:\n  - name: L\n    hold: 4\n    slides:\n"
        "      - image: {file: pic.png, zoom: 3, focus: [0.1, 0.5], pan: {to: [0.9, 0.5]}}\n"
        "      - image: {file: pic.png, fit: fit, crop: [0, 0.2, 0.2, 0.8], pan: {to: [0.9, 0.5]}}\n",
        encoding="utf-8",
    )
    event = load_event(event_file)
    for n in (0, 1):
        first = render_slide(event, event.loops[0], n, 0).convert("RGB")
        last = render_slide(event, event.loops[0], n, 3.99).convert("RGB")
        assert first.getpixel((160, 88)) == (255, 0, 0) and last.getpixel((160, 88)) == (0, 0, 255)
    pngs, skipped = export_pngs(event, event.loops[0], tmp_path / "out")
    assert not pngs and [s for s, _ in skipped] == [1, 2]  # a pan moves, so it's video only


def test_box_to_value_to_renderer_crop_matches_to_the_pixel():
    """The editor turns a Fill box into focus and zoom; the renderer must crop that same box back."""
    from loopgen.event import Event  # pylint: disable=import-outside-toplevel

    r = Renderer(Event("t", Path("x.yaml"), 320, 176, {}, [], Path(".")))
    aspect = 320 / 176
    for iw, ih in ((1179, 1521), (2048, 1365), (320, 176), (800, 800)):
        src = Image.new("RGB", (iw, ih))
        full_w = ih * aspect if iw / ih > aspect else iw
        for zoom in (1, 1.58, 2.3, 3):
            w = full_w / zoom
            h = w / aspect
            for fx, fy in ((0, 0), (0.37, 0.61), (1, 1)):
                x, y = (iw - w) * fx, (ih - h) * fy
                focus = ((x + w / 2) / iw, (y + h / 2) / ih)
                x0, y0, x1, _ = r._crop(src, *focus, full_w / w)  # pylint: disable=protected-access
                assert abs(x0 - x) < 1e-6 and abs(y0 - y) < 1e-6 and abs((x1 - x0) - w) < 1e-6


def test_transparent_parts_of_a_template_are_black_on_the_board(tmp_path, monkeypatch):
    """Regression: a template with a transparent background lost its alpha when flattened, so soft edges kept
    their raw colour (often white) and lettering on the Sections boards turned into blocks."""
    from loopgen import tpl  # pylint: disable=import-outside-toplevel
    from loopgen.event import Event  # pylint: disable=import-outside-toplevel

    edge = Image.new("RGBA", (320, 176), (0, 0, 0, 0))
    edge.putpixel((10, 10), (255, 255, 255, 64))  # a soft, mostly transparent white edge pixel
    monkeypatch.setattr(tpl.Reader, "__init__", lambda self, data: None)
    monkeypatch.setattr(tpl.Reader, "parse", lambda self: None)
    monkeypatch.setattr(tpl.Renderer, "render", lambda self, root: (edge, {"items": []}))
    (tmp_path / "Clear.tpl").write_bytes(b"x")
    board = Renderer(Event("t", tmp_path / "e.yaml", 320, 176, {}, [], tmp_path)).board("Clear.tpl")
    assert board.getpixel((10, 10)) == (64, 64, 64) and board.getpixel((100, 100)) == (0, 0, 0)


def test_lanes_slide_draws_every_lane_and_flags_a_missing_logo(tmp_path):
    Image.new("RGBA", (200, 150), (0, 80, 200, 255)).save(tmp_path / "pine-ridge.png")
    event_file = tmp_path / "lanes.yaml"
    event_file.write_text(
        "event: L\nloops:\n  - name: L\n    slides:\n"
        "      - lanes: {title: Welcome!, count: 10, first: 0,\n"
        "                lanes: [{name: PINE RIDGE, logo: pine-ridge.png}, {name: 'NORTH|HARBOR'}]}\n"
        "      - lanes: {count: 4, lanes: [{name: PARK, logo: missing.png}]}\n",
        encoding="utf-8",
    )
    event = load_event(event_file)
    img = render_slide(event, event.loops[0], 0).convert("RGB")
    assert img.size == (320, 176)
    assert (0, 80, 200) in [c for _, c in img.getcolors(100000)]  # the logo is on the board
    errors = [i for i in run_checks(event) if i.level == "error"]
    assert [e.slide for e in errors] == [2] and "logo" in errors[0].message


def test_a_team_name_sits_under_its_own_lane_label(tmp_path):
    """On two rows, a name at the bottom of its cell reads as the lane below it; it belongs under its own label."""
    event_file = tmp_path / "lanes.yaml"
    event_file.write_text(
        "event: L\ntheme: {text: '#FFFFFF', accent: '#00FF00', primary: '#FF0000', background: '#000000'}\n"
        "loops:\n  - name: L\n    slides:\n"
        "      - lanes: {title: Welcome!, first: 1, last: 8, lanes: [{name: HASTINGS}]}\n",
        encoding="utf-8",
    )
    event = load_event(event_file)
    img = render_slide(event, event.loops[0], 0).convert("RGB")
    cell = img.crop((0, 0, img.width // 4, img.height))  # lane 1's column, with lane 5 below it
    pixels = list(cell.get_flattened_data())  # Pillow 13+: getdata is going in Pillow 14

    def rows(test):
        return sorted({i // cell.width for i, colour in enumerate(pixels) if test(colour)})

    green = rows(lambda c: c[1] > 200 and c[0] < 80 and c[2] < 80)  # the LANE 1 and LANE 5 labels
    white = rows(lambda c: min(c) > 220)  # the team name, and the title above the labels
    lane5 = next(y for a, y in zip(green, green[1:]) if y - a > 10)  # where the second label band starts
    name = [y for y in white if green[0] <= y < lane5]
    assert name and name[-1] - green[0] < (lane5 - green[0]) / 2  # in the top half of lane 1's cell


def test_lanes_split_into_pages_and_loops_with_a_countdown_end_cleanly(tmp_path):
    event_file = tmp_path / "pages.yaml"
    event_file.write_text(
        "event: P\nloops:\n  - name: Welcome\n    hold: 2\n    fade: 0\n    repeat: false\n    slides:\n"
        "      - lanes: {title: Hi, first: 1, last: 8, per_page: 4, lanes: [{name: ONE}, {}, {}, {}, {name: FIVE}]}\n"
        "      - card: {lines: [{text: HELLO}]}\n"
        "  - name: Warm-up\n    slides:\n      - countdown: {length: '0:02'}\n      - card: {lines: [{text: BACK}]}\n",
        encoding="utf-8",
    )
    event = load_event(event_file)
    welcome, warmup = event.loops
    assert welcome.repeat and not warmup.repeat  # older files' repeat setting is ignored
    clip = Renderer(event).render(welcome.slides[0], 2)
    assert clip.frames == 2 * 2 * 30 + 15  # two pages of 2 s, with a half-second blend between them
    page1, page2 = render_slide(event, welcome, 0), render_slide(event, welcome, 0, at=3)
    assert page1.tobytes() != page2.tobytes()
    assert not [i for i in run_checks(event) if "repeat" in i.message]


def test_a_placeholder_team_name_blocks_an_export_until_it_is_typed_over(tmp_path):
    event_file = tmp_path / "placeholder.yaml"
    event_file.write_text(
        "event: P\nloops:\n  - name: Welcome loop\n    slides:\n"
        "      - card: {lines: [{text: Welcome}, {text: VISITING TEAM}]}\n"
        "      - card: {lines: [{text: team name}]}\n"
        "      - card: {lines: [{text: Welcome visiting teams}, {text: HASTINGS}]}\n",
        encoding="utf-8",
    )
    errors = [i for i in run_checks(load_event(event_file)) if i.level == "error"]
    assert [(e.slide, e.message) for e in errors] == [
        (1, "still says “VISITING TEAM”: type the team’s name over it"),
        (2, "still says “team name”: type the team’s name over it"),
    ]


def _yellow(img):
    """The bounding box of the test picture's yellow on the board (the text is blue), or None."""
    mask = Image.new("L", img.size, 0)
    pixels = img.convert("RGB").get_flattened_data()
    mask.putdata([255 if (r > 200 and g > 180 and b < 100) else 0 for r, g, b in pixels])
    return mask.getbbox()


def test_a_card_picture_sits_where_it_is_placed_in_any_layout(tmp_path):
    (tmp_path / "assets").mkdir()
    Image.new("RGBA", (60, 60), (255, 220, 0, 255)).save(tmp_path / "assets" / "duck.png")
    lines = "[{text: CHUCK A DUCK, size: L}, {text: Practice}]"
    slides = [
        "{layout: stack, picture: assets/duck.png, picture_place: above, bars: none, lines: %s}",
        "{layout: stack, picture: assets/duck.png, picture_place: below, bars: none, lines: %s}",
        "{layout: text-picture, picture: assets/duck.png, bars: none, lines: %s}",
        "{layout: text-picture, picture: assets/duck.png, picture_side: left, bars: none, lines: %s}",
        "{layout: text-qr, qr: 'https://example.org/give', picture: assets/duck.png, bars: none, lines: %s}",
        "{layout: stack, bars: none, lines: %s}",  # no picture key: a stack card shows none, as before
    ]
    event_file = tmp_path / "event.yaml"
    event_file.write_text(
        "event: Places\ntheme: {text: '#0000FF', muted: '#0000FF', primary: '#0000FF', background: '#000000'}\n"
        "loops:\n  - name: P\n    slides:\n" + "".join(f"      - card: {s % lines}\n" for s in slides),
        encoding="utf-8",
    )
    event = load_event(event_file)
    above, below, right, left, beside_qr, none = (_yellow(render_slide(event, event.loops[0], i)) for i in range(6))
    assert above[1] < 40 and below[3] > 136  # top of the board / bottom of the board
    assert left[2] < 160 < right[0]  # beside the lines, on the side asked for
    assert right[3] - right[1] > 100  # Text + picture's picture is big: most of the board's height
    assert beside_qr[2] < 320 - 100  # in the lines' column, left of the QR code
    assert none is None
    assert not [i for i in run_checks(event) if i.level == "error"]


def test_extra_pictures_go_over_any_slide_where_placed(tmp_path):
    (tmp_path / "assets").mkdir()
    Image.new("RGBA", (40, 20), (255, 220, 0, 255)).save(tmp_path / "assets" / "badge.png")
    event_file = tmp_path / "event.yaml"
    event_file.write_text(
        "event: Extras\ntheme: {text: '#0000FF', muted: '#0000FF', primary: '#0000FF', background: '#000000'}\n"
        "loops:\n  - name: X\n    slides:\n"
        "      - card: {id: c, bars: none, lines: [{text: HI}], badges: ["
        "{file: assets/badge.png, place: top-left, size: S}, {file: assets/badge.png, place: bottom-right, size: L}]}\n"
        "      - countdown: {length: '0:03', badges: [{file: assets/badge.png, place: center}]}\n"
        "      - card: {ref: c}\n"
        "      - card: {lines: [{text: HI}], badges: [{file: assets/missing.png}]}\n",
        encoding="utf-8",
    )
    event = load_event(event_file)
    loop = event.loops[0]
    card = render_slide(event, loop, 0).convert("RGB")
    assert card.getpixel((6 + 10, 6 + 5))[:2] == (255, 220)  # S: 24 px tall, 6 px in from the top left
    assert card.getpixel((320 - 6 - 50, 176 - 6 - 13))[:2] == (255, 220)  # L: 52 px tall (104 wide), bottom right
    assert card.getpixel((160, 88))[:2] != (255, 220)
    for at in (0, 1.0, 2.5):  # on every frame of a moving slide
        assert render_slide(event, loop, 1, at=at).convert("RGB").getpixel((160, 88))[:2] == (255, 220)
    assert render_slide(event, loop, 2).tobytes() == render_slide(event, loop, 0).tobytes()  # a linked slide too
    found = [(i.slide, i.message) for i in run_checks(event)]
    assert any(s == 4 and "extra picture not found" in m for s, m in found)
    assert render_slide(event, loop, 3).size == (320, 176)  # drawn without it


def test_a_qr_slide_without_a_full_link_shows_where_its_code_will_go(tmp_path):
    event_file = tmp_path / "qr.yaml"
    event_file.write_text(
        "event: Q\nloops:\n  - name: L\n    slides:\n      - qr: {url: 'https://', heading: [HEAT, SHEET]}\n"
        "      - qr: {url: 'https://example.org/heat-sheet', heading: [HEAT, SHEET]}\n",
        encoding="utf-8",
    )
    event = load_event(event_file)
    unfinished, finished = (render_slide(event, event.loops[0], i).convert("RGB") for i in (0, 1))
    assert not zxingcpp.read_barcodes(unfinished)  # the placeholder is no code at all, so nothing scans to "https://"
    assert [b.text for b in zxingcpp.read_barcodes(finished)] == ["https://example.org/heat-sheet"]
    errors = [i for i in run_checks(event) if i.level == "error"]
    assert [e.slide for e in errors] == [1]  # and the export still stops until the link is there


@pytest.mark.parametrize("size", [(30, 240), (3, 100), (4, 176), (200, 60), (1000, 1)])
@pytest.mark.parametrize("bars", ["both", "top", "bottom", "none"])
def test_a_text_picture_card_keeps_its_picture_clear_of_the_bars(tmp_path, size, bars):
    """Round 5: a badge seemed to touch the accent bar. Narrow pictures could still grow past their room."""
    (tmp_path / "assets").mkdir()
    Image.new("RGBA", size, (255, 220, 0, 255)).save(tmp_path / "assets" / "pic.png")
    event_file = tmp_path / "event.yaml"
    event_file.write_text(
        "event: Clear\ntheme: {text: '#0000FF', muted: '#0000FF', primary: '#0000FF', background: '#000000'}\n"
        "loops:\n  - name: P\n    slides:\n"
        f"      - card: {{layout: text-picture, picture: assets/pic.png, bars: {bars}, lines: [{{text: TIGERS}}]}}\n",
        encoding="utf-8",
    )
    event = load_event(event_file)
    img = render_slide(event, event.loops[0], 0)
    box = _yellow(img)
    assert box is not None  # drawn, even a 1000 x 1 strip (kept at least a pixel high)
    top = BAR + MARGIN if bars in ("top", "both") else MARGIN
    bottom = img.height - (BAR + MARGIN if bars in ("bottom", "both") else MARGIN)
    assert box[1] >= top and box[3] <= bottom and box[0] >= MARGIN and box[2] <= img.width - MARGIN
