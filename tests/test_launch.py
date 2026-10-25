"""Starting without a console, as the packaged Windows app does, in a window that fits the screen."""

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as Screen

import pytest
import uvicorn

from app.__main__ import WINDOW, ensure_streams, first_size, fit_to, spills, start_folder, unreachable_page


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


def test_a_folder_that_cant_be_reached_still_gets_a_log(tmp_path, monkeypatch):
    """A school's Documents on a network share, off the network: the log goes to the temp folder, not a crash."""
    (tmp_path / "share").write_text("not a folder")  # nothing can be made below a file
    monkeypatch.setenv("LOOPBUILDER_HOME", str(tmp_path / "share" / "Loop Builder"))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    log = ensure_streams()
    sys.stdout.close()
    assert log.name == "loop-builder.log" and log.parent == Path(tempfile.gettempdir())


def test_the_unreachable_page_names_the_folder_safely():
    page = unreachable_page(r"\\school\home\<pat>\Documents\Loop Builder", "[WinError 53] network path not found")
    assert "&lt;pat&gt;" in page and "<pat>" not in page and "WinError 53" in page


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


def test_dialogs_start_in_a_folder_that_exists(tmp_path):
    """Round 5: a new user's exports folder doesn't exist until the first export, and a dialog given a missing
    folder opens wherever the last one did. Save makes it first; the others climb to a folder that exists."""
    exports = tmp_path / "Movies" / "Loop Builder"
    assert start_folder(str(exports)) == str(tmp_path) and not exports.exists()  # nothing made
    assert start_folder(str(exports), make=True) == str(exports) and exports.is_dir()
    (tmp_path / "a file").write_text("x")
    assert start_folder(str(tmp_path / "a file"), make=True) == str(tmp_path)  # a file: the folder it's in
    assert start_folder(str(tmp_path / "a file" / "below"), make=True) == str(tmp_path)  # can't be made: above it
    assert start_folder("") == start_folder("  ") == start_folder("Exports", make=True) == ""  # relative: none
    assert not (Path.cwd() / "Exports").exists()
    nobody = start_folder("~nosuchuser12345/Exports")  # Mac: no such home ("" = the system's choice); Windows maps
    assert nobody == "" or os.path.isdir(nobody)  # it under C:\\Users and climbs. Either way, no error


@pytest.mark.skipif(sys.platform == "win32", reason="chmod can't lock a folder on Windows")
def test_a_folder_that_cant_be_read_doesnt_break_the_dialog(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        # Path.is_dir() raises PermissionError for Exports inside it; the dialog still gets the nearest folder
        assert start_folder(str(locked / "Exports"), make=True) == str(locked)
    finally:
        locked.chmod(0o755)


def test_only_save_makes_the_folder(tmp_path, monkeypatch):
    import app.__main__ as launcher  # pylint: disable=import-outside-toplevel

    calls = []
    monkeypatch.setattr(
        launcher.NativeDialogs, "_dialog", lambda self, kind, **kw: calls.append((kind, kw["directory"]))
    )
    dialogs, folder = launcher.NativeDialogs(), tmp_path / "Exports"
    dialogs.pick_folder(str(folder))
    dialogs.open_package(str(folder))
    assert not folder.exists() and calls == [("FOLDER", str(tmp_path)), ("OPEN", str(tmp_path))]
    dialogs.save_file("Meet.loopevent", str(folder))
    assert folder.is_dir() and calls[-1] == ("SAVE", str(folder))
