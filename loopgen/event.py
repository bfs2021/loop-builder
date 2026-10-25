"""Load an event file and normalise its loops and slides."""

import copy
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from PIL import ImageColor

SLIDE_TYPES = ("board", "card", "qr", "image", "countdown", "crawl", "lanes")
TIMED = ("countdown", "crawl")
COMMON = ("id", "hold", "fade", "notes", "badges")
DEFAULT_THEME = {
    "primary": "#CC0202",
    "accent": "#F0C878",
    "text": "#FFFFFF",
    "muted": "#AAAAAA",
    "background": "#000000",
    "logo": None,
    "font": "Arial",
}
PANELS_FILE = Path(__file__).with_name("templates.yaml")


class EventError(ValueError):
    """The event file can't be read as an event."""


@dataclass
class Slide:
    """One slide: its type (card, lanes, countdown…), its own settings, and the hold, fade and id any slide may set."""

    type: str
    props: dict
    id: str = None
    hold: float = None
    fade: float = None
    notes: str = None
    badges: list = None  # extra pictures over any slide (badges, league logos): [{file, place, size}]

    @property
    def timed(self):
        return self.type in TIMED


@dataclass
class Loop:
    """A named run of slides, exported as one video."""

    name: str
    slides: list
    hold: float = 10.0
    fade: float = 0.5
    repeat: bool = True  # the last slide fades back into the first; a loop with a countdown ends on its last slide


@dataclass
class Event:
    """An event file, read: its loops, board size, theme and template folder."""

    name: str
    path: Path
    width: int
    height: int
    theme: dict
    loops: list
    templates: Path
    panels: dict = field(default_factory=dict)
    date: str = None
    fps: int = 30

    def resolve(self, value):
        """A path from the event file, relative to the file unless absolute or ~."""
        p = Path(str(value)).expanduser()
        return p if p.is_absolute() else self.path.parent / p

    def template(self, name):
        """A template's file. A name not found where it says is looked for by file name anywhere under the
        template folder, so picking a folder one level up (e.g. the whole DisplayLink Plus library) still works."""
        p = Path(str(name)).expanduser()
        if p.is_absolute():
            return p
        direct = self.templates / p
        if direct.exists() or not self.templates.is_dir():
            return direct
        matches = [m for m in self.templates.rglob(p.name) if m.is_file()]
        return matches[0] if len(matches) == 1 else direct

    def color(self, role):
        return ImageColor.getrgb(self.theme[role])

    def loop(self, key):
        """A loop by name or 1-based number."""
        for i, loop in enumerate(self.loops, 1):
            if key in (loop.name, str(i)):
                return loop
        raise EventError(f"no loop named {key!r}; loops: {', '.join(l.name for l in self.loops)}")


def _slide(item, where):
    if not isinstance(item, dict) or len(item) != 1 or next(iter(item)) not in SLIDE_TYPES:
        raise EventError(f"{where}: a slide is one of {', '.join(SLIDE_TYPES)}, e.g. '- card: {{...}}'")
    kind, props = next(iter(item.items()))
    if props is not None and not isinstance(props, dict):
        raise EventError(f"{where}: a {kind}'s settings go under it as name: value, e.g. '- {kind}: {{...}}'")
    props = dict(props or {})
    common = {k: props.pop(k) for k in COMMON if k in props}
    return Slide(kind, props, **common)


def read_event_file(path):
    """An event file's data, if it has the shape load_event reads: a mapping, its loops a list of mappings. A file
    that isn't (a YAML slip, a half-synced copy) raises EventError saying where, rather than a crash further on."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:  # can't be opened, or saved in another encoding
        raise EventError(f"{path}: can't be read as an event file: {exc}") from exc
    return parse_event(text, path)


def parse_event(text, path):
    """read_event_file for text already in hand (an event.yaml inside a .loopevent); `path` names it in errors."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        raise EventError(
            f"{path}: not a readable event file{f' (line {mark.line + 1})' if mark else ''}: "
            f"{getattr(exc, 'problem', None) or exc}"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("loops"), list):
        raise EventError(f"{path}: an event file needs 'loops', a list of loops")
    for key in ("theme", "board", "template_panels"):
        if not isinstance(data.get(key) or {}, dict):
            raise EventError(f"{path}: '{key}' needs name: value settings")
    for name, panel in (data.get("template_panels") or {}).items():
        if not isinstance(panel, dict) or "panel" not in panel:
            raise EventError(f"{path}: template_panels: {name} needs a 'panel'")
    for n, raw in enumerate(data["loops"], 1):
        if not isinstance(raw, dict):
            raise EventError(f"{path}: loop {n} needs a name and slides, e.g. '- name: Welcome'")
        if not isinstance(raw.get("slides") or [], list):
            raise EventError(f"{path}: loop {n} ({raw.get('name', '?')}): 'slides' needs to be a list")
    return data


def load_event(path, templates=None):
    """Read an event file; `templates` (the DisplayLink Plus template folder setting) overrides the file's own."""
    path = Path(path).expanduser().resolve()
    data = read_event_file(path)
    board = data.get("board") or {}
    theme = {**DEFAULT_THEME, **(data.get("theme") or {})}
    panels = {}
    if PANELS_FILE.exists():
        panels.update(
            {
                k: v["panel"]
                for k, v in (yaml.safe_load(PANELS_FILE.read_text(encoding="utf-8")) or {}).items()
                if "panel" in v
            }
        )
    panels.update({k: v["panel"] for k, v in (data.get("template_panels") or {}).items()})
    templates = Path(str(templates or data.get("templates", "templates"))).expanduser()
    if not templates.is_absolute():
        templates = path.parent / templates

    loops, by_id = [], {}
    for n, raw in enumerate(data["loops"], 1):
        where = f"loop {n} ({raw.get('name', '?')})"
        slides = [_slide(item, f"{where}, slide {i}") for i, item in enumerate(raw.get("slides") or [], 1)]
        for s in slides:
            if s.id and "ref" not in s.props:
                if s.id in by_id:
                    raise EventError(f"{where}: slide id {s.id!r} is used twice")
                by_id[s.id] = s
        try:
            hold, fade = float(raw.get("hold", 10)), float(raw.get("fade", 0.5))
        except (TypeError, ValueError) as exc:
            raise EventError(f"{where}: hold and fade are seconds, e.g. 'hold: 10'") from exc
        loops.append(
            Loop(
                raw.get("name") or f"Loop {n}",
                slides,
                hold,
                fade,
                not any(s.type == "countdown" for s in slides),  # older files' `repeat` is ignored
            )
        )
    for loop in loops:  # linked slides: same content, the link may override hold and fade
        for i, s in enumerate(loop.slides):
            if "ref" in s.props:
                target = by_id.get(s.props["ref"])
                if target is None:
                    raise EventError(f"{loop.name}: slide {i + 1} links to unknown id {s.props['ref']!r}")
                if target.type != s.type:
                    raise EventError(f"{loop.name}: slide {i + 1} is a {s.type} but {target.id!r} is a {target.type}")
                loop.slides[i] = Slide(
                    target.type,
                    copy.deepcopy(target.props),
                    target.id,
                    s.hold if s.hold is not None else target.hold,
                    s.fade if s.fade is not None else target.fade,
                    s.notes or target.notes,
                    copy.deepcopy(s.badges if s.badges is not None else target.badges),
                )
    return Event(
        data.get("event") or path.stem,
        path,
        int(board.get("width", 320)),
        int(board.get("height", 176)),
        theme,
        loops,
        templates,
        panels,
        data.get("date") and str(data["date"]),
        int(data.get("fps", 30)),
    )
