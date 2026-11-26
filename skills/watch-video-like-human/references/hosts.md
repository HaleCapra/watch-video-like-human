# Hosts: Which Tool Does What

This skill follows the open Agent Skills layout (`SKILL.md` with YAML frontmatter, `scripts/`,
`references/`) and names **capabilities**, not tools. Whatever agent is running it, map each
capability to a tool the host actually offers. If the host has no tool for a capability, that
capability is unavailable: say so in the disclosure instead of working around it.

Tool names below are examples and change between versions. Trust the tool list your host shows
you over this table.

| Capability the skill needs | What it is used for | If the host lacks it |
|---|---|---|
| **Run a local command** | Every script in `scripts/` (Python 3.9+, standard library only), `ffmpeg`, `ffprobe`, optionally `yt-dlp` and a local Whisper | Only Route B by hand is possible; no manifest. Write the disclosure yourself and say no scripts ran |
| **Look at an image file** | Opening extracted frames and crops. Without it nothing was "seen" | Visual is `none`. Deliver transcript-based work and label it |
| **Drive a browser page** | Route B only: read the player, the transcript panel, loaded caption tracks, take page screenshots | Route B is unavailable |
| **Ask the user a question** | Before anything heavy: Route C, any upload, installing or updating a tool, switching engine | Ask in plain chat text and wait |
| **Read and write files in a work directory** | Products, the read log, the manifest, the notes | Keep results in the reply and say no manifest exists |
| **A real desktop session with screen and audio** | Route C only | Route C is unavailable - common in cloud sandboxes |

## Examples by host

These are starting points, not guarantees. "Unverified" means it was written from the vendor's
documentation or from the folder layout, not tested end to end.

| Host | Run a command | Look at an image | Drive a browser | Ask the user | Where the skill goes |
|---|---|---|---|---|---|
| **Claude Code** (terminal, desktop, IDE) | the shell tool | the file-reading tool (it returns images) | a browser extension or a browser MCP server, if one is connected | the question tool, or plain text | `~/.claude/skills/watch-video-like-human/`, a project's `.claude/skills/`, or as a plugin |
| **Claude apps with skills** (upload a zip) | the code-execution sandbox | images the sandbox can open | usually none | plain text | uploaded in the app's skill settings |
| **Codex** (CLI, IDE, app) | the shell tool | the image-viewing tool | a browser tool or MCP server, if configured | plain text | `~/.agents/skills/watch-video-like-human/` or `~/.codex/skills/watch-video-like-human/` (plugin form: unverified) |
| **CodeBuddy** | the terminal tool | the host's image reading | if configured | plain text | `.codebuddy/skills/watch-video-like-human/` in the workspace (per vendor docs; user-level folder unverified) |
| **WorkBuddy** | the terminal tool | the host's image reading | if configured | plain text | `~/.workbuddy/skills/watch-video-like-human/` - community-sourced, unverified; otherwise import through its skill settings |
| **Any other agent** | any shell | any image input | any page-scripting tool | plain text | anywhere; point the agent at `SKILL.md` from `AGENTS.md` |

Most hosts can also be installed with `npx skills add <owner>/<repo>`, which copies the folder to
the right place for the agent it detects. WorkBuddy is not in its list and needs the manual copy.

## When a capability is missing

| Missing | Routes left | What the disclosure says |
|---|---|---|
| a browser tool | 0, A, C | `B unavailable - this host has no browser tool` in the Route history |
| a desktop session (cloud sandbox, SSH) | 0, A, B | `C unavailable - no screen or audio device here` |
| outbound network | 0, C, and B if the browser is the user's own | `A failed (no outbound network)` |
| an image-viewing tool | any, but Visual is `none` | the Visual line says no picture was opened |
| a shell | B by hand only | the block is written by hand and says no manifest exists |

Run `python scripts/probe_capabilities.py --has-browser yes|no` once: it prints this ladder for
the machine and host you are actually on.

## What changes in a cloud sandbox

A hosted sandbox is not the user's computer. Expect: no screen and no audio device (Route C is
out), outbound network limited to an allow-list (Route A usually fails - report the real error,
do not hunt for a way around it), and only the files the user uploaded (Route 0 works on those).
`scripts/probe_capabilities.py` reports all of this; run it once and plan from its output.

## Calling the scripts

Commands in this skill are written as `python scripts/NAME.py`. Resolve `scripts/` relative to the
folder that contains `SKILL.md`, and use whichever interpreter exists: `python3` on macOS and
Linux, `python` or `py -3` on Windows. Paths with spaces need quotes. The scripts print JSON that
is safe on any console code page, and read child-process output as UTF-8.

Optional pieces, all absent by default and never installed by the skill:

| Optional | Needed for | Without it |
|---|---|---|
| `yt-dlp` | Route A | Use Route 0, B or C |
| a local Whisper (`faster-whisper`, `mlx-whisper`, `openai-whisper`), driven by `scripts/transcribe_local.py` | transcribing audio locally | Captions only, or ask about cloud transcription |
| a loopback audio device (VB-CABLE, BlackHole, a PulseAudio / PipeWire monitor) | audio in Route C | Picture-only recording |
| Tesseract, a vision-model endpoint, a cloud speech endpoint | the optional backends | The default first-hand path |

## Installing what is missing

`python scripts/setup_tools.py` prints a plan and installs nothing; `--yes` runs it. The agent
asks the user first, in one sentence, and never installs silently, never uses `sudo`, and never
types a password. What it installs for Python (yt-dlp, a speech recogniser) goes into
`~/.watch-video-like-human` (or `$WVLH_HOME`), which every script puts first on `PATH`; ffmpeg
comes from the system's package manager, or as a static build placed in that folder's `bin/`
where no package manager can be used (seen on an Intel Mac, where Homebrew refused to install).
The script itself runs on Python 3.6+, so it is also the answer to "Python is too old": on such a
machine the base tier creates a private Python, and every other script, started with the old
Python, hands over to that one by itself and says so. The hand-over keeps the interpreter options
(`-I`, `-E`, `-s`, `-B`, `-O`, `-u`, `-W`, `-X utf8`). A private Python that is itself too old, or
that no longer starts, is reported with the steps to replace it; nothing is deleted or moved for the
user. With `--yes`, exit code 2 means everything automatic is done but manual steps are left (they
are listed at the end); do not report the setup as finished then.

## Notes from field tests

- **A built-in browser pane that is not the user's browser.** One desktop agent app's built-in
  pane can run page scripts, but it blocks the player scripts and styles of video sites
  (`net::ERR_BLOCKED_BY_CLIENT` on YouTube and TED) and has no login session, so the page has no
  `video` element. It does not meet Route B's precondition. Use a browser tool that drives the
  user's own browser there, and if only the built-in pane exists say "B unavailable - this
  host's browser cannot play the video"; do not scrape the page
from the command line and call it Route B.
- **Route C on macOS inside a desktop agent app.** Commands run under the app's bundled
  command-line helper, which has its own Screen Recording switch (see `recording-notes.md`).
- **Route C inside any desktop agent app.** The app's own window comes to the front when the
  agent finishes a turn and covers the player. Minimise it and keep the turn open until the
  recording ends.
- **Intel Macs.** Homebrew's installer refuses Intel processors. Python (`uv python install`
  or python.org), yt-dlp, ffmpeg (a signed static build) and BlackHole (the vendor's installer)
  all install without it; `setup_tools.py` plans it that way.
- **python.org Python on macOS** has no CA bundle until `Install Certificates.command` is run;
  the probe reports that as a TLS trust problem, not as a missing network.
- **Debian / Ubuntu Python** may come without `pip`, `ensurepip` and `venv`. `setup_tools.py`
  then plans to fetch a pinned, checksum-verified `uv` into the private folder (only with
  `--yes`): from its official GitHub release page, or from the same version on PyPI when GitHub
  cannot be reached. Where neither answers it prints the manual steps (install uv yourself, or the `python3-venv` package).
- **A browser tool whose replies are cut at about 1 KB.** Read the transcript panel by character
  budget (`browser-extraction.md`), not by time window.
