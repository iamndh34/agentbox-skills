"""Assembles out/final.mp4 from the recorded takes, the narration and the cards.

Inputs (all under out/ except the narration):
  takes/NN-<name>.mkv + takes/NN-<name>.json  — written by record.py; the JSON
      carries the moments that matter inside the take (see WAIT below);
  narration.en.json                           — one entry per shot: id, text.
Output: out/final.mp4 (H.264 + AAC at the takes' own size); captions are burned
in (their sources stay in out/build/, so a caption can be read back).

Nothing on screen is edited. Two things are done to time only, and both show:
  * a stretch the shot list marked `fast` is played at 2x with a "2x" badge in
    the corner, because a real wait is real time and a demo has a budget;
  * when the voice outlasts a take, the take's last frame is held.

Usage:
  python render.py            # TTS (cached per text) + assemble
  python render.py --no-tts   # reuse cached voice files only
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
# The PROJECT is the directory the scripts sit in, so `out/` and the narration
# are beside the shot list rather than inside scripts/. PROJECT_DIR overrides
# it for a layout that keeps them somewhere else.
PROJECT = Path(os.environ.get("PROJECT_DIR") or HERE.parent).resolve()
OUT = PROJECT / "out"
TAKES = OUT / "takes"
BUILD = OUT / "build"
# A logo for the cards, if the project has one. No default: a renderer that
# reached into some other repository for a brand mark would put that brand on
# somebody else's video.
LOGO = Path(os.environ["DEMO_LOGO"]) if os.environ.get("DEMO_LOGO") else None
VOICE = "en-US-AriaNeural"
FPS = 30


def narration_file() -> str:
    """The narration to read: DEMO_LANG picks the language, default English."""
    return f"narration.{os.environ.get('DEMO_LANG', 'en')}.json"


def frame_size() -> tuple[int, int]:
    """The output size: the FIRST take's own, rounded to even.

    Read from the footage rather than declared, because the window is what was
    recorded — a fixed 1920x1080 either upscales a small app into a blur or
    pillarboxes it inside bars nobody asked for. Even numbers because H.264
    with yuv420p cannot encode an odd dimension.
    """
    takes = sorted(TAKES.glob("*.mkv"))
    if not takes:
        return 1920, 1080
    raw = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(takes[0])],
        capture_output=True, text=True, check=True).stdout.strip()
    w, h = (int(v) for v in raw.split("x")[:2])
    return w - w % 2, h - h % 2
ACCENT = (0, 90, 171)
FONT = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
MAX_SECONDS = 300


def run(cmd: list[str]) -> None:
    """Runs a command, failing loudly with its stderr tail."""
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(res.stderr[-3000:])
        raise SystemExit(f"command failed: {' '.join(cmd[:6])} …")


def duration(path: Path) -> float:
    """Media duration in seconds (ffprobe)."""
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)


def card(path: Path, title: str, lines: list[str]) -> None:
    """A title card in the guide's palette: logo, title, a few lines."""
    W, H = frame_size()
    img = Image.new("RGB", (W, H), (11, 18, 32))
    d = ImageDraw.Draw(img)
    for y in range(H):  # soft vertical gradient toward the accent
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(11 + 10 * t), int(18 + 30 * t), int(32 + 70 * t)))
    # Everything below is a FRACTION of the frame, because the frame is the
    # app's own window and an app window is whatever size it is. The same card
    # drawn with 1080p pixel offsets put its title below the bottom edge of a
    # 482x613 recording (measured 2026-09-28).
    unit = H / 1080
    if LOGO is not None and LOGO.exists():
        side = max(32, int(160 * unit))
        logo = Image.open(LOGO).convert("RGBA").resize((side, side))
        img.paste(logo, (W // 2 - side // 2, int(0.23 * H)), logo)
    tf = font(FONT_BOLD, max(18, int(78 * unit)))
    tw = d.textlength(title, font=tf)
    d.text(((W - tw) / 2, 0.42 * H), title, font=tf, fill=(255, 255, 255))
    lf = font(FONT, max(12, int(40 * unit)))
    step = max(16, int(62 * unit))
    for i, line in enumerate(lines):
        lw = d.textlength(line, font=lf)
        d.text(((W - lw) / 2, 0.53 * H + i * step), line, font=lf, fill=(190, 214, 240))
    rule = max(20, int(60 * unit))
    d.rectangle([(W // 2 - rule, 0.507 * H), (W // 2 + rule, 0.507 * H + max(2, 4 * unit))], fill=ACCENT)
    img.save(path)


def badge(path: Path) -> None:
    """The "2x" badge shown while a wait is played faster (two drawn triangles + 2×)."""
    img = Image.new("RGBA", (150, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([(0, 0), (149, 63)], radius=18, fill=(0, 0, 0, 170))
    for x0 in (22, 42):  # the font has no ▶ glyph, so draw the fast-forward mark
        d.polygon([(x0, 20), (x0, 44), (x0 + 18, 32)], fill=(255, 255, 255))
    d.text((72, 11), "2×", font=font(FONT_BOLD, 34), fill=(255, 255, 255))
    img.save(path)


async def tts(text: str, dest: Path) -> None:
    import edge_tts
    await edge_tts.Communicate(text, VOICE, rate="+4%").save(str(dest))


def voice_for(text: str, use_tts: bool) -> Path:
    """The narration audio for one text, cached by content hash."""
    key = hashlib.sha1(f"{VOICE}|{text}".encode()).hexdigest()[:16]
    dest = BUILD / "voice" / f"{key}.mp3"
    if not dest.exists():
        if not use_tts:
            raise SystemExit(f"no cached voice for: {text[:60]}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        asyncio.run(tts(text, dest))
    return dest


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def split_caption(text: str, dur: float, start: float) -> list[tuple[float, float, str]]:
    """Cuts one narration into caption lines, timed by length.

    Sentences first; a sentence over ~11 words is split again at commas, then
    by length. A caption never starts in the middle of a sentence's first words.
    """
    import re
    chunks: list[str] = []
    for sentence in re.split(r"(?<=[.?!])\s+", text.strip()):
        words = sentence.split()
        if len(words) <= 11:
            chunks.append(sentence)
            continue
        parts, cur = [], []
        for w in words:
            cur.append(w)
            if (w.endswith((",", ":")) and len(cur) >= 4) or len(cur) >= 11:
                parts.append(" ".join(cur))
                cur = []
        if cur:
            if parts and len(cur) < 3:
                parts[-1] += " " + " ".join(cur)
            else:
                parts.append(" ".join(cur))
        chunks += parts
    total = sum(len(c) for c in chunks) or 1
    out, t = [], start
    for c in chunks:
        d = dur * len(c) / total
        out.append((t, t + d, c))
        t += d
    return out


def segment_from_take(take: Path, meta: dict, dest: Path, badge_png: Path) -> None:
    """One take → a segment with its `fast` spans at 2x (badge on) and the rest at 1x."""
    total = duration(take)
    start = float(meta.get("trim_start", 0.0))
    end = float(meta.get("trim_end", total))
    spans = sorted((max(start, a), min(end, b)) for a, b in meta.get("fast", []) if b > a)
    pieces, t = [], start
    for a, b in spans:
        if a > t:
            pieces.append((t, a, 1))
        pieces.append((a, b, 2))
        t = b
    if end > t:
        pieces.append((t, end, 1))
    parts = []
    for i, (a, b, speed) in enumerate(pieces):
        p = dest.with_name(f"{dest.stem}.p{i}.mp4")
        W, H = frame_size()
        vf = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0b1220,fps={FPS}"
        if speed == 2:
            run(["ffmpeg", "-y", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(take), "-i", str(badge_png),
                 "-filter_complex", f"[0:v]setpts=PTS/2,{vf}[v];[v][1:v]overlay=W-w-36:36[o]", "-map", "[o]",
                 "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(p)])
        else:
            run(["ffmpeg", "-y", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(take), "-vf", vf,
                 "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(p)])
        parts.append(p)
    concat(parts, dest)


def concat(parts: list[Path], dest: Path) -> None:
    lst = dest.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(dest)])


def still(png: Path, seconds: float, dest: Path) -> None:
    run(["ffmpeg", "-y", "-loop", "1", "-t", f"{seconds:.3f}", "-i", str(png), "-vf", f"fps={FPS},format=yuv420p",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(dest)])


def with_voice(video: Path, voice: Path | None, dest: Path, lead: float = 0.4) -> float:
    """Lays the voice over a segment, holding the last frame if the voice is longer."""
    vdur = duration(video)
    adur = duration(voice) if voice else 0.0
    total = max(vdur, adur + lead + 0.6)
    hold = max(0.0, total - vdur)
    if voice:
        run(["ffmpeg", "-y", "-i", str(video), "-i", str(voice), "-filter_complex",
             f"[0:v]tpad=stop_mode=clone:stop_duration={hold:.3f}[v];"
             f"[1:a]adelay={int(lead * 1000)}|{int(lead * 1000)},apad=whole_dur={total:.3f}[a]",
             "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(dest)])
    else:
        run(["ffmpeg", "-y", "-i", str(video), "-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
             "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-shortest", str(dest)])
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-tts", action="store_true")
    args = ap.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    # Beside the shot list, not inside scripts/: the narration is the
    # project's content, and the scripts are the skill's.
    narration = json.loads((PROJECT / narration_file()).read_text())
    badge_png = BUILD / "badge.png"
    badge(badge_png)
    segments, captions, clock = [], [], 0.0
    for shot in narration["shots"]:
        sid, text = shot["id"], shot.get("text", "").strip()
        voice = voice_for(text, not args.no_tts) if text else None
        seg_video = BUILD / f"{sid}.video.mp4"
        if shot.get("card"):
            png = BUILD / f"{sid}.png"
            card(png, shot["card"]["title"], shot["card"].get("lines", []))
            still(png, max(3.0, (duration(voice) + 1.2) if voice else 3.0), seg_video)
        else:
            takes = sorted(TAKES.glob(f"{sid}-*.mkv"))
            if not takes:
                raise SystemExit(f"no take for shot {sid} in {TAKES}")
            take = takes[-1]
            meta = json.loads(take.with_suffix(".json").read_text())
            segment_from_take(take, meta, seg_video, badge_png)
        seg = BUILD / f"{sid}.seg.mp4"
        dur = with_voice(seg_video, voice, seg)
        if text:
            captions += split_caption(text, duration(voice), clock + 0.4)
        segments.append(seg)
        clock += dur
        print(f"{sid}: {dur:5.1f}s  (total {clock:5.1f}s)")
    joined = BUILD / "joined.mp4"
    concat(segments, joined)
    # Not next to the mp4: players (VLC) auto-load a same-name .srt as a second
    # subtitle track on top of the burned-in captions.
    srt = BUILD / "captions.srt"
    srt.write_text("".join(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{t}\n\n" for i, (a, b, t) in enumerate(captions, 1)))
    # Top centre: the composer at the bottom is where the prompts are typed,
    # and the band between the project picker and "Background tasks" is empty
    # on every screen of the demo.
    # Captions as ASS with an explicit 1920x1080 PlayRes: through an SRT the
    # filter measures margins on a 384x288 canvas and reads Alignment the
    # legacy way, which put the text mid-screen. Top centre, inside the band
    # between the project picker and "Background tasks", which is empty on
    # every screen of the demo; the composer at the bottom is where prompts
    # are typed and must stay visible.
    ass = BUILD / "captions.ass"
    def ts(t: float) -> str:
        cs = int(round(t * 100))
        return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"
    lines = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1920", "PlayResY: 1080", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        "Style: Cap,Noto Sans,38,&H00FFFFFF,&H00FFFFFF,&H80101820,&H80101820,0,0,0,0,100,100,0,0,3,10,0,8,520,520,14,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    lines += [f"Dialogue: 0,{ts(a)},{ts(b)},Cap,,0,0,0,,{t}" for a, b, t in captions]
    ass.write_text("\n".join(lines) + "\n", encoding="utf-8")
    final = OUT / "final.mp4"
    run(["ffmpeg", "-y", "-i", str(joined), "-vf", f"ass={ass}",
         "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy",
         "-movflags", "+faststart", str(final)])
    total = duration(final)
    print(f"wrote {final} — {total:.1f}s")
    if total > MAX_SECONDS:
        print(f"TOO LONG: {total:.1f}s > {MAX_SECONDS}s")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
