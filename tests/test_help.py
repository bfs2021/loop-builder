"""--help names the module, not __main__.py, and shows the developer options."""

import sys

import pytest

from app.__main__ import main as app_main
from loopgen.__main__ import main as loopgen_main


def help_output(main, monkeypatch, capsys, name):
    monkeypatch.setattr(sys, "argv", [name, "--help"])
    with pytest.raises(SystemExit) as exit_:
        main()
    assert exit_.value.code == 0
    return capsys.readouterr().out


def test_app_help_lists_the_developer_options(monkeypatch, capsys):
    out = help_output(app_main, monkeypatch, capsys, "app")
    assert "usage: python -m app" in out
    for option in ("--templates", "--port", "--browser", "--no-open"):
        assert option in out


def test_loopgen_help_names_the_module(monkeypatch, capsys):
    out = help_output(loopgen_main, monkeypatch, capsys, "loopgen")
    assert "usage: python -m loopgen" in out
    assert "__main__.py" not in out
