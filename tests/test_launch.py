"""Starting without a console, as the packaged Windows app does, in a window that fits the screen."""

import sys
from types import SimpleNamespace as Screen

import uvicorn

from app.__main__ import WINDOW, ensure_streams, first_size, fit_to, spills, start_folder


def test_a_windowed_start_logs_to_a_file_instead_of_failing(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOPBUILDER_HOME", str(tmp_path / "Loop Builder"))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    log = ensure_streams()
    try:
        uvicorn.Config(lambda scope, receive, send: None, log_level="warning")  # set up logging: failed before
        print("started")
    finally:
        sys.stdout.close()
    assert log == tmp_path / "Loop Builder" / "loop-builder.log" and "started" in log.read_text(encoding="utf-8")


def test_a_console_start_keeps_its_streams():
    assert ensure_streams() is None


def test_the_window_fits_any_screen():
    assert fit_to(0, 0, 2560, 1400) == (560, 220, *WINDOW)  # room for the usual size: centred
    for area in [(0, 0, 1280, 672), (0, 40, 1366, 728), (-1920, 0, 1920, 1032), (0, 0, 3840, 2100)]:
        x, y, w, h = fit_to(*area)
        left, top, width, height = area
        assert left <= x and x + w <= left + width and top <= y and y + h <= top + height  # on the screen
    assert not spills((256, 141, 1000, 700), (0, 33, 1512, 892))
    assert spills((0, 0, 1500, 1400), (0, 33, 1512, 892)) and spills((-10, 100, 800, 600), (0, 0, 1920, 1040))
    assert first_size([Screen(width=1280, height=720)])[1] < 720 and first_size([]) == WINDOW


def test_show_folder_opens_only_a_folder_that_exists(tmp_path, monkeypatch):
    import app.__main__ as launcher  # pylint: disable=import-outside-toplevel

    opened = []
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher.os, "startfile", opened.append, raising=False)
    dialogs = launcher.NativeDialogs()
    assert dialogs.show_folder(str(tmp_path)) and opened == [str(tmp_path)]
    assert not dialogs.show_folder(str(tmp_path / "missing")) and not dialogs.show_folder("") and len(opened) == 1


def test_save_and_open_dialogs_start_in_a_folder_that_exists(tmp_path):
    """Round 5: a new user's exports folder doesn't exist until the first export, and a dialog given a missing
    folder opens wherever the last one did. Save and Open make it first; the folder picker climbs to one that exists."""
    exports = tmp_path / "Movies" / "Loop Builder"
    assert start_folder(str(exports)) == str(tmp_path) and not exports.exists()  # folder picker: nothing made
    assert start_folder(str(exports), make=True) == str(exports) and exports.is_dir()
    (tmp_path / "a file").write_text("x")
    assert start_folder(str(tmp_path / "a file" / "below"), make=True) == str(tmp_path)  # can't be made: above it
    assert start_folder("") == ""
