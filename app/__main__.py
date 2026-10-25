"""Start Loop Builder: the app window on the events home, backed by a local server on 127.0.0.1.

python -m app [EVENT.yaml] [--templates "<DisplayLink Plus template folder>"]

With EVENT.yaml the editor opens on that event straight away. Developer options: --browser opens a
browser tab instead (reload and dev tools); --no-open only serves; --port picks the port (default: any free one).
"""

import argparse
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from app.library import default_root
from app.server import create_app


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_folder(start, make=False):
    """Where a dialog opens. A dialog given a folder that doesn't exist opens wherever the last one did, and the
    exports folder (Movies › Loop Builder on a Mac) only exists after the first export: so with `make` the folder is
    made first. Otherwise, or if it can't be made, the nearest folder above it that exists. Never raises: a folder
    that can't be read, or "~someone" with no such user, gives the system's own choice ("")."""
    try:
        path = Path(str(start or "").strip()).expanduser()
    except (RuntimeError, OSError):
        return ""
    if not path.is_absolute():  # empty or relative: nothing to start in, and nothing made beside the app
        return ""
    if make:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return next((str(p) for p in (path, *path.parents) if os.path.isdir(p)), "")  # isdir never raises


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
        return self._dialog("FOLDER", directory=start_folder(start))

    def save_file(self, name, start=""):
        return self._dialog("SAVE", directory=start_folder(start, make=True), save_filename=name)

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
        return self._dialog("OPEN", directory=start_folder(start), file_types=("Loop Builder event (*.loopevent)",))

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
    log.parent.mkdir(parents=True, exist_ok=True)
    stream = open(log, "w", encoding="utf-8", buffering=1)  # pylint: disable=consider-using-with  # app-long
    sys.stdout = sys.stdout or stream
    sys.stderr = sys.stderr or stream
    return log


def main():
    ensure_streams()
    ap = argparse.ArgumentParser(
        prog="python -m app", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("event", nargs="?")
    ap.add_argument("--templates", help="DisplayLink Plus template folder (overrides the setting)")
    developer = ap.add_argument_group("developer options")
    developer.add_argument("--port", type=int, help="port to serve on (default: any free one)")
    developer.add_argument("--browser", action="store_true", help="open a browser tab instead of the app window")
    developer.add_argument("--no-open", action="store_true", help="serve only: open no window and no tab")
    args = ap.parse_args()
    port = args.port or free_port()
    url = f"http://127.0.0.1:{port}/" + ("edit" if args.event else "")
    server = uvicorn.Server(
        uvicorn.Config(create_app(args.event, args.templates), host="127.0.0.1", port=port, log_level="warning")
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
