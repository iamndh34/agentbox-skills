"""Drives a real X11 window: find it, place it, look at it, click and type into it.

The app runs under XWayland (GDK_BACKEND=x11) so that input can be injected
with XTest and the window captured with ffmpeg x11grab — no extra system
package, and nothing inside the app changes. Every action here is what a person
at the keyboard would do; nothing reaches into the app's state, which is what
makes the recording evidence rather than a re-enactment.

Wayland-native windows are invisible to this file, by design of the protocol:
one client cannot drive another. That is why the app is launched with
GDK_BACKEND=x11 — see SKILL.md, step 1.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageChops
from pynput.keyboard import Controller as Keys, Key
from pynput.mouse import Button, Controller as Mouse
from Xlib import X, display
from Xlib.protocol import event

os.environ.setdefault("DISPLAY", ":0")

_mouse = Mouse()
_keys = Keys()


def find_window(title: str, timeout: float = 60.0):
    """The top-level X window whose name contains `title`, waiting for it to appear."""
    d = display.Display()
    deadline = time.time() + timeout
    while time.time() < deadline:
        root = d.screen().root
        stack, hits = [root], []
        while stack:
            w = stack.pop()
            try:
                name = w.get_wm_name() or ""
                attrs = w.get_attributes()
            except Exception:
                continue
            if title in str(name) and attrs.map_state == X.IsViewable:
                hits.append(w)
            try:
                stack.extend(w.query_tree().children)
            except Exception:
                pass
        if hits:
            # With server-side decorations (GTK_CSD=0) the same title is on the
            # app's client window and on mutter's frame around it, whose
            # invisible resize border changes size between launches. Take the
            # client (the smaller one): it is exactly the webview.
            return d, min(hits, key=lambda w: w.get_geometry().width * w.get_geometry().height)
        time.sleep(0.5)
    raise TimeoutError(f"no window titled {title!r}")


def activate(title: str) -> None:
    """Raises and focuses the window the way a click on its taskbar entry would."""
    d, win = find_window(title, timeout=5)
    root = d.screen().root
    ev = event.ClientMessage(window=win, client_type=d.intern_atom("_NET_ACTIVE_WINDOW"),
                             data=(32, [2, X.CurrentTime, 0, 0, 0]))
    root.send_event(ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
    d.flush()
    time.sleep(0.3)


def move(x: int, y: int, duration: float = 0.45) -> None:
    """Glides the pointer to (x, y) so the viewer can follow it."""
    sx, sy = _mouse.position
    steps = max(1, int(duration * 60))
    for i in range(1, steps + 1):
        t = i / steps
        e = t * t * (3 - 2 * t)  # smoothstep
        _mouse.position = (int(sx + (x - sx) * e), int(sy + (y - sy) * e))
        time.sleep(duration / steps)


def click(x: int, y: int, pause: float = 0.35) -> None:
    move(x, y)
    time.sleep(0.12)
    _mouse.click(Button.left, 1)
    time.sleep(pause)


def scroll(x: int, y: int, clicks: int, pause: float = 0.05) -> None:
    """Wheel-scrolls at (x, y): positive is down."""
    move(x, y, 0.3)
    for _ in range(abs(clicks)):
        _mouse.scroll(0, -1 if clicks > 0 else 1)
        time.sleep(pause)


def type_text(text: str, cps: float = 14.0) -> None:
    """Types like a person: a steady pace, not a paste."""
    for ch in text:
        _keys.type(ch)
        time.sleep(1.0 / cps)


def press(key: str) -> None:
    k = getattr(Key, key)
    _keys.press(k)
    _keys.release(k)
    time.sleep(0.15)


def hotkey(*keys: str) -> None:
    ks = [getattr(Key, k) if hasattr(Key, k) else k for k in keys]
    for k in ks:
        _keys.press(k)
    for k in reversed(ks):
        _keys.release(k)
    time.sleep(0.2)


def fingerprint(img: Image.Image) -> str:
    return hashlib.sha1(img.convert("L").resize((240, 135)).tobytes()).hexdigest()


def changed(a: Image.Image, b: Image.Image) -> bool:
    return ImageChops.difference(a.convert("L"), b.convert("L")).getbbox() is not None


class App:
    """The app window's CONTENT area (below the title bar, inside the shadow).

    XWayland is rootless under GNOME, so the root window cannot be read; the
    app's own window can. Coordinates handed to click() are content pixels —
    the same pixels a screenshot from img() shows — and are mapped to the
    screen through the window's live position.
    """

    # With GTK_CSD=0 the client window is the webview alone; the title bar
    # belongs to the compositor's frame, outside what is captured. An app that
    # draws its own title bar needs TITLE set to its height instead.
    MARGIN = 0
    TITLE = 0

    def __init__(self, title: str):
        """title is matched as a SUBSTRING of the window name, so the shortest
        distinctive part of it is the right thing to pass."""
        self.title = title

    def _win(self):
        return find_window(self.title, timeout=10)

    def fit(self, w: int = 1920, h: int = 1080, x: int = 0, y: int = 40) -> tuple[int, int]:
        """Sizes the window so its content area is w x h, correcting by measurement.

        The window must stay entirely on screen: x11grab of a window that
        crosses the screen edge fails with BadMatch under XWayland. With the
        client-side shadow off (GTK_CSD=0) a 1920x1080 content area fits a
        1920x1200 screen with its header bar. On a smaller screen, ask for a
        size that fits: a window pushed off the edge cannot be recorded.
        """
        d, win = self._win()
        root = d.screen().root
        flags = (1 << 8) | (1 << 9) | (1 << 10) | (1 << 11) | 10
        rw, rh = w, h
        for _ in range(4):
            ev = event.ClientMessage(window=win, client_type=d.intern_atom("_NET_MOVERESIZE_WINDOW"),
                                     data=(32, [flags, x, y, rw, rh]))
            root.send_event(ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
            d.flush()
            time.sleep(1.0)
            _, _, cw, ch = self.content_box()
            if (cw, ch) == (w, h):
                break
            rw, rh = rw + (w - cw), rh + (h - ch)
        return self.content_box()[2:]

    def content_box(self) -> tuple[int, int, int, int]:
        """(x, y, w, h) of the content area inside the window image."""
        _, win = self._win()
        g = win.get_geometry()
        top = self.MARGIN + self.TITLE
        # The window manager rounds sizes by a few pixels; the frame the video
        # uses is fixed, so clamp to it.
        return (self.MARGIN, top, min(1920, g.width - 2 * self.MARGIN),
                min(1080, g.height - top - self.MARGIN))

    def origin(self) -> tuple[int, int]:
        """Screen position of the content area's top-left pixel."""
        d, win = self._win()
        t = win.translate_coords(d.screen().root, 0, 0)
        x, y, _, _ = self.content_box()
        return -t.x + x, -t.y + y

    def img(self, path: Path | None = None) -> Image.Image:
        """A screenshot of the content area."""
        _, win = self._win()
        g = win.get_geometry()
        raw = win.get_image(0, 0, g.width, g.height, X.ZPixmap, 0xFFFFFFFF)
        full = Image.frombytes("RGB", (g.width, g.height), raw.data, "raw", "BGRX")
        x, y, w, h = self.content_box()
        img = full.crop((x, y, x + w, y + h))
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            img.save(path)
        return img

    def click(self, x: int, y: int, pause: float = 0.4) -> None:
        ox, oy = self.origin()
        click(ox + x, oy + y, pause)

    def move(self, x: int, y: int, duration: float = 0.45) -> None:
        ox, oy = self.origin()
        move(ox + x, oy + y, duration)

    def scroll(self, x: int, y: int, clicks: int) -> None:
        ox, oy = self.origin()
        scroll(ox + x, oy + y, clicks)

    def wait_still(self, box: tuple[int, int, int, int] | None = None, quiet: float = 2.5,
                   timeout: float = 120.0, poll: float = 0.5) -> float:
        """Waits until the content (or a box of it) stops changing for `quiet` seconds."""
        def grab():
            im = self.img()
            return im.crop(box) if box else im
        start = time.time()
        last = fingerprint(grab())
        still_since = time.time()
        while time.time() - start < timeout:
            time.sleep(poll)
            cur = fingerprint(grab())
            if cur != last:
                last, still_since = cur, time.time()
            elif time.time() - still_since >= quiet:
                return time.time() - start
        raise TimeoutError(f"content still changing after {timeout}s")

    def recorder(self, dest: Path) -> "WindowRecorder":
        return WindowRecorder(self, dest)


class WindowRecorder:
    """ffmpeg capture of the app window by id, cropped to the content area."""

    def __init__(self, app: App, dest: Path):
        self.app, self.dest = app, dest
        self.proc: subprocess.Popen | None = None
        self.t0 = 0.0

    def __enter__(self) -> "WindowRecorder":
        self.dest.parent.mkdir(parents=True, exist_ok=True)
        _, win = self.app._win()
        x, y, w, h = self.app.content_box()
        self.proc = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-draw_mouse", "1", "-framerate", "30",
             "-window_id", hex(win.id), "-i", os.environ["DISPLAY"],
             "-vf", f"crop={w - w % 2}:{h - h % 2}:{x}:{y}",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12", "-pix_fmt", "yuv420p", str(self.dest)],
            stdin=subprocess.PIPE)
        time.sleep(1.0)
        self.t0 = time.time()
        return self

    def now(self) -> float:
        """Seconds on the take's own timeline."""
        return time.time() - self.t0 + 1.0

    def __exit__(self, *exc) -> None:
        time.sleep(0.6)
        if self.proc and self.proc.stdin:
            self.proc.stdin.write(b"q")
            self.proc.stdin.flush()
            self.proc.wait(timeout=30)


def app_type(app: App, text: str, cps: float = 14.0) -> None:
    """Types into the app after making sure its window has keyboard focus.

    XTest key events go to whichever window is focused; without this, text
    meant for the app lands wherever the person at the machine last clicked.
    """
    activate(app.title)
    type_text(text, cps)
