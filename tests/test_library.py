"""The Loop Builder folder: starters, duplicates, settings and .loopevent packages."""

import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.library import STARTERS, Library, LibraryError
from app.server import create_app
from loopgen import load_event, render_slide, run_checks
from loopgen.__main__ import main as cli
from loopgen.event import EventError


@pytest.fixture(name="lib")
def fixture_lib(tmp_path):
    return Library(tmp_path / "Loop Builder")


@pytest.mark.parametrize("starter", sorted(STARTERS))
def test_every_starter_loads_and_draws(lib, starter):
    slug = lib.create(f"{starter} test", starter)
    event = load_event(lib.event_file(slug))
    for loop in event.loops:
        for i in range(len(loop.slides)):
            assert render_slide(event, loop, i).size == (320, 176)
    errors = [i for i in run_checks(event) if i.level == "error"]
    # only what's left for the team to fill in: the Sections heat-sheet link and the visiting team's name
    assert all("QR" in e.message or "VISITING TEAM" in e.message for e in errors)


def test_names_never_collide_and_duplicates_are_independent(lib):
    first = lib.create("Dual: Lakeview", "dual-meet")
    second = lib.create("Dual: Lakeview", "dual-meet")
    assert first == "Dual- Lakeview" and second == "Dual- Lakeview (2)"
    copy = lib.duplicate(first, "Next week")
    assert load_event(lib.event_file(copy)).name == "Next week"
    assert {e["slug"] for e in lib.events()} == {first, second, copy}


def test_package_round_trip_and_unsafe_packages(lib, tmp_path):
    slug = lib.create("Sections", "sections")
    package = lib.export_package(slug, tmp_path / "Sections")
    assert package.suffix == ".loopevent"
    imported = lib.import_package(package)  # "Sections" is still here, so the copy is told apart like its folder
    assert imported == "Sections (2)" and load_event(lib.event_file(imported)).name == "Sections (2)"
    lib.delete(slug)
    lib.delete(imported)
    assert load_event(lib.event_file(lib.import_package(package))).name == "Sections"  # on another computer
    bad = tmp_path / "bad.loopevent"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("event.yaml", "event: x\nloops: []\n")
        z.writestr("../../escape.txt", "no")
    with pytest.raises(LibraryError):
        lib.import_package(bad)


def test_settings_keep_known_keys_only(lib):
    lib.update_settings(team="Riverside", templates="/tmp", nonsense=1)
    settings = lib.settings()
    assert settings["team"] == "Riverside" and "nonsense" not in settings


def test_team_library_trims_logos_and_copies_them_into_events(lib, tmp_path):
    from PIL import Image  # pylint: disable=import-outside-toplevel

    logo = Image.new("RGB", (400, 300), "white")
    logo.paste((0, 80, 200), (100, 75, 300, 225))  # a blue badge on a white page
    logo.save(tmp_path / "pine-ridge.jpg")
    team_id = lib.add_team("Pine Ridge", tmp_path / "pine-ridge.jpg", trim=True)
    with Image.open(lib.teams_dir / f"{team_id}.png") as stored:
        size, mode = stored.size, stored.mode
    assert mode == "RGBA" and 200 <= size[0] <= 212 and 150 <= size[1] <= 162  # page gone (JPEG
    # noise at the badge's edge keeps a few px)
    slug = lib.create("Sections", "sections")
    used = lib.use_team(team_id, lib.event_file(slug).parent)
    assert used == {"name": "Pine Ridge", "logo": "assets/teams/pine-ridge.png"}
    assert (lib.event_file(slug).parent / used["logo"]).exists()
    lib.rename_team(team_id, "PINE RIDGE")
    assert lib.teams()[0]["name"] == "PINE RIDGE"
    lib.delete_team(team_id)
    assert lib.teams() == []


def test_home_team_from_settings_leads_the_team_list(lib, tmp_path):
    from PIL import Image  # pylint: disable=import-outside-toplevel

    Image.new("RGBA", (60, 40), (0, 80, 200, 255)).save(tmp_path / "otters.png")
    lib.update_settings(team="Riverside Otters")
    assert lib.teams() == []  # a name without a logo isn't a team on the board yet
    lib.set_logo(tmp_path / "otters.png")
    lib.add_team("Lakeview", tmp_path / "otters.png", trim=False)
    home, added = lib.teams()
    assert home["home"] and home["name"] == "Riverside Otters" and added["name"] == "Lakeview"
    slug = lib.create("Dual", "dual-meet")
    used = lib.use_team(home["id"], lib.event_file(slug).parent)
    assert (lib.event_file(slug).parent / used["logo"]).exists() and used["name"] == "Riverside Otters"
    assert used["logo"] == "assets/teams/_home.png"  # never the same file as an added team's "<id>.png"
    with pytest.raises(LibraryError):
        lib.rename_team(home["id"], "Someone else")  # its name lives in Settings
    with pytest.raises(LibraryError):
        lib.delete_team(home["id"])
    assert [t["name"] for t in lib.teams()] == ["Riverside Otters", "Lakeview"]
    assert lib.settings()["team"] == "Riverside Otters"


def test_pool_lanes_are_team_settings(lib):
    assert lib.settings()["pool_lanes"] == 8 and lib.settings()["first_lane"] == 1
    lib.update_settings(pool_lanes=10, first_lane=0)
    assert lib.settings()["pool_lanes"] == 10 and lib.settings()["first_lane"] == 0


def test_delete_removes_only_that_event(lib):
    keep, gone = lib.create("Keep", "blank"), lib.create("Gone", "blank")
    lib.delete(gone)
    assert [e["slug"] for e in lib.events()] == [keep]
    for slug in (gone, ".", ".."):
        with pytest.raises(LibraryError):
            lib.delete(slug)
    assert lib.event_file(keep).exists()


def test_pictures_are_kept_for_every_event_and_copied_into_one_on_use(lib, tmp_path):
    from PIL import Image  # pylint: disable=import-outside-toplevel

    badge = Image.new("RGB", (300, 120), "white")
    badge.paste((20, 40, 160), (40, 20, 260, 100))  # a flat-colour badge: kept as PNG, not smudged into a JPEG
    badge.save(tmp_path / "app-badge.png")
    Image.new("RGB", (3000, 2000), (200, 150, 40)).save(tmp_path / "duck.jpg")
    badge_id = lib.add_picture("App badge", tmp_path / "app-badge.png", trim=True)
    duck_id = lib.add_picture("Duck", tmp_path / "duck.jpg")
    pictures = {p["id"]: p for p in lib.pictures()}
    assert [p["name"] for p in lib.pictures()] == ["App badge", "Duck"]
    assert pictures[badge_id]["file"] == "app-badge.png" and pictures[badge_id]["size"] == [220, 80]  # page trimmed
    assert pictures[duck_id]["file"] == "duck.jpg" and max(pictures[duck_id]["size"]) == 2048  # shrunk working copy
    slug = lib.create("Sections", "sections")
    folder = lib.event_file(slug).parent
    assert lib.use_picture(badge_id, folder) == {"file": "assets/pictures/app-badge.png"}
    assert (folder / "assets" / "pictures" / "app-badge.png").exists()
    lib.add_picture("Duck", tmp_path / "app-badge.png")  # the same name replaces it, even as another type
    assert sorted(p.name for p in lib.pictures_dir.iterdir()) == ["app-badge.png", "duck.png", "pictures.json"]
    lib.rename_picture(duck_id, "Rubber duck")
    lib.delete_picture(badge_id)
    assert [p["name"] for p in lib.pictures()] == ["Rubber duck"]
    assert (folder / "assets" / "pictures" / "app-badge.png").exists()  # the event keeps its copy
    with pytest.raises(LibraryError):
        lib.add_picture("  ", tmp_path / "duck.jpg")
    with pytest.raises(LibraryError):
        lib.use_picture("gone", folder)


def test_the_loop_builder_folder_is_in_application_support_on_a_mac(tmp_path, monkeypatch):
    from app import library  # pylint: disable=import-outside-toplevel

    monkeypatch.delenv("LOOPBUILDER_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Path.home() on Windows
    monkeypatch.setattr(library.sys, "platform", "darwin")
    assert library.default_root() == tmp_path / "Library" / "Application Support" / "Loop Builder"
    assert library.default_exports(library.default_root()) == tmp_path / "Movies" / "Loop Builder"
    monkeypatch.setattr(library.sys, "platform", "win32")
    monkeypatch.setattr(library, "windows_documents", lambda: None)  # Windows can't say: the user folder's
    assert library.default_root() == library.documents_root() == tmp_path / "Documents" / "Loop Builder"
    assert library.default_exports(library.default_root()) == tmp_path / "Documents" / "Loop Builder" / "Exports"
    monkeypatch.setenv("LOOPBUILDER_HOME", str(tmp_path / "elsewhere"))
    assert library.default_root() == tmp_path / "elsewhere"


def test_move_from_brings_an_older_folder_over(tmp_path):
    old = Library(tmp_path / "Documents")
    kept = old.create("Sections", "sections")
    old.create("Dual", "dual-meet")
    old.update_settings(team="Lakeview", pool_lanes=6)
    (old.team_dir / "logo.png").write_bytes(b"png")
    (old.root / "loop-builder.log").write_text("log")
    new = Library(tmp_path / "Application Support")
    here = new.create("Sections", "blank")  # already here: the moved one is told apart
    assert new.move_from(old.root) == 2
    names = sorted(e["slug"] for e in new.events())
    assert names == sorted([here, f"{kept} (2)", "Dual"])
    settings = new.settings()
    assert settings["team"] == "Lakeview" and settings["pool_lanes"] == 6 and settings["documents_checked"]
    assert (new.team_dir / "logo.png").read_bytes() == b"png"
    assert not (old.root / "Events").exists() and (old.root / "loop-builder.log").exists()  # the rest stays
    with pytest.raises(LibraryError):
        new.move_from(old.root)  # nothing left to bring over


def test_importing_a_renamed_events_package_tells_the_copy_apart(lib, tmp_path):
    """A renamed event keeps its first folder: checking folder names alone, the first import shared its name."""
    slug = lib.create("Round 4", "blank")
    path = lib.event_file(slug)
    path.write_text(
        path.read_text(encoding="utf-8").replace("event: Round 4", "event: Round 4 renamed"), encoding="utf-8"
    )
    package = lib.export_package(slug, tmp_path / "Round 4 renamed")
    names = [load_event(lib.event_file(lib.import_package(package))).name for _ in range(2)]
    assert names == ["Round 4 renamed (2)", "Round 4 renamed (3)"]


@pytest.mark.parametrize(
    "text",
    [
        "- just\n- a list\n",
        "event: Bad\nloops: [1, 2]\n",
        "event: Bad\nloops: [\n",
        "event: Bad\nloops:\n  - name: a\n    slides: 3\n",
    ],
)
def test_a_malformed_event_file_is_left_out_and_explained(lib, text):
    """A hand-edited or half-synced file used to take the whole events home down (500) with it."""
    lib.create("Good", "blank")
    (lib.events_dir / "Bad").mkdir()
    (lib.events_dir / "Bad" / "event.yaml").write_text(text, encoding="utf-8")
    assert [e["name"] for e in lib.events()] == ["Good"]
    api = TestClient(create_app(library=lib), base_url="http://127.0.0.1")  # the app answers only its own host
    assert api.get("/api/home").status_code == 200
    res = api.post("/api/events/Bad/open")
    assert res.status_code == 422 and "Bad" in res.json()["detail"]  # an EventError naming the file, not a 500


def test_a_slide_whose_settings_are_a_list_says_so(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("event: x\nloops:\n  - name: a\n    slides:\n      - card: [1, 2]\n", encoding="utf-8")
    with pytest.raises(EventError, match="loop 1 \\(a\\), slide 1: a card's settings"):
        load_event(path)


def test_the_command_line_reports_a_malformed_file_without_a_traceback(tmp_path, monkeypatch, capsys):
    path = tmp_path / "bad.yaml"
    path.write_text("event: x\nloops: [\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["loopgen", str(path), "--check"])
    assert cli() == 1
    err = capsys.readouterr().err
    assert err.startswith("error: ") and "(line 3)" in err and "Traceback" not in err


@pytest.mark.parametrize("text", ["- just\n- a list\n", "event: Bad\nloops: [1]\n"])
def test_a_malformed_package_or_event_is_refused_not_half_made(lib, tmp_path, text):
    package = tmp_path / "bad.loopevent"
    with zipfile.ZipFile(package, "w") as z:
        z.writestr("event.yaml", text)
    with pytest.raises(LibraryError, match="isn.t a Loop Builder event"):
        lib.import_package(package)
    assert not list(lib.events_dir.iterdir())  # nothing unpacked
    (lib.events_dir / "Bad").mkdir()
    (lib.events_dir / "Bad" / "event.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(LibraryError):
        lib.duplicate("Bad", "Copy")
    assert [p.name for p in lib.events_dir.iterdir()] == ["Bad"]  # no half-made copy


def test_template_panels_need_a_panel_each(tmp_path):
    path = tmp_path / "panels.yaml"
    path.write_text("event: x\ntemplate_panels: {Welcome.tpl: 1}\nloops: []\n", encoding="utf-8")
    with pytest.raises(EventError, match="template_panels: Welcome.tpl needs a 'panel'"):
        load_event(path)


def test_the_command_line_refuses_slide_zero(monkeypatch, capsys):
    event = Path(__file__).resolve().parent.parent / "examples" / "dual-meet" / "event.yaml"
    monkeypatch.setattr("sys.argv", ["loopgen", str(event), "--slide-png", "Raffle", "0", "out.png"])
    with pytest.raises(SystemExit):
        cli()
    assert "whole number from 1" in capsys.readouterr().err


def test_only_the_macs_own_folder_offers_the_documents_one(tmp_path, monkeypatch):
    from app import library  # pylint: disable=import-outside-toplevel

    monkeypatch.delenv("LOOPBUILDER_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(library.sys, "platform", "darwin")
    assert library.old_mac_folder(library.default_root()) == tmp_path / "Documents" / "Loop Builder"
    assert library.old_mac_folder(tmp_path / "elsewhere") is None
    monkeypatch.setenv("LOOPBUILDER_HOME", str(tmp_path / "elsewhere"))  # a tester's throwaway folder
    assert library.old_mac_folder(library.default_root()) is None
    monkeypatch.delenv("LOOPBUILDER_HOME")
    monkeypatch.setattr(library.sys, "platform", "win32")  # Windows keeps Documents: nothing to bring over
    monkeypatch.setattr(library, "windows_documents", lambda: None)
    assert library.old_mac_folder(library.default_root()) is None


def test_move_from_adds_saved_teams_and_tells_events_apart(tmp_path):
    old = Library(tmp_path / "Documents")
    old.create("Meet", "blank")
    old.teams_dir.mkdir(parents=True)
    (old.teams_dir / "teams.json").write_text(
        '[{"id": "lakeview", "name": "Lakeview", "logo": "lakeview.png"},'
        ' {"id": "riverside", "name": "Riverside", "logo": "riverside.png"}]',
        encoding="utf-8",
    )
    for team in ("lakeview", "riverside"):
        (old.teams_dir / f"{team}.png").write_bytes(b"png")
    new = Library(tmp_path / "Application Support")
    new.create("Meet", "blank")
    new.teams_dir.mkdir(parents=True)  # a team added before bringing the old folder over
    (new.teams_dir / "teams.json").write_text('[{"id": "lakeview", "name": "Lakeview Otters", "logo": "lakeview.png"}]')
    (new.teams_dir / "lakeview.png").write_bytes(b"new")
    new.move_from(old.root)
    assert sorted(t["name"] for t in new.teams()) == ["Lakeview", "Lakeview Otters", "Riverside"]
    assert (new.teams_dir / "lakeview.png").read_bytes() == b"new"  # the one here is untouched
    assert sorted(e["name"] for e in new.events()) == ["Meet", "Meet (2)"]


def test_move_from_fills_in_settings_this_folder_still_has_at_their_defaults(tmp_path):
    """The template folder is often picked before the events are brought over; that choice stays, the rest comes."""
    old = Library(tmp_path / "Documents")
    old.create("Sections", "sections")
    old.update_settings(team="Lakeview", pool_lanes=6, templates=str(tmp_path / "old-boards"))
    new = Library(tmp_path / "Application Support")
    new.update_settings(templates=str(tmp_path), pool_lanes=10)  # chosen here first: kept
    assert new.move_from(old.root) == 1
    settings = new.settings()
    assert settings["team"] == "Lakeview" and settings["pool_lanes"] == 10 and settings["templates"] == str(tmp_path)
    assert settings["documents_checked"] and not (old.root / "settings.json").exists()


def test_windows_uses_the_documents_explorer_shows_unless_one_is_already_in_use(tmp_path, monkeypatch):
    """OneDrive's folder backup moves Documents to OneDrive › Documents; <user folder>\\Documents isn't where people
    look then. A Loop Builder folder an earlier version made there stays in use, so no events go missing."""
    from app import library  # pylint: disable=import-outside-toplevel

    monkeypatch.delenv("LOOPBUILDER_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(library.sys, "platform", "win32")
    monkeypatch.setattr(library, "windows_documents", lambda: tmp_path / "OneDrive" / "Documents")
    assert library.default_root() == tmp_path / "OneDrive" / "Documents" / "Loop Builder"
    (tmp_path / "Documents" / "Loop Builder" / "Events").mkdir(parents=True)  # made empty, e.g. by an offline launch
    assert library.default_root() == tmp_path / "OneDrive" / "Documents" / "Loop Builder"  # not enough to stay
    Library(tmp_path / "Documents" / "Loop Builder").create("Sections", "blank")  # events from 0.1.7 or earlier
    assert library.default_root() == tmp_path / "Documents" / "Loop Builder"


def test_the_documents_folder_id_is_the_one_windows_documents():
    """FOLDERID_Documents, {FDD39AD0-238F-46AF-ADB4-6C85480369C7}: checked byte for byte, on any system."""
    import uuid  # pylint: disable=import-outside-toplevel
    from app import library  # pylint: disable=import-outside-toplevel

    assert bytes(library.FOLDERID_DOCUMENTS) == uuid.UUID("FDD39AD0-238F-46AF-ADB4-6C85480369C7").bytes_le


@pytest.mark.skipif(sys.platform != "win32", reason="asks Windows itself")
def test_windows_says_where_documents_is():
    from app import library  # pylint: disable=import-outside-toplevel

    documents = library.windows_documents()
    assert documents is not None and documents.is_dir()
