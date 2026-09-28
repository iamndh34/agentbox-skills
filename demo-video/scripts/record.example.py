"""The shot list: one function per shot, one take per function.

Copy this beside your own project, replace the shots, and run it. What it is
for is the SHAPE — a take is a recording plus the moments inside it, and a
shot is a thing a person would do — not the particular clicks below.

Usage (the app must already be running under GDK_BACKEND=x11):
  python record.py                 # every shot
  python record.py --only 02 03    # retake some shots
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import xdrive
from xdrive import App

HERE = Path(__file__).resolve().parent
TAKES = HERE / "out" / "takes"

# The window to drive, as a SUBSTRING of its title. Find it with the screen
# driver's `list_windows` while the app is on screen — not with xdotool, which
# is not installed on every machine this skill runs on.
APP_TITLE = "Calculator"


class Take:
    """One recorded shot: the video, and the moments inside it.

    The marks matter as much as the video: they are what lets the renderer
    play a wait at speed, or cut a title in at the moment something appeared,
    without anyone re-watching the footage with a stopwatch.
    """

    def __init__(self, app: App, shot: str, name: str):
        self.app = app
        self.dest = TAKES / f"{shot}-{name}.mkv"
        self.meta: dict = {"shot": shot, "name": name, "fast": [], "marks": {}}
        self.rec = None

    def __enter__(self) -> "Take":
        TAKES.mkdir(parents=True, exist_ok=True)
        # A retake replaces the previous file of the same shot, so `--only 03`
        # leaves one take per shot rather than two that disagree.
        for old in TAKES.glob(f"{self.meta['shot']}-*.mkv"):
            old.unlink()
            old.with_suffix(".json").unlink(missing_ok=True)
        self.rec = self.app.recorder(self.dest).__enter__()
        return self

    def mark(self, name: str) -> float:
        t = self.rec.now()
        self.meta["marks"][name] = round(t, 3)
        return t

    def fast(self, a: float, b: float) -> None:
        """A stretch the renderer may play at speed — a wait, a long scroll."""
        if b - a > 2.0:
            self.meta["fast"].append([round(a, 3), round(b, 3)])

    def __exit__(self, *exc) -> None:
        self.rec.__exit__(*exc)
        self.meta["duration_hint"] = round(self.rec.now(), 3)
        self.dest.with_suffix(".json").write_text(json.dumps(self.meta, indent=1))
        print(f"  take {self.dest.name}: marks {self.meta['marks']} fast {self.meta['fast']}")


def shot_01_open(app: App) -> None:
    """Show the app as a person finds it."""
    with Take(app, "01", "open") as take:
        take.mark("shown")
        time.sleep(2.0)


def shot_02_do_something(app: App) -> None:
    """One action, at a human pace.

    Every coordinate here came from LOOKING: app.img().save(...) once, open the
    picture, read the pixel. A coordinate nobody looked at is a click that
    lands somewhere else on another machine.
    """
    with Take(app, "02", "do-something") as take:
        app.click(300, 400)
        take.mark("clicked")
        # wait_still waits for the window to stop changing, which is how long
        # the app actually took rather than how long we guessed.
        app.wait_still(timeout=20.0)
        take.mark("settled")
        time.sleep(1.5)


SHOTS = {
    "01": shot_01_open,
    "02": shot_02_do_something,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None,
                    help="shot numbers to record; default all of them")
    args = ap.parse_args()

    app = App(APP_TITLE)
    # A window that crosses the screen edge cannot be recorded (x11grab fails
    # with BadMatch), so it is placed and sized before anything is captured.
    app.fit(1280, 800)
    xdrive.activate(APP_TITLE)
    time.sleep(1.0)

    for shot in sorted(SHOTS):
        if args.only and shot not in args.only:
            continue
        print(f"shot {shot}")
        SHOTS[shot](app)


if __name__ == "__main__":
    main()
