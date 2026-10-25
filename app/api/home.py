"""The events home, Settings, Teams and Pictures: creating, opening, importing and deleting events."""

import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from loopgen import load_event
from loopgen.event import DEFAULT_THEME, Event, EventError, Loop, _slide, read_event_file
from loopgen.loops import render_slide
from loopgen.slides import MissingAsset, Renderer
from loopgen.uploads import UploadError, prepare_upload

from app.library import STARTERS, LibraryError, default_exports, old_mac_folder
from app.version import COPYRIGHT, PROJECT_URL, RELEASES_URL, VERSION
from app.api.state import legal_text, look_colours, png, template_folder_status
from app.api.models import LookBody, NewEventBody, PathBody, SavePictureBody, SettingsBody


def register(app, ctx):
    """The events home's routes, Settings', and the team and picture libraries'."""
    s, lib, current, jobs, update, folder_override, open_event, library_call, event_file_path = (
        ctx.s,
        ctx.lib,
        ctx.current,
        ctx.jobs,
        ctx.update,
        ctx.folder_override,
        ctx.open_event,
        ctx.library_call,
        ctx.event_file_path,
    )

    @app.get("/api/home")
    def home():
        settings = lib.settings()
        folder = template_folder_status(settings["templates"])
        events, unreadable = lib.scan_events()  # the check Settings makes as a folder is typed
        return {
            "settings": {k: settings[k] for k in ("team", "templates", "export_dir", "pool_lanes", "first_lane")}
            | {"logo": bool(settings["logo"]), "theme": lib.team_look()},
            "templates_found": folder["found"],
            "template_count": folder["count"],
            "events": events,
            "unreadable": unreadable,  # left out of events: the home says so
            "starters": [{"id": k, "title": v["title"], "about": v["about"]} for k, v in STARTERS.items()],
            "open": current.session.path.parent.name if current.session else None,
            "folder": str(lib.root),
            "exports": str(default_exports(lib.root)),
            # a Mac with the folder in Application Support: offer the Documents › Loop Builder of 0.1.6 and earlier
            "offer_documents": bool(old_mac_folder(lib.root)) and not settings.get("documents_checked"),
            "version": VERSION,
            "update": update or None,
        }

    @app.get("/api/about")
    def about():
        return {
            "version": VERSION,
            "copyright": COPYRIGHT,
            "project": PROJECT_URL,
            "update_check": bool(RELEASES_URL),
            "notices": legal_text("THIRD_PARTY_NOTICES.md"),
        }

    @app.post("/api/library/move-documents")
    def move_documents():
        """Bring the events, team logos and settings of 0.1.6 and earlier over from Documents › Loop Builder.
        Only when asked: looking in Documents is what makes macOS ask for permission."""
        old = old_mac_folder(lib.root)
        if old is None:  # not the Mac's own folder (another OS, or LOOPBUILDER_HOME): nothing is ever pulled in
            raise HTTPException(404, "There's nothing to bring over into this Loop Builder folder.")
        try:
            found = (old / "Events").is_dir()
        except PermissionError:
            found = True  # macOS said no; the move below says so in words
        if not found:
            lib.update_settings(documents_checked=True)
            raise HTTPException(404, f"There's no Loop Builder folder in Documents ({old}).")
        try:
            return {"moved": lib.move_from(old)}
        except PermissionError as exc:
            raise HTTPException(
                422,
                "macOS didn't let Loop Builder open your Documents folder. Allow it in System Settings › "
                "Privacy & Security › Files and Folders, then try again.",
            ) from exc
        except (LibraryError, OSError) as exc:
            raise HTTPException(422, f"couldn't move the events: {exc}") from exc

    @app.post("/api/library/documents-checked")
    def documents_checked():
        """No events to bring over from Documents: stop offering."""
        lib.update_settings(documents_checked=True)
        return {"ok": True}

    @app.put("/api/settings")
    def save_settings(body: SettingsBody):
        changes = body.model_dump(exclude_none=True)
        if "pool_lanes" in changes and not 1 <= changes["pool_lanes"] <= 10:
            raise HTTPException(422, "a pool has 1 to 10 lanes")
        if "first_lane" in changes and changes["first_lane"] not in (0, 1):
            raise HTTPException(422, "lanes are numbered from 0 or 1")
        if "templates" in changes and changes["templates"] and not Path(changes["templates"]).expanduser().is_dir():
            raise HTTPException(422, f"folder not found: {changes['templates']}")
        if "theme" in changes:
            changes["theme"] = look_colours(changes["theme"])
        before = lib.settings().get("templates")
        settings = lib.update_settings(**changes)
        if current.session and settings.get("templates") != before:
            with current.session.lock:
                current.session.reload()  # redraw boards from the new folder; undo history stays
        return settings

    @app.post("/api/settings/preview")
    def preview_look(body: LookBody):
        """A sample welcome card in some colours and the team logo, drawn by the real renderer."""
        logo = lib.team_logo()
        theme = {**DEFAULT_THEME, **lib.team_look(), **look_colours(body.theme), "logo": str(logo) if logo else None}
        card = _slide(
            {
                "card": {
                    "layout": "logo-center" if logo else "stack",
                    "lines": [
                        {"text": "Welcome", "size": "M", "style": "outlined"},
                        {"text": "VISITING TEAM", "size": "L", "style": "outlined"},
                        {"text": "Thanks for swimming with us!", "size": "S"},
                    ],
                }
            },
            "preview",
        )
        event = Event("Preview", lib.root / "preview.yaml", 320, 176, theme, [], lib.root)
        try:
            img = render_slide(event, Loop("Preview", [card]), 0, None, Renderer(event))
        except (MissingAsset, ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return Response(png(img, 2), media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/api/settings/logo")
    def team_logo(file: UploadFile):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / Path(file.filename or "logo").name
            src.write_bytes(file.file.read())
            try:
                lib.set_logo(prepare_upload(src, Path(tmp) / "shrunk"))
            except UploadError as exc:
                raise HTTPException(422, str(exc)) from exc
        return {"ok": True}

    @app.get("/api/teams")
    def list_teams():
        return lib.teams()

    @app.post("/api/teams")
    def add_team(file: UploadFile, name: str = Form(...), trim: bool = Form(True)):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / Path(file.filename or "logo").name
            src.write_bytes(file.file.read())
            try:
                team_id = lib.add_team(name, src, trim)
            except (LibraryError, UploadError) as exc:
                raise HTTPException(422, str(exc)) from exc
        return {"id": team_id}

    @app.put("/api/teams/{team_id}")
    def rename_team(team_id: str, body: NewEventBody):
        library_call(lib.rename_team, team_id, body.name)
        return {"ok": True}

    @app.delete("/api/teams/{team_id}")
    def delete_team(team_id: str):
        library_call(lib.delete_team, team_id)
        return {"ok": True}

    @app.get("/api/teams/{team_id}/logo")
    def team_logo_png(team_id: str):
        team = next((t for t in lib.teams() if t["id"] == team_id), None)
        if team is None:
            raise HTTPException(404, "no such team")
        return FileResponse(lib.team_logo_path(team), headers={"Cache-Control": "no-store"})

    @app.post("/api/teams/{team_id}/use")
    def use_team(team_id: str):
        """Copy a team's logo into the open event, for a lane; returns the lane's name and logo path."""
        return library_call(lib.use_team, team_id, s.path.parent)

    # Pictures kept for every event (badges, league logos, the duck). Not /api/pictures: that's an event upload.
    @app.get("/api/library/pictures")
    def list_pictures():
        return lib.pictures()

    @app.post("/api/library/pictures")
    def save_picture(file: UploadFile, name: str = Form(...), trim: bool = Form(False)):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / Path(file.filename or "picture").name
            src.write_bytes(file.file.read())
            try:
                return {"id": lib.add_picture(name, src, trim)}
            except (LibraryError, UploadError) as exc:
                raise HTTPException(422, str(exc)) from exc

    @app.post("/api/library/pictures/from-event")
    def save_event_picture(body: SavePictureBody):
        """Keep a picture the open event already has (e.g. its assets/duck.png) in Pictures."""
        try:
            picture_id = lib.add_picture(body.name, event_file_path(body.path), replace=False)
            return {"id": picture_id, "name": next(p["name"] for p in lib.pictures() if p["id"] == picture_id)}
        except (LibraryError, UploadError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.put("/api/library/pictures/{picture_id}")
    def rename_picture(picture_id: str, body: NewEventBody):
        library_call(lib.rename_picture, picture_id, body.name)
        return {"ok": True}

    @app.delete("/api/library/pictures/{picture_id}")
    def delete_picture(picture_id: str):
        library_call(lib.delete_picture, picture_id)
        return {"ok": True}

    @app.get("/api/library/pictures/{picture_id}/image")
    def picture_image(picture_id: str):
        try:
            path = lib.picture_path(picture_id)
        except LibraryError as exc:
            raise HTTPException(404, str(exc)) from exc
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    @app.post("/api/library/pictures/{picture_id}/use")
    def use_picture(picture_id: str):
        """Copy a saved picture into the open event; returns its path there for the slide."""
        return library_call(lib.use_picture, picture_id, s.path.parent)

    @app.get("/api/team/logo")
    def team_logo_file():
        logo = lib.settings().get("logo")
        if not logo or not (lib.root / logo).exists():
            raise HTTPException(404, "no team logo yet")
        return FileResponse(lib.root / logo, headers={"Cache-Control": "no-store"})

    @app.post("/api/events")
    def new_event(body: NewEventBody):
        slug = library_call(lib.create, body.name, body.starter, body.date)
        if body.visitor:
            library_call(lib.set_visitor, slug, body.visitor)
        return {"slug": slug}

    @app.post("/api/events/{slug}/duplicate")
    def duplicate_event(slug: str, body: NewEventBody):
        return {"slug": library_call(lib.duplicate, slug, body.name, body.date)}

    @app.post("/api/events/{slug}/open")
    def open_slug(slug: str):
        path = library_call(lib.event_file, slug)
        try:
            open_event(path)
        except EventError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"ok": True}

    @app.delete("/api/events/{slug}")
    def delete_event(slug: str):
        """Delete an event's folder. If it's the open event, the editor closes it first."""
        path = library_call(lib.event_file, slug)
        session = current.session
        if session and session.path == path:
            with session.lock:
                if any(job["state"] == "running" for job in jobs.values()):
                    raise HTTPException(409, "this event is still exporting")
                current.session = None
        library_call(lib.delete, slug)
        return {"ok": True}

    @app.get("/api/events/{slug}/thumb.png")
    def event_thumb(slug: str):
        """The event's first slide, for its row on the home screen."""
        try:
            path = library_call(lib.event_file, slug)
            own = read_event_file(path).get("templates")
            event = load_event(path, folder_override or (None if own else lib.settings().get("templates")))
            first = event.loops[0].slides[0]
            img = render_slide(event, event.loops[0], 0, 3.0 if first.type == "crawl" else None)
        except (EventError, MissingAsset, ValueError, KeyError, IndexError):
            return Response(status_code=204)
        return Response(png(img), media_type="image/png", headers={"Cache-Control": "no-store"})

    def import_from(package):
        try:
            return {"slug": lib.import_package(package)}
        except (LibraryError, OSError, zipfile.BadZipFile) as exc:
            raise HTTPException(422, f"couldn't import: {exc}") from exc

    @app.post("/api/events/import")
    def import_event(file: UploadFile):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / Path(file.filename or "event.loopevent").name
            package.write_bytes(file.file.read())
            return import_from(package)

    @app.post("/api/events/import-file")
    def import_event_file(body: PathBody):
        """Import a .loopevent picked with the app's own Open dialog."""
        return import_from(Path(body.path).expanduser())

    @app.post("/api/events/{slug}/package")
    def save_package(slug: str, body: PathBody):
        return {"file": str(library_call(lib.export_package, slug, Path(body.path).expanduser()))}

    @app.get("/api/events/{slug}/package")
    def download_package(slug: str):
        tmp = Path(tempfile.mkdtemp())
        try:
            dest = library_call(lib.export_package, slug, tmp / slug)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        # the zip is only on its way to the browser: its folder goes once it's sent
        cleanup = BackgroundTask(shutil.rmtree, tmp, ignore_errors=True)
        return FileResponse(dest, filename=dest.name, media_type="application/zip", background=cleanup)
