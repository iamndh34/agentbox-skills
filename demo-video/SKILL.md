---
name: demo-video
description: >
  Record a real desktop application on THIS machine into a finished demo video: launch it under
  X11/XWayland, drive it with injected mouse and keyboard the way a person would, capture its window
  with ffmpeg, and cut the takes into an mp4 with voice-over and captions. Use it when asked to
  demo, record, film or screen-capture an app, a desktop workflow, or a product walkthrough that has
  to show the real thing. For a website or a web app use the browser instead, and for a video built
  from generated visuals rather than a live screen use hyperframes.
---

# Recording a real app

The video is evidence: every pixel in it is the app doing the thing, driven by
the same events a person's mouse and keyboard produce. Nothing is injected into
the app and nothing on screen is edited. Only time is changed, and it shows — a
marked wait is played at 2x with a badge.

## 0. This runs on the host, not in the sandbox

Every command here goes through `execute_command_unsandboxed`. The first one
raises a card; answer it with "don't ask again" for `python record.py *` and
the rest of the session is quiet.

**Do not try it in the sandbox first.** A graphical app cannot start there —
no display, no memfd — and no workaround changes that. Five relaunches with
`HOME` moved and a cursor theme set is what that looks like when someone tries
anyway (2026-09-27); the sandbox now says so in one line and offers the card.

## 1. Requirements, checked before anything is recorded

    agentbox install pytools    # python-xlib, pynput, Pillow, edge-tts
    ffmpeg -version | head -1

Everything here runs on the Python runtime the product provisions,
`~/.agentbox/pytools/bin/python` — not a venv of your own. That is where the
screen driver's packages already live, and installing a second interpreter
beside it means two runtimes to keep working and only one that `hachimi
doctor` can vouch for.

`hachimi doctor` names whichever piece is missing: the `media:` line covers
ffmpeg and the voice, the `screen:` line covers the display and the driver's
packages. The session must be X11 or Wayland-with-XWayland; a pure Wayland
session cannot be driven at all, because the protocol has no way for one
client to drive another window.

## 1b. Where the scripts are, and where the demo lives

This skill's directory is READ-ONLY — the line injected above the text names
its absolute path. The demo is not built there; copy the scripts into the
working directory that will hold the takes:

    cp <skill dir>/scripts/xdrive.py <skill dir>/scripts/render.py .
    cp <skill dir>/scripts/record.example.py record.py

`out/` and `narration.<lang>.json` then sit beside them, which is the layout
both scripts expect. (`render.py` can instead be run in place with
`PROJECT_DIR=$PWD`; `record.py` cannot, because it imports `xdrive` from its
own directory.)

## 2. Launch the app so it can be seen

    GDK_BACKEND=x11 <the app's command>

GTK and Tauri apps pick Wayland by default, and a Wayland-native window is
invisible to this skill — `list_windows` will not show it and `x11grab` cannot
read it. Electron and Chrome are already X11. Add `GTK_CSD=0` if the app draws
its own title bar and you want the window to be the content alone.

Then place it, before anything is captured:

    app = App("part of the window title")
    app.fit(1280, 800)        # must fit ON the screen; x11grab fails at the edge

## 3. Look before you script

Take one screenshot, open it, and read the coordinates off the picture:

    app.img(Path("out/probe.png"))

Every coordinate in the shot list has to come from a picture somebody looked
at. A guessed coordinate is a click that lands somewhere else on the next
machine, and the video will show it landing there.

After each action, `app.wait_still()` — it waits for the window to stop
changing, which is how long the app actually took rather than how long you
guessed.

## 4. The shot list

Work in the `record.py` copied in §1b and replace the shots. One function per shot,
one take per function, `--only 03` to retake one. Each take writes its video
and a small JSON beside it: the moments you marked, and the stretches you
marked `fast`.

Mark generously. The marks are what let the renderer play a wait at speed or
cut a title in at the moment something appeared, without anyone re-watching
footage with a stopwatch.

## 5. Narration and render

Write `narration.<lang>.json` AFTER watching the takes — every number or label
the voice says has to be on screen in that shot. Then:

    ~/.agentbox/pytools/bin/python render.py

Cards + takes + edge-tts voice + burned-in captions → `out/final.mp4`.

**Check it with the machine, not with the log.** `ffprobe` the duration, then
read back a frame from the middle of each shot and say what is in it. A render
that printed no error and produced a black video prints no error.

## 5b. The other way to record: the screen driver

The `computer` MCP server has `record_start`, `record_stop` and
`record_status`, capturing the same window through the same ffmpeg. Use those
when you are driving the app by hand — looking, clicking, checking — and the
recording is one span around it.

Use the scripts above when the demo is a SHOT LIST: sixty clicks through a
tool is sixty round trips to a model, and a script is one command. The two are
not alternatives to choose between once; they answer different questions.

## 6. When to hand off to hyperframes

The takes are footage. If the piece needs motion graphics, animated callouts or
a designed intro around them, give hyperframes the take files and let it build
the composition. Two routes, and no third: this skill's own `render.py` for a
straight demo with voice and captions, or hyperframes for a designed one.

## 7. Data and credentials

Seed a demo state rather than filming real data — a mock backend where the real
one holds real records.

**Never type a credential.** `list_secrets` names what this machine holds, and
`{{secret:NAME}}` in a tool argument spends one without it ever reaching the
conversation or the ledger. If the name you need is not there, ask the person
to run `hachimi secret set <NAME>` and to tell you the NAME only.

## 8. Traps that have cost real time

- **A Wayland-native window is invisible.** If `list_windows` is empty while
  the app is plainly on screen, it was not started with `GDK_BACKEND=x11`.
- **`dconf-CRITICAL` lines are noise**, not the failure. The failure is the
  line after them.
- **The window must stay on screen.** `x11grab` of a window crossing the edge
  fails with `BadMatch`; `app.fit()` sizes it to fit.
- **One recording is one take.** Do not try to stitch while recording; retake.
- **edge-tts needs the network.** It runs on the host here, so that is fine —
  but it is the one step that fails with no internet.
- **A model's answer is not a take.** If the app shows something wrong, reseed
  and record the shot again rather than editing around it.
