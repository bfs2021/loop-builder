"""Start Loop Builder: the app window on the events home, backed by a local server on 127.0.0.1.

python -m app [EVENT.yaml] [--templates "<DisplayLink Plus template folder>"]

With EVENT.yaml the editor opens on that event straight away. Developer options: --browser opens a
browser tab instead (reload and dev tools); --no-open only serves; --port picks the port (default: any free one).
"""

import argparse
import html
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from app.library import Library, default_root
from app.server import create_app


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class NativeDialogs:
    """The system's own folder, open and save pickers, and fitting the window to the screen, offered to the page
    as window.pywebview.api."""

    def __init__(self):
        self._window = None  # private: pywebview exposes every public attribute to the page
        self._fitted = False

    def _dialog(self, kind, **kwargs):
        import webview  # pylint: disable=import-outside-toplevel

        mode = getattr(getattr(webview, "FileDialog", None), kind, None) or getattr(webview, f"{kind}_DIALOG")
        picked = self._window.create_file_dialog(mode, **kwargs)
        if isinstance(picked, (list, tuple)):
            picked = picked[0] if picked else None
        return picked or None

    def pick_folder(self, start=""):
        return self._dialog("FOLDER", directory=start or "")

    def save_file(self, name, start=""):
        return self._dialog("SAVE", directory=start or "", save_filename=name)

    def show_folder(self, path):
        """Open a folder in Explorer or Finder: where an export just put its files."""
        if not path or not os.path.isdir(path):
            return False
        if sys.platform == "win32":
            os.startfile(path)  # pylint: disable=no-member  # Windows only
        else:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", path], check=False)
        return True

    def open_package(self, start=""):
        """A .loopevent to import. The page's own file input can't offer one on a Mac: the web view filters by
        file type, and macOS knows no type for .loopevent, so it greys those files out."""
        return self._dialog("OPEN", directory=start or "", file_types=("Loop Builder event (*.loopevent)",))

    def fit_screen(self, left, top, width, height):
        """Given the usable screen area the page measured, fit and centre the window if it spills over (once
        per run). The page knows that area; only the app knows where its window is (webviews misreport it)."""
        if self._fitted:
            return
        self._fitted = True
        win = self._window
        if spills((win.x, win.y, win.width, win.height), (left, top, width, height)):
            x, y, w, h = fit_to(left, top, width, height)
            win.resize(w, h)
            win.move(x, y)


WINDOW = (1440, 960)
MIN_WINDOW = (800, 500)
SCREEN_SHARE = 0.92  # of the usable screen, so the window's edges and title bar stay on it


def fit_to(left, top, width, height):
    """The window's place [x, y, width, height] in a usable screen area: the usual size if it fits,
    else as much of the area as SCREEN_SHARE allows, centred. Any units, as long as all are the same."""
    w, h = min(WINDOW[0], int(width * SCREEN_SHARE)), min(WINDOW[1], int(height * SCREEN_SHARE))
    return left + (width - w) // 2, top + (height - h) // 2, w, h


def spills(window, area):
    """Whether a window [x, y, width, height] goes past a screen area [left, top, width, height]."""
    x, y, w, h = window
    left, top, width, height = area
    return x < left or y < top or x + w > left + width or y + h > top + height


def first_size(screens):
    """A first guess at the window's size from pywebview's screen list; the page corrects it once it can
    measure the usable screen (see fitWindow in common.js)."""
    if not screens:
        return WINDOW
    return fit_to(0, 0, screens[0].width, screens[0].height)[2:]


def ensure_streams():
    """A windowed build (no console) starts with no stdout/stderr, and uvicorn's logging fails on that: send
    them to loop-builder.log in the Loop Builder folder, fresh each start."""
    if sys.stdout is not None and sys.stderr is not None:
        return None
    log = default_root() / "loop-builder.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        stream = open(log, "w", encoding="utf-8", buffering=1)  # pylint: disable=consider-using-with  # app-long
    except OSError:  # the folder can't be reached (a share, off the network): a log the app can still write
        log = Path(tempfile.gettempdir()) / "loop-builder.log"
        stream = open(log, "w", encoding="utf-8", buffering=1)  # pylint: disable=consider-using-with
    sys.stdout = sys.stdout or stream
    sys.stderr = sys.stderr or stream
    return log


def unreachable_page(folder, problem):
    """What the window says when the Loop Builder folder can't be reached, instead of opening on an empty or second
    library (a school's Documents on a network share, with the PC off the network)."""
    folder, problem = html.escape(str(folder)), html.escape(str(problem))
    return (
        "<!doctype html><meta charset=utf-8><body style='font:16px system-ui;padding:32px;max-width:40em'>"
        f"<h2>Loop Builder can’t reach its folder</h2><p>Your events are kept in <b>{folder}</b>, which this computer "
        "can’t open right now. If it’s on a school or work network, connect to it, then open Loop Builder again.</p>"
        f"<p style='color:#666'>{problem}</p>"
    )


def main():
    ensure_streams()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("event", nargs="?")
    ap.add_argument("--templates", help="DisplayLink Plus template folder (overrides the setting)")
    ap.add_argument("--port", type=int, help=argparse.SUPPRESS)
    ap.add_argument("--browser", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-open", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    try:
        library = Library()
    except OSError as exc:  # its folder can't be made or reached
        print(f"error: the Loop Builder folder can't be reached: {exc}", file=sys.stderr)
        if args.browser or args.no_open:
            raise SystemExit(1) from exc
        import webview  # pylint: disable=import-outside-toplevel

        webview.create_window("Loop Builder", html=unreachable_page(default_root(), exc), width=640, height=360)
        webview.start()
        raise SystemExit(1) from exc
    port = args.port or free_port()
    url = f"http://127.0.0.1:{port}/" + ("edit" if args.event else "")
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(args.event, args.templates, library=library), host="127.0.0.1", port=port, log_level="warning"
        )
    )
    if args.browser or args.no_open:
        if args.browser:
            threading.Timer(1.0, webbrowser.open, [url]).start()
        server.run()
        return

    import webview  # pylint: disable=import-outside-toplevel  # the window toolkit loads only for the app

    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:  # open the window only once the page can load
        time.sleep(0.05)
    dialogs = NativeDialogs()
    try:
        screens = webview.screens
    except Exception:  # pylint: disable=broad-except  # no screen list: the default size
        screens = []
    width, height = first_size(screens)
    dialogs._window = webview.create_window(  # pylint: disable=protected-access
        "Loop Builder", url, width=width, height=height, min_size=MIN_WINDOW, js_api=dialogs
    )
    webview.start()
    server.should_exit = True


if __name__ == "__main__":
    main()
