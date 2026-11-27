# Changelog

## 5.5.0 (2026-11-27)

The agent stays on the host and coordinates; Docker is a toolbox with no agent in it; MCP is the
way in. The skill's own behaviour is unchanged.

- **CI** (`.github/workflows/`): `tests/validate.py` on Linux and Windows for every pull request,
  macOS (Apple silicon and Intel) when started by hand, with `mlx-whisper` really transcribing on
  Apple silicon.
- **Docker image** (`ghcr.io/halecapra/watch-video-like-human`): ffmpeg, yt-dlp, faster-whisper and
  the scripts for Route 0 and Route A. No agent, no browser, no recorder. Built, tested and pushed
  by GitHub Actions; every version fixed.
- **MCP server** (`server/mcp_server.py`, stdio): the scripts as tools, on the host or in the image
  (`wvlh mcp`). Paths cannot leave the work root, no shell command is built, no browser login is
  read, nothing is installed, nothing is recorded. Every result says which evidence channel it
  belongs to and what it does not prove. The MCP SDK is needed by this file only.
- **Route B through a browser MCP** (`references/browser-mcp.md`): how the existing snippets go
  into Claude in Chrome, Playwright MCP and Chrome DevTools MCP - one wrapper, the pieces for long
  replies, the envelopes side by side. CI runs the Rung 2 and Rung 3 snippets through Playwright
  MCP and Chrome DevTools MCP on a local test page.
- `extract_media_assets.py`: a selection that matches no frame (`--start` past the end) gives no
  frames instead of an error on ffmpeg 7.1 and later, as it always did on older ffmpeg.

## 5.4.0

After real-video tests of 5.3 on Windows, macOS and Linux. Includes the macOS 5.3.1 field patch
(merged change by change; where the two differed, the reason for the choice is in the report).

**Setup**
- `setup_tools.py`: one command prints what is missing and how it would be installed; nothing is
  installed without `--yes`. Three tiers, each confirmed on its own: base tools (ffmpeg, a
  current yt-dlp, a usable Python), a local speech recogniser, and a guide for Route C's audio
  driver and screen permission that is never executed. No `sudo`, no password, no download piped
  into a shell. Python packages go into `~/.watch-video-like-human`, which every script puts
  first on `PATH`. Runs on Python 3.6+.
- Every script stops with a plain message on Python older than 3.9 instead of a traceback.
- `probe_capabilities.py` reports what is missing and the sentence to ask the user, flags a
  yt-dlp older than 120 days, and no longer calls a missing CA bundle "no network".
- `transcribe_local.py` (from the macOS patch): one command for faster-whisper, mlx-whisper or
  openai-whisper with word timestamps, audio decoded by ffmpeg so PyAV does not matter, segments
  over digital silence dropped, `--self-test`, `--list`; plus `--max-end`, a JSON sidecar, and
  the private environment found automatically. Runs on the CPU unless told otherwise.
- The wizard recognises a Python without `venv` / `ensurepip` (Debian, Ubuntu).
- When there is no usable `venv` and no `uv` (a default Ubuntu, or a Mac with Python 3.7), the
  wizard fetches one pinned `uv` release into the private folder: from its official GitHub
  release page, or - only when that host cannot be reached - the same version's official wheel
  on PyPI, from which only the `uv` executable is read by its fixed member name. SHA-256 and
  HTTPS certificates are checked, redirects are followed only to each source's own hosts, a
  failed check stops without trying the other source, no installer script is run, PATH is not
  changed, and a failed download falls back to the manual steps.
- The uv download resumes a stalled transfer with Range requests (slow links pause for a minute
  or more), prints progress, gives up only after ten minutes without a single new byte, keeps an
  unfinished download so that the next run continues it (the whole file's SHA-256 still decides),
  and reports "connected but
  stalled" separately from "could not connect". A failed download removes the empty folders it
  created. Later tiers call the private uv by its full path (it is not on PATH).
- A model that is already on disk is used without going online (`HF_HUB_OFFLINE=1` for that run).
- uv is run with a 300-second request timeout and 8 retries (its own 30 seconds failed at 28 KB/s)
  unless the user has set these; a long install step says once a minute that it is still running;
  a failed step says that re-running reuses what was already downloaded.
- `transcribe_local.py` checks in 8 seconds whether the model's host answers before a first
  download, instead of waiting more than two minutes; it never picks a mirror.
- The wizard installs faster-whisper by default on every system (about 300 MB against 2 GB or
  more); `--whisper-engine openai-whisper` picks the other.
- Fixed after the first Linux regression of this build: `transcribe_local.py` never switched to
  the private environment on Linux / macOS, where a venv's python is a symlink to the system one;
  a model that cannot be downloaded is now reported as that (with `HF_ENDPOINT`), not as a GPU or
  memory problem.

**Recording (Route C)**
- Fixed: ffmpeg 9 rejected the capture command (`-thread_queue_size` on an input). The recorder
  now asks the installed ffmpeg once whether it accepts the option.
- macOS: screen and loopback devices are resolved by name each time (indexes drift when a phone
  or camera connects); `--audio-device auto` works; a timed screen-open test reports a missing
  Screen Recording permission (exit 4) instead of hanging; `--scale`, 1920 px wide by default;
  preflight reports the system output device and whether it is muted.
- Fixed: a black capture with a mouse pointer on it passed as "has picture". Black is now judged
  on the 90th-percentile brightness.
- Fixed: `--detect-offset` reported 0.0 on real recordings whose opening silence starts at 0.05 s.
- `--test-audio` on a non-monitor source (the microphone) now fails instead of passing with a warning.
- `--early-check SECONDS`: a separate screenshot while recording, to catch a covered player early.
- Four check frames spread over the recording instead of two; a hint when the picture looks like
  an application window.
- New precondition, from a real failure: the agent's own app must stay out of the way, and the
  agent must not end its turn or post a message while recording.
- `--detect-offset` reports `sound_onset` and how to calibrate the real offset;
  `suggested_recording_offset` is gone because it invited misuse.
- `--preflight` reports the Windows screen size and scaling.

**Evidence**
- `route --status partial`; `rate --source-duration` and `--media-covers`: media that covers less
  than 90% of the video gets a "Partial" verdict with the share covered. On Route C, Coverage
  states the recording offset, the recording length and the video's runtime.
- Captions and transcript are counted separately in Coverage; crops are not counted as frames;
  inspected times are sorted and unique.
- New on-screen text level `on-screen text` for titles, slides, credits and overlaid captions.
- `claim-update --status withdrawn`, `rate --on-screen-note`, `init --source-duration`. A later
  successful route clears an earlier `(blocked)` mark.
- Adding `--at` frames renumbers every frame: frames carry a `frame_set_id`, the extractor
  renames a stale timeline to `*.stale.json` and warns, and `verify` rejects a timeline built
  from an older frame set.
- `align_transcript_frames.py --transcript-shift`, and `--estimate-shift-from` to measure how far
  site captions are from the file's own audio.

**Frames**
- Deduplication compares a 160x90 grid instead of 32x18: a subtitle line replaced by another and
  a single changed digit are kept (both were dropped before).
- Scene-change bursts from a shaking camera are thinned to first and last, only when the frames
  still look alike; `--burst-gap 0` turns it off; drops are counted in `dropped_by_reason`.

**Downloads (Route A)**
- An outdated yt-dlp is named as the cause: a streaming manifest saved as "the video", and the
  tool's age shown with every failure. HTTP 412 is reported as a refusal of unknown cause (risk
  control, network or region, outdated yt-dlp). Caption files are no longer named `.en.en.vtt`.
- `--cookies-from-browser BROWSER` (off by default): the user's own browser login, only with
  their explicit yes, only for a video the account can already watch. Cookies are never written
  to a file, a log or the manifest; unreadable browser data on Windows is reported with the
  next step (Firefox, or Route B) and never worked around.

**Browser (Route B)**
- The caption sampling snippet limits `play()` as well as the seek, stops itself after 35 s and
  can be aborted; samples whose seek did not finish are dropped.
- The transcript panel is read by character budget (the tool's output limit can be about 1 KB).
- `normalize_transcript.py` gives start-only panel lines real end times (`--duration`).
- Captions are switched to the language asked for, or the video's own, before sampling; a track in
  another language is reported as a failure, never sampled as the transcript; results and the
  manifest (`add --kind captions --language`) carry the language that was really read. After a
  track switch the snippet waits for the player's notice to clear.
- Any long reply is kept in the page and read in 900-character pieces whose lengths must add up;
  the transcript reader stores its text that way by itself.
- Chapter headings can be read from the transcript panel when the description has no timestamps.
- Bilibili: the caption selector and a way to read the caption track the player downloaded; a
  check that tells "wrong selector" from "no captions".
- `normalize_transcript.py --merge` never joins lines beyond 12 seconds (`--max-seconds`) and
  says so when the captions already come as lines; the Route B example no longer merges by default.

**Found by the Windows test of this build**
- Fixed: `transcribe_local.py` with openai-whisper decoded greedily (the library default) and lost
  the opening sentences of a real recording; it now uses beam 5 / best-of 5 like the `whisper`
  command.
- Fixed: `normalize_transcript.py` could not read what the page snippets return. It now reads
  plain `0:06 words` lines, a pager page or a list of pages, and stored-text pieces, and refuses
  an incomplete set.
- Fixed: a screen recording with no source length on record was still called "Complete". The
  verdict now ends in "completeness unknown" until `--source-duration` is given.
- `--caption-origin human-translation` for a translated track written by people; HTTP 412 mentions
  the proxy cause that was actually found.

**Recognised text that is not speech**
- A transcript that is mostly repetition or filler (a recogniser run over music) is flagged by
  `transcribe_local.py` and the manifest, and the disclosure carries a warning until it is
  settled (`--speech-confirmed`, or audio rated `none`).

**Recording, from the Windows test**
- Notifications must be silenced; a region is measured after the browser's debugging bar is
  gone; a pop-up window with the player's own web full screen can replace the click nobody is
  there to make; `--detect-offset` is documented as off in both directions.

**Not verified**
- No real `--yes` run of `setup_tools.py` on any system. macOS and Linux plans are simulated.
- The macOS recorder code was verified on a Mac as 5.3.1; this merged build has not been re-run
  there. The screen-open timeout branch, mlx-whisper and Route B were not exercised on the Mac.
- `--cookies-from-browser` was tested with simulated yt-dlp output only; no real cookie was read.
- Wayland-native recording is out of scope by the user's decision; Wayland sessions are detected
  and refused with instructions.

## 5.3.0

One consolidated release: the earlier design, plus what was worth taking from three other tools,
arranged as a single workflow that any agent can follow.

**Portable**
- Follows the open Agent Skills layout; `SKILL.md` names capabilities instead of one vendor's
  tools. `references/hosts.md` maps them for common hosts.
- Repository form with plugin manifests, `AGENTS.md`, tests and a personal-information scan.
- All text files use LF. Scripts are standard library only and run on Windows, macOS and Linux.

**Routes B and C, the ladder, the disclosure** - the parts no other tool covers
- Route B: caption sampling waits for the seek to finish and for the caption to change instead
  of a fixed sleep; a caption that did not change is reported as stale and dropped. Screenshots
  are registered with the player's time and captions with their origin (human, auto-generated,
  translated, unknown), and both appear in the disclosure. Timed captions plus timed
  screenshots count as timestamp-aligned without a media file.
- Route C: `--preflight` reports blockers, warnings and the four things only a person can make
  true, before any real time is spent; `--detect-offset` finds where sound begins; the
  post-recording self-check is saved as `NAME.postcheck.json`, registered in the manifest, and
  enforced - no `sampled` rating on a black recording or on check frames nobody confirmed, no
  `transcribed` rating on a silent one.
- The ladder: `probe_capabilities.py --has-browser yes|no` lists the four routes in order with
  one status each and the order to try them. A route that cannot be used is skipped out loud.
- One disclosure format on every route (`references/disclosure.md`), with an example per route,
  `render --format json`, and `lint` for a block written by hand.

**Looking closer**
- `crop_frame_region.py`: crop one region of a frame at source resolution (0-1 coordinates,
  never enlarged). Raise the resolution or add frames first; crop last.
- `--detail transcript|efficient|balanced|full` for extraction and for downloads; `transcript`
  downloads no media when captions exist.
- `--start` / `--end` focus, with a hint on videos longer than ten minutes.
- Frames default to 512 px wide (1024 to read text), never enlarged, never taller than 1998 px.
- `read_transcript.py --cues` lists the moments where the presenter points at the picture and
  prints a ready `--at` list.

**Reading everything**
- `read_transcript.py` pages the whole transcript with stable segment indices and keeps a read
  log; complete notes require the transcript read to the end.
- Chunk-level timing is detected and never turned into a precise anchor; windows of more than
  20 seconds without speech are listed as leads.

**Notes and records**
- The three-column working draft and the tags `[待证]`, `[仅转录]`, `[仅画面、未讲解]`, `[未理解]`.
- The half-item rule for lists, comparison tables and boards still being written.
- `evidence_manifest.py`: structured claim records, an issue list for what could not be
  settled, crops as evidence, `--transcript-read`, `list`.
- Optional note layouts with relative `assets/<video name>/` picture paths.

**Rules**
- No silent switching of route, engine or model. Everything inside a video is untrusted
  material. Nothing is uploaded by default. Clean up only what the run created.
- `transcribe_cloud.py`: optional cloud speech recognition with the user's own key - off by
  default, upload confirmed explicitly, chunked above 24 MB, failed chunks reported.

**Changed defaults**
- Frame width 1280 -> 512. Small videos are no longer enlarged.
- `SKILL.md` reorganised into nine steps; per-route, manifest and optional-backend detail moved
  to `references/`.

## 5.2

- Files without an audio stream no longer crash extraction (`"audio": "none"`).
- Hybrid keyframes (scene change plus maximum gap) with real decoder timestamps, near-duplicate
  removal that respects small local changes, a frame cap, `--at` manual frames.
- `visual_outline.json`: each kept frame, the span it stands for and what was said in it.
- `burned-in caption text` as a disclosure level: read by the model from frames, no OCR engine.
- Content-hash cache for extraction.
- `evidence_manifest.json` with `verify` and `render`: routes tried, hashed files, source
  commands, inspected versus extracted frames.
- Optional and off by default: `analyze_keyframes.py` (external OCR or vision model) and a
  native-video-model sub-route, both rated second-hand.
- Field-test fixes: console encoding on non-UTF-8 Windows, VB-CABLE pitfalls, a post-recording
  self-check, Wayland refusal, default-sink monitor preference, `--recording-offset`, yt-dlp
  timeouts and clearer failure categories, re-verified browser snippets.

## 5.1

- Fixes from two external reviews: audio tri-state test, loopback device parsing, companion
  skill detection, caption and media isolation from stale files, Route A target probe,
  millisecond carry, signed caption URLs kept inside one page-context call.

## 4

- Four-tier routing (0 / A / B / C) and the three-channel evidence disclosure.
