# agentbox-skills

Skills that ship with [AgentBox](https://dev.azure.com/) rather than with a
checkout of its source: every install clones this repository on first run
(`skills.PreinstallPacks`) and ticks what it delivers.

That is the whole reason this repository is separate. A skill frozen into
whichever build somebody happens to have installed cannot be corrected without
shipping a new build; a skill cloned from here at a pinned version can be
updated by the person who has it, and re-pinned when they choose to.

## What is here

| Skill | What it does |
| --- | --- |
| `demo-video` | Record a real desktop application on this machine into a finished demo video — launch it under X11, drive it with injected mouse and keyboard, capture the window with ffmpeg, cut the takes into an mp4 with voice-over and captions. |

## Installing it by hand

Every AgentBox install already has this. To add it to another machine, or to
re-add it after removing it:

    agentbox skill add github:iamndh34/agentbox-skills

## Requirements

`demo-video` needs a graphical session it can drive and the runtime AgentBox
provisions:

    agentbox install pytools    # python-xlib, pynput, Pillow, edge-tts
    hachimi doctor              # names whatever is still missing

The session must be X11, or Wayland with XWayland **and** the application
started under `GDK_BACKEND=x11`. A native Wayland window is not in the X11
window tree, so the driver cannot see it and ffmpeg cannot read it — Wayland
has no protocol for one client to drive another's window, and no workaround
changes that.

## Layout

One directory per skill, each with a `SKILL.md` carrying `name` and
`description` in its frontmatter. Supporting files live beside it and are
read-only once installed; the path is injected above the skill's text when it
loads.
