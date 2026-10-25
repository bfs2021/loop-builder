"""Render scoreboard loops from an event file: checks, then one WMV per loop (and/or PNG stills).

python -m loopgen EVENT.yaml --out DIR                 every loop
python -m loopgen EVENT.yaml --out DIR --loop NAME     one loop (name or 1-based number; repeatable)
python -m loopgen EVENT.yaml --out DIR --format png    one PNG per still slide (--format wmv png for both)
python -m loopgen EVENT.yaml --check                   checks only
python -m loopgen EVENT.yaml --slide-png LOOP N OUT.png [--at SECONDS]   one slide (N is 1-based)
python -m loopgen --prepare-upload PICTURE OUT_DIR     shrink a picture the way the app stores it in an event
"""

import argparse
import sys
from pathlib import Path

from loopgen import export_loop, export_pngs, load_event, render_slide, run_checks
from loopgen.event import EventError
from loopgen.slides import Renderer
from loopgen.uploads import UploadError, prepare_upload


def main():
    ap = argparse.ArgumentParser(
        prog="python -m loopgen", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("event", type=Path, nargs="?")
    ap.add_argument("--templates", type=Path, help="DisplayLink Plus template folder (overrides the event file)")
    ap.add_argument("--out", type=Path, help="folder for the exported files")
    ap.add_argument("--format", nargs="+", choices=["wmv", "png"], default=["wmv"], help="what to export")
    ap.add_argument("--loop", action="append", help="loop name or number (default: all)")
    ap.add_argument("--preview-mp4", action="store_true", help="also write a 4x MP4 for review")
    ap.add_argument("--check", action="store_true", help="run the checks and stop")
    ap.add_argument("--slide-png", nargs=3, metavar=("LOOP", "N", "OUT"), help="render one slide to a PNG")
    ap.add_argument("--at", type=float, help="with --slide-png: seconds into a timed or panning slide")
    ap.add_argument("--scale", type=int, default=1, help="with --slide-png: integer enlargement")
    ap.add_argument(
        "--prepare-upload",
        nargs=2,
        type=Path,
        metavar=("PICTURE", "OUT_DIR"),
        help="shrink and re-encode a picture as the app does when it is added",
    )
    args = ap.parse_args()
    if args.prepare_upload:
        try:
            print(prepare_upload(*args.prepare_upload))
        except UploadError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0
    if not args.event:
        ap.error("an event file is required")
    try:
        event = load_event(args.event, args.templates)
        if args.slide_png:
            loop, n, out = args.slide_png
            if not n.isdigit() or int(n) < 1:
                ap.error(f"--slide-png: the slide number is a whole number from 1, not {n!r}")
            img = render_slide(event, event.loop(loop), int(n) - 1, args.at)
            if args.scale > 1:
                img = img.resize((img.width * args.scale, img.height * args.scale), 0)
            img.save(out)
            print(out)
            return 0
        loops = [event.loop(k) for k in args.loop] if args.loop else event.loops
        issues = run_checks(event, loops)
        for issue in issues:
            print(issue, file=sys.stderr)
        if args.check:
            return 1 if any(i.level == "error" for i in issues) else 0
        if any(i.level == "error" for i in issues):
            print("not exported: fix the errors above", file=sys.stderr)
            return 1
        if not args.out:
            ap.error("--out is required to export")
        renderer = Renderer(event)
        for loop in loops:
            if "wmv" in args.format:
                for path in export_loop(event, loop, args.out, args.preview_mp4, renderer):
                    print(path)
            if "png" in args.format:
                pngs, skipped = export_pngs(event, loop, args.out, renderer)
                for path in pngs:
                    print(path)
                for n, why in skipped:
                    print(f"{loop.name}, slide {n}: no PNG ({why})", file=sys.stderr)
    except (EventError, FileNotFoundError, IndexError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
