"""Draw each slide type at board size. A slide renders to a Clip: its frames as
(image, repeat count) runs, plus its first and last frame for crossfades."""

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageOps

from . import draw, tpl, uploads

SIZES = {"S": 16, "M": 22, "L": 34}
MARGIN = 8  # side margin every fitted line keeps
OUTLINE = 2  # outlined text: px of primary colour around it
BAR = 4  # accent bar thickness
MAX_IMAGE_ZOOM = 3  # enlarge a picture more than this and the board shows its pixels
LINK_COLOURS = ("muted", "text", "accent", "primary")
LINK_BAND = 14  # px under a Text + QR code for its link
LINK_OVERHANG = 10  # how far the link may run past each side of the code
MAX_LANES = 10  # a lanes slide shows up to ten lanes, numbered no higher than 10
PAGE_FADE = 0.5  # seconds of crossfade between the pages of a lanes slide
BADGE_SIZES = {"S": 24, "M": 36, "L": 52, "XL": 80}  # an extra picture's height on the board, px
BADGE_INSET = 6  # px from the board's edges
PLACES = ("top-left", "top", "top-right", "left", "center", "right", "bottom-left", "bottom", "bottom-right")


def lane_range(p):
    """(first, last, per_page) for a lanes slide. Older slides stored a lane count instead of the last lane."""
    first = max(0, min(int(p.get("first", 1)), MAX_LANES))
    if p.get("last") is not None:
        last = int(p["last"])
    else:
        last = first + int(p.get("count") or len(p.get("lanes") or []) or 8) - 1
    last = max(first, min(last, MAX_LANES, first + MAX_LANES - 1))
    per_page = int(p.get("per_page") or 0) or last - first + 1
    return first, last, max(1, min(per_page, last - first + 1))


BANNER_LINES = 2  # a banner is one big line and one small one
CRAWL_SPEED = {"slow": 2, "medium": 3, "fast": 4}  # board px per frame at 30 fps


class MissingAsset(FileNotFoundError):
    """An image, logo or template the slide names isn't there."""


@dataclass
class Clip:
    """A slide's frames for a video, drawn as they're needed, with its first and last for the fades."""

    runs: Callable  # () -> iterator of (Image, count)
    first: Image.Image
    last: Image.Image
    frames: int
    timed: bool
    seek: Callable = None  # frame index -> image, so a preview can jump to any moment without drawing the rest


def still(img, frames):
    return Clip(lambda: iter([(img, frames)]), img, img, frames, False)


def with_badges(clip, badges):
    """The clip with its extra pictures pasted on every frame, in order (a still is pasted once, not per frame)."""
    last = [None, None]

    def put(img):
        if img is not last[0]:
            out = img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img.copy()
            for pic, at in badges:
                out.paste(pic, at, pic)
            last[:] = [img, out]  # holding img keeps its id from being reused by a new frame
        return last[1]

    seek = clip.seek and (lambda k: put(clip.seek(k)))
    return Clip(
        lambda: ((put(img), n) for img, n in clip.runs()),
        put(clip.first),
        put(clip.last),
        clip.frames,
        clip.timed,
        seek,
    )


def seconds(value):
    """'10:00', '0:30', 90 or '90' -> seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    parts = [float(p) for p in str(value).split(":")]
    return sum(p * 60**i for i, p in enumerate(reversed(parts)))


class Renderer:
    """Renders an event's slides; collects warnings in self.issues as (slide, message)."""

    def __init__(self, event):
        self.event = event
        self.W, self.H, self.fps = event.width, event.height, event.fps
        self.family = event.theme.get("font") or "Arial"
        self._boards = {}
        self._live = {}  # template path -> its live field codes
        self.issues = []

    # --- shared pieces -------------------------------------------------------------

    def warn(self, message):
        self.issues.append(message)

    def blank(self):
        return Image.new("RGB", (self.W, self.H), self.event.color("background"))

    def open_image(self, value, what):
        p = self.event.resolve(value)
        if not p.exists():
            raise MissingAsset(f"{what} not found: {value}")
        return uploads.open_picture(p)  # same pixels as a picture added in the app

    def picture(self, value):
        if value in (None, "none", False):
            return None
        if value == "logo":
            if not self.event.theme.get("logo"):
                self.warn("no team logo is set yet, so the card is drawn without one")
                return None
            value = self.event.theme["logo"]
        return self.open_image(value, "picture").convert("RGBA")

    def board(self, template):
        """A DisplayLink Plus template drawn once at board size."""
        path = self.event.template(template)
        if path not in self._boards:
            if not path.exists():
                raise MissingAsset(f"board template not found: {template}")
            reader = tpl.Reader(path.read_bytes())
            img, meta = tpl.Renderer(reader).render(reader.parse())
            self._live[path] = sorted(
                {i.get("Code") or "?" for i in meta["items"] if i["type"] == "DataTextTemplateItem"}
            )
            # Transparent parts of a template are unlit on the board, i.e. black. Blend onto black before dropping
            # alpha, or soft edges keep their raw colour (often white) and lettering turns into blocks.
            img = Image.alpha_composite(Image.new("RGBA", img.size, (0, 0, 0, 255)), img.convert("RGBA")).convert("RGB")
            self._boards[path] = (
                img.resize((self.W, self.H), Image.Resampling.LANCZOS) if img.size != (self.W, self.H) else img
            )
        if self._live.get(path):
            self.warn(
                f"{path.stem} shows live meet data ({tpl.describe_fields(self._live[path])}) "
                "that a video would freeze: pick a template without live fields"
            )
        return self._boards[path].copy()

    def panel(self, template):
        rect = self.event.panels.get(Path(str(template)).name)
        if rect is None:
            raise ValueError(f"template {template!r} has no panel to draw in: set one in the countdown or crawl editor")
        return tuple(int(v) for v in rect)  # x, y, w, h

    def bars(self, d, which, w=None, thick=BAR):
        w = w or self.W
        if which in ("top", "both"):
            d.rectangle((0, 0, w, thick - 1), fill=self.event.color("primary"))
        if which in ("bottom", "both"):
            d.rectangle((0, self.H - thick, w, self.H), fill=self.event.color("primary"))

    def line(self, spec, max_w):
        """(font, stroke, fill, height) for a card line, fitted to max_w."""
        style = spec.get("style", "regular")
        weight = "regular" if style == "regular" else "bold"
        stroke = OUTLINE if style == "outlined" else 0
        f, too_long = draw.fit(self.family, weight, str(spec["text"]), SIZES[spec.get("size", "S")], max_w, stroke)
        if too_long:
            self.warn(f"line too long for the board: {spec['text']!r}")
        fill = self.event.color("accent" if style == "accent" else "text")
        return f, stroke, fill, draw.line_height(f, stroke)

    def link_colour(self, p):
        """The theme colour a QR's printed link uses: muted (default), text, accent or primary."""
        role = p.get("link_color", "muted")
        return self.event.color(role if role in LINK_COLOURS else "muted")

    def link_under(self, d, url, cx, y, max_w, colour):
        """The short form of a QR's link (no https://, www. or trailing /) in small muted type.

        If it won't fit even at the smallest size, it's cut with "…" and flagged."""
        short = draw.short_url(url)
        f, too_long = draw.fit(self.family, "regular", short, 11, max_w)
        if too_long:
            self.warn(
                f"the link is too long to show under the QR ({len(short)} characters): "
                "shorten it, or turn off “Show the link”"
            )
            while short and draw.width(short + "…", f) > max_w:
                short = short[:-1]
            short += "…"
        draw.text_centred(d, cx, y, short, f, colour)

    def qr_placeholder(self, size):
        """A dashed square with 'ADD QR LINK', where a Text + QR card's code will go."""
        box = Image.new("RGB", (size, size), self.event.color("background"))
        d = ImageDraw.Draw(box)
        muted = self.event.color("muted")
        for k in range(0, size, 8):  # dashed outline
            for x0, y0, x1, y1 in (
                (k, 0, k + 4, 1),
                (k, size - 2, k + 4, size - 1),
                (0, k, 1, k + 4),
                (size - 2, k, size - 1, k + 4),
            ):
                d.rectangle((x0, y0, x1, y1), fill=muted)
        f = draw.font(self.family, "bold", 13)
        for i, word in enumerate(("ADD QR", "LINK")):
            draw.text_centred(d, size / 2, size / 2 - 16 + i * 18, word, f, muted)
        return box

    def draw_lines(self, d, lines, x0, x1, tops):
        for spec, (f, stroke, fill, _), y in zip(lines, [self.line(s, x1 - x0 - 2 * MARGIN) for s in lines], tops):
            draw.text_centred(d, (x0 + x1) / 2, y, str(spec["text"]), f, fill, stroke, self.event.color("primary"))

    # --- slide types ---------------------------------------------------------------

    def render(self, slide, hold):
        frames = round(hold * self.fps)
        clip = getattr(self, "_" + slide.type)(slide.props, frames)
        badges = [b for b in map(self.badge, slide.badges or []) if b]
        return with_badges(clip, badges) if badges else clip

    def badge(self, spec):
        """An extra picture over the slide (a badge, a league logo) as (picture, top-left position), or None
        when it has no picture yet. `place` is one of PLACES; `size` one of BADGE_SIZES."""
        if not isinstance(spec, dict) or not spec.get("file"):
            return None
        try:
            pic = self.open_image(spec["file"], "extra picture").convert("RGBA")
        except MissingAsset as exc:
            self.warn(f"{exc}; the slide is drawn without it")
            return None
        h = BADGE_SIZES.get(str(spec.get("size", "M")).upper(), BADGE_SIZES["M"])
        h = min(h, self.H - 2 * BADGE_INSET)
        w = min(round(pic.width * h / pic.height), self.W // 2)  # a wide picture stops at half the board
        h = max(1, round(pic.height * w / pic.width))
        pic = pic.resize((max(1, w), h), Image.Resampling.LANCZOS)
        place = spec.get("place") if spec.get("place") in PLACES else "top-right"
        if place.endswith("left"):
            x = BADGE_INSET
        elif place.endswith("right"):
            x = self.W - pic.width - BADGE_INSET
        else:
            x = (self.W - pic.width) // 2
        if place.startswith("top"):
            y = BADGE_INSET
        elif place.startswith("bottom"):
            y = self.H - pic.height - BADGE_INSET
        else:
            y = (self.H - pic.height) // 2
        return pic, (x, y)

    def _lanes(self, p, frames):
        """Guest lane assignments, a page at a time: each page shows the title and its share of the lanes
        for the hold time, crossfading into the next page."""
        lanes = list(p.get("lanes") or [])
        first, last, per_page = lane_range(p)
        pages = [
            self._lanes_page(
                p,
                [
                    (num, lanes[num - first] if num - first < len(lanes) else {})
                    for num in range(start, min(start + per_page, last + 1))
                ],
            )
            for start in range(first, last + 1, per_page)
        ]
        if len(pages) == 1:
            return still(pages[0], frames)
        fade = round(PAGE_FADE * self.fps)
        seq = []  # (image, count) runs: each page, then the blend into the next
        for k, page in enumerate(pages):
            seq.append((page, frames))
            if k < len(pages) - 1:
                seq += [(Image.blend(page, pages[k + 1], j / (fade + 1)), 1) for j in range(1, fade + 1)]

        def seek(target):
            seen = 0
            for img, count in seq:
                if seen + count > target:
                    return img
                seen += count
            return pages[-1]

        return Clip(lambda: iter(seq), pages[0], pages[-1], sum(c for _, c in seq), False, seek)

    def _lanes_page(self, p, page):
        """One page of a lanes slide: the title, then one cell per (lane number, lane) in `page`."""
        n = len(page)
        label = str(p.get("label", "LANE")).strip()
        img = self.blank()
        d = ImageDraw.Draw(img)
        top = 3
        title = str(p.get("title", "")).strip()
        if title:
            f, too_long = draw.fit(self.family, "bold", title, round(self.H * 0.15), self.W - 2 * MARGIN, OUTLINE)
            if too_long:
                self.warn(f"title too long for the board: {title!r}")
            draw.text_centred(
                d, self.W / 2, top, title, f, self.event.color("text"), OUTLINE, self.event.color("primary")
            )
            top += draw.line_height(f, OUTLINE) + 2
        cols = n if n <= 5 else math.ceil(n / 2)
        rows = 1 if n <= 5 else 2
        cw, ch = self.W / cols, (self.H - top - 2) / rows
        size = max(draw.MIN_SIZE, round(ch * 0.16))
        role = p.get("label_color", "accent")
        label_fill = self.event.color(role if role in LINK_COLOURS else "accent")
        for i, (num, lane) in enumerate(page):
            lane = lane if isinstance(lane, dict) else {}
            row, col = divmod(i, cols)
            x0, y0 = col * cw, top + row * ch
            cx, inner = x0 + cw / 2, cw - 4
            lf, _ = draw.fit(self.family, "bold", f"{label} {num}".strip(), size, inner)
            draw.text_centred(d, cx, y0, f"{label} {num}".strip(), lf, label_fill)
            names = [s.strip() for s in str(lane.get("name", "")).replace("|", "\n").split("\n") if s.strip()][:2]
            smallest_ok = max(draw.MIN_SIZE, round(size * 0.75))  # shrink a little before breaking a name in two
            if (
                len(names) == 1
                and " " in names[0]
                and draw.width(names[0], draw.font(self.family, "bold", smallest_ok)) > inner
            ):
                words = names[0].split()  # too wide for one line: break it at the middle word
                half = max(1, len(words) // 2)
                names = [" ".join(words[:half]), " ".join(words[half:])]
            fonts = []
            for name in names:
                f, too_long = draw.fit(self.family, "bold", name, size, inner)
                if too_long:
                    self.warn(f"lane {num}: team name too long for its cell: {name!r}")
                fonts.append(f)
            # The team's name sits right under its own lane's label, so on two rows it can't be read as the
            # next row's lane; the logo fills the rest of the cell below it.
            y = y0 + draw.line_height(lf) + 1
            for name, f in zip(names, fonts):
                draw.text_centred(d, cx, y, name, f, self.event.color("text"))
                y += draw.line_height(f)
            if lane.get("logo"):
                logo_top = y + 1
                box_w, box_h = round(inner), round(y0 + ch - 3 - logo_top)
                if box_w > 4 and box_h > 4:
                    pic = ImageOps.contain(
                        self.open_image(lane["logo"], f"lane {num} logo").convert("RGBA"),
                        (box_w, box_h),
                        Image.Resampling.LANCZOS,
                    )
                    img.paste(pic, (round(cx - pic.width / 2), round(logo_top + (box_h - pic.height) / 2)), pic)
        return img

    def _board(self, p, frames):
        return still(self.board(p["template"]), frames)

    def _card(self, p, frames):
        layout = p.get("layout", "stack")
        lines = [dict(l) for l in p.get("lines") or []]
        if layout == "banner" and len(lines) > BANNER_LINES:
            hidden = (
                f"line {BANNER_LINES + 1} is"
                if len(lines) == BANNER_LINES + 1
                else f"lines {BANNER_LINES + 1}–{len(lines)} are"
            )
            self.warn(f"a banner shows {BANNER_LINES} lines; {hidden} kept but hidden")
            lines = lines[:BANNER_LINES]
        big = 1 if layout == "logo-center" and len(lines) >= 3 else 0
        for i, l in enumerate(lines):  # default sizes by position: the big line L, others S
            l.setdefault("size", "L" if i == big else "S")
        img = self.blank()
        d = ImageDraw.Draw(img)
        bars = p.get("bars", "both")
        if layout == "banner":
            self.bars(d, "both", thick=12)
            top, bottom = 12, self.H - 12
        else:
            self.bars(d, bars)
            top = 6 + (BAR if bars in ("top", "both") else 0)
            bottom = self.H - 6 - (BAR if bars in ("bottom", "both") else 0)
        x0, x1 = 0, self.W
        # a picture: Logo center's defaults to the theme logo; other layouts show one only when it's chosen
        pic = self.picture(p.get("picture", "logo" if layout == "logo-center" else None))
        if layout == "text-picture":  # the picture beside the lines, as Text + QR has its code
            if pic is None:
                self.warn("this layout needs a picture: pick one under Picture")
            else:
                # kept MARGIN clear of the edge and the accent bars, as the lines are: closer, a badge seems to touch
                room = min(self.H - 20, bottom - top - 2 * (MARGIN - 6))
                pic = ImageOps.contain(pic, (int(self.W * 0.45), room), Image.Resampling.LANCZOS)  # within both
                pw, ph = pic.size
                left = p.get("picture_side") == "left"
                px = MARGIN if left else self.W - pw - MARGIN
                img.paste(pic, (px, top + (bottom - top - ph) // 2), pic)
                x0, x1 = (px + pw + 6, self.W) if left else (0, px - 6)
            pic = None
        if layout == "text-qr":
            show_link = bool(p.get("show_url")) and draw.full_url(p.get("qr"))
            size = min(self.H - 20 - (LINK_BAND if show_link else 0), int(self.W * 0.5))
            if draw.full_url(p.get("qr")):
                code, px = draw.qr_image(p["qr"], size)
                if px < 3:
                    self.warn(f"QR has {px} px per module: link too long to scan from the stands")
            else:  # no link yet: hold the QR's place so the layout reads, and say what's missing
                self.warn("this layout needs a QR link: add it below the lines")
                code = self.qr_placeholder(int(size * 0.85))
            x1 = self.W - code.width - 6
            qy = (self.H - code.height - (LINK_BAND if show_link else 0)) // 2
            img.paste(code, (x1, qy))
            if show_link:  # centred under the code; may run a little wider than it
                column = code.width + 2 * LINK_OVERHANG
                cx = x1 + code.width / 2
                x1 = min(x1, round(cx - column / 2))
                self.link_under(d, p["qr"], cx, qy + code.height + 3, column, self.link_colour(p))
            x1 -= 6
        heights = [self.line(l, x1 - x0 - 2 * MARGIN)[3] for l in lines]
        gap = 18 if layout != "banner" else 6
        if pic is None:
            self.draw_lines(d, lines, x0, x1, draw.distribute(top, bottom, heights, gap))
            return still(img, frames)
        # in the lines' column: above them, under the big line (as Logo center always had it), or below them
        place = p.get("picture_place", "middle")
        big_line = next((i + 1 for i, l in enumerate(lines) if l["size"] == "L"), 1)
        split = {"above": 0, "below": len(lines)}.get(place, min(big_line, len(lines)))
        avail = bottom - top - sum(heights) - 4 * len(lines)
        ph = max(8, min(int(p.get("picture_height", 70)), avail))
        pw = min(round(pic.width * ph / pic.height), x1 - x0 - 2 * MARGIN)
        ph = max(1, round(pic.height * pw / pic.width))
        tops = draw.distribute(top, bottom, heights[:split] + [ph] + heights[split:], gap)
        self.draw_lines(d, lines[:split], x0, x1, tops[:split])
        pic = pic.resize((pw, ph), Image.Resampling.LANCZOS)
        img.paste(pic, (round((x0 + x1 - pw) / 2), tops[split]), pic)
        self.draw_lines(d, lines[split:], x0, x1, tops[split + 1 :])
        return still(img, frames)

    def _qr(self, p, frames):
        img = self.blank()
        d = ImageDraw.Draw(img)
        linked = draw.full_url(p.get("url"))
        if linked:
            code, px = draw.qr_image(p["url"], self.H - 12)
            if px < 3:
                self.warn(f"QR has {px} px per module: link too long to scan from the stands")
        else:  # no full link yet: a code for "https://" would scan to nothing, so hold its place and say what's missing
            code = self.qr_placeholder(self.H - 28)
        right = p.get("side", "right") == "right"
        qx = self.W - code.width - 6 if right else 6
        img.paste(code, (qx, (self.H - code.height) // 2))
        x0, x1 = (6, qx - 8) if right else (qx + code.width + 8, self.W - 6)
        divider = qx - 7 if right else qx + code.width + 6
        d.line((divider, 24, divider, self.H - 24), fill=(70, 70, 70))
        cx = (x0 + x1) / 2
        d.rectangle((cx - 40, 10, cx + 40, 13), fill=self.event.color("primary"))
        heading = [{"text": t, "style": "bold", "size": "L"} for t in p.get("heading", [])]
        caption = [{"text": t, "size": "S"} for t in p.get("caption", ["Scan with your", "phone camera"])]
        if p.get("show_url", True) and linked:
            caption.append({"text": draw.short_url(p["url"]), "size": "S", "_px": 11, "_link": True})
        weights = []
        for l in heading + caption:
            f, too_long = draw.fit(
                self.family,
                "bold" if l in heading else "regular",
                l["text"],
                30 if l in heading else l.get("_px", 15),
                x1 - x0,
            )
            if too_long:
                self.warn(
                    f"the link is too long to show under the caption ({len(l['text'])} characters): "
                    "shorten it, or turn off “Show the link”"
                    if l.get("_link")
                    else f"line too long for the board: {l['text']!r}"
                )
            weights.append(f)
        tops = draw.distribute(22, self.H - 8, [draw.line_height(f) for f in weights], 14)
        for l, f, y in zip(heading + caption, weights, tops):
            fill = self.link_colour(p) if l.get("_link") else self.event.color("text" if l in heading else "muted")
            draw.text_centred(d, cx, y, l["text"], f, fill)
        return still(img, frames)

    def _crop(self, src, fx, fy, zoom):
        """Box (x0, y0, x1, y1) of src that fills the board around focus fx, fy at zoom."""
        iw, ih = src.size
        if iw / ih > self.W / self.H:
            cw, ch = ih * self.W / self.H, ih
        else:
            cw, ch = iw, iw * self.H / self.W
        cw, ch = cw / zoom, ch / zoom
        x = min(max(fx * iw - cw / 2, 0), iw - cw)
        y = min(max(fy * ih - ch / 2, 0), ih - ch)
        return x, y, x + cw, y + ch

    def _image(self, p, frames):
        """A picture: Fill (a board-shaped box fills the board) or Fit (any box, fitted with the background around it).

        A pan moves the box, same size, from where it starts to centre on `pan.to` over the hold."""
        src = self.open_image(p["file"], "image").convert("RGB")
        iw, ih = src.size
        fit = p.get("fit", "fill") == "fit"
        focus = p.get("focus", [0.5, 0.5])
        zoom = float(p.get("zoom", 1.0))
        if fit:
            c = [min(max(float(v), 0.0), 1.0) for v in (p.get("crop") or (0, 0, 1, 1))]
            start = (c[0] * iw, c[1] * ih, c[2] * iw, c[3] * ih)
            if start[2] - start[0] < 2 or start[3] - start[1] < 2:
                start = (0, 0, iw, ih)
            if min(self.W / (start[2] - start[0]), self.H / (start[3] - start[1])) > MAX_IMAGE_ZOOM:
                self.warn(
                    "the chosen part of the picture is small, so it will look blocky on the board: draw a bigger box"
                )
        else:
            start = self._crop(src, *focus, zoom)

        def draw_box(box):
            if not fit:
                return src.resize((self.W, self.H), Image.Resampling.LANCZOS, box=box)
            bw, bh = box[2] - box[0], box[3] - box[1]
            k = min(self.W / bw, self.H / bh)
            size = (max(1, round(bw * k)), max(1, round(bh * k)))
            img = self.blank()
            img.paste(
                src.resize(size, Image.Resampling.LANCZOS, box=box), ((self.W - size[0]) // 2, (self.H - size[1]) // 2)
            )
            return img

        pan = p.get("pan")
        if not pan:
            return still(draw_box(start), frames)
        if "to" in pan:  # the box slides, same size, until its centre is at `to` (kept inside the picture)
            bw, bh = start[2] - start[0], start[3] - start[1]
            tx = min(max(float(pan["to"][0]) * iw - bw / 2, 0), iw - bw)
            ty = min(max(float(pan["to"][1]) * ih - bh / 2, 0), ih - bh)
            end = (tx, ty, tx + bw, ty + bh)

            def box_at(e):
                return tuple(s0 + (e1 - s0) * e for s0, e1 in zip(start, end))

        else:  # the first format: start and end framings, Fill only
            a, b = pan.get("start", {}), pan.get("end", {})

            def box_at(e):
                def mix(k, dflt):
                    return a.get(k, dflt) + (b.get(k, dflt) - a.get(k, dflt)) * e

                return self._crop(src, mix("x", focus[0]), mix("y", focus[1]), mix("zoom", zoom))

        def frame(t):
            e = 0.7 * t + 0.3 * t * t * (3 - 2 * t)  # mostly linear, softened ends: never sits frozen
            return draw_box(box_at(e))

        n = max(frames, 1)
        return Clip(
            lambda: ((frame(k / max(n - 1, 1)), 1) for k in range(n)),
            frame(0),
            frame(1),
            n,
            False,
            lambda k: frame(min(k, n - 1) / max(n - 1, 1)),
        )

    def _countdown(self, p, _frames):
        total = int(seconds(p.get("length", "10:00")))
        label, sub = p.get("label", "WARM-UP"), p.get("sublabel", "time remaining")
        hold = seconds(p.get("hold_at_zero", 5))
        bg = p.get("background", "blank")
        if bg in (None, "blank"):
            base, (px, py, pw, ph) = None, (0, 0, self.W, self.H)
        else:
            base, (px, py, pw, ph) = self.board(bg), self.panel(bg)
        full = pw >= 240
        sizes = (30, 92, 17) if full else (26, 60, 15)
        rows = (10, 38, 146) if full else (14, 48, 120)
        scale = ph / (self.H if full else 145)
        primary, text, muted = (self.event.color(r) for r in ("primary", "text", "muted"))
        digits = draw.font(self.family, "bold", sizes[1])
        widths = {n: draw.width(n, digits) for n in ("0:00", "00:00")}  # centre on a fixed width per digit count

        def frame(secs):
            panel = Image.new("RGB", (pw, ph), self.event.color("background"))
            d = ImageDraw.Draw(panel)
            if full:
                d.rectangle((0, 0, pw, 3), fill=primary)
                d.rectangle((0, ph - 4, pw, ph), fill=primary)
            else:
                d.rectangle((pw // 2 - 46, 4, pw // 2 + 46, 6), fill=primary)
            f, too_long = draw.fit(self.family, "bold", label, sizes[0], pw - 12)
            draw.text_centred(d, pw / 2, round(rows[0] * scale), label, f, text)
            d.text(
                ((pw - widths["00:00" if secs >= 600 else "0:00"]) / 2, round(rows[1] * scale)),
                f"{secs // 60}:{secs % 60:02d}",
                font=digits,
                fill=text,
                stroke_width=3 if full else 2,
                stroke_fill=primary,
            )
            if sub:
                f, _ = draw.fit(self.family, "regular", sub, sizes[2], pw - 12)
                draw.text_centred(d, pw / 2, round(rows[2] * scale), sub, f, muted)
            img = base.copy() if base is not None else self.blank()
            img.paste(panel, (px, py))
            return img, too_long

        if frame(total)[1]:
            self.warn(f"countdown label too long: {label!r}")

        def runs():
            for secs in range(total, 0, -1):  # shows the time left rounded up: 10:00 first, then 9:59 …
                yield frame(secs)[0], self.fps
            yield frame(0)[0], max(1, round(hold * self.fps))

        n = total * self.fps + max(1, round(hold * self.fps))
        return Clip(runs, frame(total)[0], frame(0)[0], n, True, lambda k: frame(max(0, total - k // self.fps))[0])

    def _crawl(self, p, _frames):
        n = round(seconds(p.get("length", "3:00")) * self.fps)
        speed = CRAWL_SPEED.get(p.get("speed", "medium"), p.get("speed", 3))
        bg = p.get("background")
        if p.get("area", "full") == "panel":
            base, (px, py, pw, ph), size = self.board(bg), self.panel(bg), 40
        else:
            base, (px, py, pw, ph), size = None, (0, 0, self.W, self.H), 64
        f = draw.font(self.family, "bold", size)
        stroke = max(2, size // 16)
        parts = [(str(s["text"]), s.get("style", "regular")) for s in p.get("segments") or []]
        separator = str(p.get("separator", "•")).strip()  # "" or " " = spaces only
        parts.append((f"   {separator}   " if separator else "      ", "separator"))
        strip_w = round(sum(draw.width(t, f) for t, _ in parts))
        asc, desc = f.getmetrics()
        strip = Image.new("RGB", (strip_w, asc + desc + 10), self.event.color("background"))
        d = ImageDraw.Draw(strip)
        x = 0
        for t, style in parts:
            role = (
                p.get("separator_color", "primary") if style == "separator" else {"accent": "accent"}.get(style, "text")
            )
            fill = self.event.color(role if role in LINK_COLOURS else "primary")
            d.text(
                (x, 6),
                t,
                font=f,
                fill=fill,
                stroke_width=stroke if style == "outlined" else 0,
                stroke_fill=self.event.color("primary"),
            )
            x += draw.width(t, f)

        def frame(k):
            panel = Image.new("RGB", (pw, ph), self.event.color("background"))
            if base is None:
                pd = ImageDraw.Draw(panel)
                pd.rectangle((0, 0, pw, 3), fill=self.event.color("primary"))
                pd.rectangle((0, ph - 4, pw, ph), fill=self.event.color("primary"))
            x = pw - k * speed  # enters from the right edge, then tiles seamlessly
            if x < 0:
                x = -((-x) % strip_w)
            while x < pw:
                panel.paste(strip, (x, (ph - strip.height) // 2))
                x += strip_w
            img = base.copy() if base is not None else self.blank()
            img.paste(panel, (px, py))
            return img

        return Clip(
            lambda: ((frame(k), 1) for k in range(n)),
            frame(0),
            frame(max(n - 1, 0)),
            n,
            True,
            lambda k: frame(min(k, n - 1)),
        )


def as_seconds(frames, fps):
    return math.ceil(frames / fps * 10) / 10
