# Route Details

`SKILL.md` chooses the route and gives the order of work. This file holds the commands, the
defaults and the failure handling for each route. Read the part for the route you are on.

**Before any route:** `--detail` decides how much picture evidence to take
(`transcript | efficient | balanced | full`), `--start` / `--end` focus on one stretch, and frames
default to 512 px wide (`--width 1024` to read text, `--width 0` for source width, never
enlarged, never taller than 1998 px). On a video longer than about ten minutes, read the
transcript first and focus; a fixed cap spread over an hour is thin. Extraction cleans up only
its own `frames/` folder in the output directory - never the source file, never the parent of
`--out-dir`, never a model cache.

### Route 0 - user file

Use immediately when a local video is already available. Ask whether the user has a file only
when that fact is unknown and the answer would materially change the work.

```bash
python scripts/extract_media_assets.py VIDEO --out-dir WORK --interval 5
# Transcribe WORK/audio.wav (skip if frames.json says "audio": "none"):
python scripts/transcribe_local.py WORK/audio.wav --language LANG --model small     # -> WORK/audio.srt
# (equivalent by hand with openai-whisper:)
python -m whisper WORK/audio.wav --model small --language LANG --word_timestamps True \
    --output_format srt --output_dir WORK
python scripts/align_transcript_frames.py --transcript transcript.srt --frames WORK/frames.json     --output WORK/timeline.json --speech-source transcribed
```

`extract_media_assets.py` defaults to **hybrid keyframes**: a frame at every scene change
(`--scene-threshold 0.3`) plus a fill frame whenever `--interval` seconds pass without one.
Every timestamp is the decoder's real PTS, and `frames.json` records why each frame was chosen
(`first-frame`, `scene-change`, `max-gap`, `interval`, `manual`). Near-duplicate frames are moved
to `frames/_dropped/` and the kept count is capped by `--max-frames` (default 120). Use
`--frame-mode interval` for a fixed cadence and `--at 01:30,02:45` for frames at times the
question needs. A file with **no audio stream** (for example a Route C `--allow-silent`
recording) still gets its frames and `frames.json`, with `"audio": "none"` — that file supports
no audio claims at all. Re-running with the same file and parameters into the same `--out-dir`
reuses the products (content-hash cache); pass `--force` to re-extract.

`transcribe_local.py` uses faster-whisper, mlx-whisper or openai-whisper, whichever is importable
from the Python running it or from the private environment `setup_tools.py --tier whisper` makes
(`pipx` does not work for a package without a command). It decodes the audio itself, so it is
not affected by the faster-whisper 1.2 / PyAV 19 incompatibility, always asks for word
timestamps, and drops any segment that lies entirely over digital silence (Whisper invents
"you" or "Thank you" there). `--self-test` runs each backend on a second of silence; `--list`
shows what is importable. It runs on the CPU unless `--device cuda` is given. With openai-whisper
it decodes with beam size 5 and best-of 5, exactly as the `whisper` command does: the library's
own default (greedy) lost the opening sentences of a real recording. The same file can
come out as 63, 66 or 69 segments on consecutive runs: recognition is not deterministic. Report
the segment count of the transcript you actually used, never as a reproducible property of the video.

**Music is not speech.** A recogniser run over a track with no voice still prints text ("Oh, oh,
oh...", "la la", "Thank you."). `transcribe_local.py` and the manifest flag text that is mostly
repetition or filler (`speech_doubt`), and the disclosure then carries a warning. Settle it: if
nobody speaks, rate audio `none` and say the track is music; if it is speech (a chant, a song
the user cares about), re-add the transcript with `--speech-confirmed`.

When calling Whisper by hand, always pass `--word_timestamps True`: without it Whisper stretches the first segment back to
00:00 across any silent or music-only opening (measured: a line spoken at 00:20-00:27 was stamped
00:00-00:28), which corrupts every alignment that follows. Set `--language` explicitly.

Deduplication keeps a frame when any small region of it changed: the test compares a 160x90
grey grid, so a subtitle line replaced by another, a new slide bullet, scrolling code or a single
changed digit survives (an earlier 32x18 grid dropped replaced subtitle lines). Scene-change
frames that come several to a second and still look alike - a shaking camera - are thinned to
the first and last of the burst (`--burst-gap 0` turns that off); real fast cuts are different
pictures and stay. `frames.json` counts what was dropped under `dropped_by_reason`.

**Slides, code, subtitles, screen recordings** - anything where only text changes: the default
hybrid mode keys on scene changes, which small text changes do not trigger, so it may keep only a
frame or two. Use a fixed cadence instead: `--frame-mode interval --interval 2`, and
`--no-dedupe` when every state matters and the frame count is acceptable.

**Captions that are not on the file's clock.** Site captions are often timed to the programme
without the intro the downloaded file has (measured on TED: 3.4 s early). When a transcript
recognised from the file's own audio exists, `align_transcript_frames.py --transcript CAPTIONS
--estimate-shift-from WORK/audio.srt` reports the typical difference as
`suggested_transcript_shift`; check two lines by ear or against a frame, then pass
`--transcript-shift SECONDS`. Nothing is shifted automatically, and the shift is stated in the
disclosure.

`align_transcript_frames.py` writes two views: `timeline.json` (each speech segment with nearby
frames) and `visual_outline.json` (each kept frame with the span it stands for, up to the next
kept frame, and every line spoken in that span). Without `--transcript` it writes the outline
alone, which is the right shape for a silent recording.

If the host has another video skill installed (`probe_capabilities.py` lists what it finds), it
may do scene selection, deduplication or transcription for Route 0. Say which tool did the work;
the evidence disclosure is still mandatory.

### Route A - download

Use only for authorized sources when retrieval is supported and allowed. Prefer metadata and
captions before downloading media.

```bash
python scripts/fetch_media.py URL --info
python scripts/fetch_media.py URL --captions --lang en
python scripts/fetch_media.py URL --audio
python scripts/fetch_media.py URL --video
python scripts/fetch_media.py URL --detail transcript   # captions only; no media download when captions exist
python scripts/fetch_media.py URL --detail balanced     # captions + the video file
```

With `--detail transcript`, when captions are obtained **nothing else is downloaded** and the
evidence is captions-only. When there are none, only the audio track is fetched so it can be
transcribed; the result says which happened.

Another installed video skill may be used for Route A media processing if the user prefers it. Do not repeatedly retry
network, IP, login, or unsupported-site failures; move to Route B when normal browser playback is
available.

`fetch_media.py` names the failure and always quotes yt-dlp's own error line. Tell the cases
apart, because the next move differs: a sign-in demand and an HTTP 429 are access controls
(never type credentials, solve a captcha or disguise the client; go to Route B or C); an HTTP 412
(seen on Bilibili) is a refusal whose cause has to be found - the site's risk control, the
network or region, or an outdated yt-dlp. In one field test it was a proxy: the shell had
`HTTPS_PROXY` set, the site refused the proxy's foreign exit address, and the same command worked
at once without it; a streaming manifest saved as "the video" and an
extractor error such as
`list index out of range` or `An extractor error has occurred` means the installed yt-dlp is too
old for that site, which is not an access block - tell the user it may need updating and do not
install or update it unasked. A field test with a two-year-old yt-dlp failed on four public
sources in three different ways, so Route A failing does not mean the video is protected.

### Using the user's browser login (optional, off by default)

```bash
python scripts/fetch_media.py URL --detail balanced --cookies-from-browser firefox
python scripts/fetch_media.py URL --video --cookies-from-browser chrome --browser-profile "Profile 1"
```

- **Ask first, every time.** The agent adds `--cookies-from-browser` only after the user has said
  yes to using their browser login for this download. It is never a default, never detected, and
  never an automatic retry after a failure. The browser is named explicitly.
- **Only for a video the user's account can already watch normally.** It is the same viewing
  right, used by another program. It does not solve captchas and is not a way past DRM, a
  paywall, a region lock or any other restriction; if the site still refuses, stop.
- **Login cookies are credentials.** yt-dlp reads them in memory for that one command. This skill
  never writes them to a file, a log, the cache, an error message or the evidence manifest; the
  manifest records only that a browser login was used and which browser
  (`evidence_manifest.py route --route A --status succeeded --browser-login firefox`), and the
  disclosure says so.
- **The risk is the user's to accept**: automated downloading can be against a platform's rules,
  and an account used this way can be limited or suspended. Say this when asking.
- **When the browser will not give them up** (Windows: Chrome and Edge encrypt the data, bind it
  to the browser and lock the database while running), `fetch_media.py` says so. Then ask whether
  Firefox holds the same login, or use Route B. Do not try to defeat the encryption, do not run
  anything as administrator, do not close the user's browser, and do not suggest a
  cookie-exporting extension.

### Route B - browser extraction

Read `references/browser-extraction.md` before driving a browser. Work in this order:

1. Player runtime, metadata, and chapters.
2. Visible transcript panel.
3. Caption track already loaded by the player.
4. Timed caption sampling.
5. Frame screenshots only when the question is visual.

Save what you extract as files and register it (transcript, each screenshot with `--time`, the
caption track's origin with `--caption-origin`); section 8 of the browser reference shows how.

Route B never supplies real audio. Captions are text evidence and do not support claims about
tone, music, sound effects, overlapping speakers, or anything omitted by the captions.

**Session hygiene — these six lines prevent most Route B failures:**

- Set the viewport to **at least 1280x900 first**. Below roughly 1200px many sites drop to a
  narrow layout where the transcript panel does not exist in the DOM at all. A control you
  cannot find is often a control that is not there.
- **Pause playback via the video element** before DOM-heavy reads. Playback plus ads plus
  repeated screenshots is what pins a renderer.
- **Prefer text reads over screenshots.** One screenshot costs roughly what five minutes of
  transcript text costs, and tells you about one instant.
- **Expand collapsed regions before searching them** — transcript entry points hide inside
  description panels.
- **Re-resolve element references after the page changes.** A click that reports success while
  nothing happens usually hit a hidden duplicate node. Re-query; do not re-click.
- **Handle ads explicitly**: detect, use the platform's own Skip control when offered, otherwise
  wait — and mention the interruption in your output.

**When the page stops responding:** stop issuing the failing call. Try a text-only read; if it
returns, the DOM is alive, so finish through text and skip visuals. If nothing returns, close
the tab and open a fresh one — do not reload the frozen tab — then resume at the highest step
already cleared. Two consecutive screenshot timeouts, or two independent tab failures, is a real
blocker to report, not a retry opportunity.

### Route C - screen plus loopback recording

Read `references/recording-notes.md`. Route C costs real time and takes over the screen, so ask
the user first, then run the preflight, then check audio:

```bash
python scripts/record_browser_playback.py --preflight         # screen, session, loopback device, blockers
```

Then check audio before recording:

```bash
python scripts/record_browser_playback.py --check-audio    # is a loopback device present?
python scripts/record_browser_playback.py --test-audio     # is signal actually FLOWING? (play the video first)
```

`--check-audio` only proves a device exists. `--test-audio` records a few seconds and distinguishes
normal signal, signal that is flowing but too quiet for reliable transcription, and digital
silence around -91 dB. Run it **while the video is playing**. Without it you discover a muted
player only after recording the whole video in real time — the one failure whose cost is measured
in minutes. It prints the full mute-checklist only for digital silence.

Two Windows traps, both detailed in `references/recording-notes.md`: the VB-CABLE installer
makes `CABLE Input` the system default output, so set the speakers back as default right after
installing; and a browser that is missing from Volume mixer while the video plays has a muted
tab, which no page script can detect.

**Route C records the screen, not the video.** Whatever is on top is what gets recorded, so
these are preconditions, not tips:

- The player is **full screen and in front** for the whole recording. A person has to be at the
  machine to put it there - an agent usually cannot raise a browser window by itself - and nobody
  uses the computer until the recording ends. If no one is present, Route C is not available;
  say so instead of recording the desktop.
- **Exactly one player is playing.** Before and after recording, list every `video` / `audio`
  element on the page (snippet in `references/browser-extraction.md`, section 1). Two instances
  give doubled, offset audio that transcribes into nonsense: discard that audio.
- **Note the offset** between starting the recording and the video starting to play. Every
  timestamp from a recording is on the recording's clock.

Windows and Linux can auto-select a recognized loopback source:

```bash
python scripts/record_browser_playback.py --audio-device auto --duration 780 --output capture.mp4
```

Linux uses X11 capture and a PulseAudio / PipeWire `.monitor` source. The screen size is read
from `xdpyinfo` / `xrandr` when `--video-size` is omitted. Never pass `--audio-device default`
there: the default source is the microphone. Under **Wayland** the script refuses to start,
because x11grab records a black picture there; use the desktop's own recorder and continue as
Route 0, or grab one X11 window:

```bash
python scripts/record_browser_playback.py --platform linux --video-size 1920x1080 --audio-device auto --duration 780 --output capture.mp4
python scripts/record_browser_playback.py --platform linux --window-id 0x600009 --audio-device auto --duration 780 --output capture.mp4
```

macOS requires the numeric screen and audio indexes returned by `--list-devices`:

```bash
python scripts/record_browser_playback.py --platform macos --list-devices
python scripts/record_browser_playback.py --platform macos --screen-device 2 --audio-device 1 --duration 780 --output capture.mp4
```

**Post-recording self-check - do this before extracting anything.** When ffmpeg stops, the
script samples the recording and prints a JSON report: `video` is `has_picture`, `partly_black`,
`black` or `no_frames`; `audio` is `signal_present`, `too_quiet`, `digital_silence` or `none`.
An all-black picture (DRM, Wayland, a protected surface) or a silent track when a device was
given exits with code 3 - report Route C as blocked for that channel. Re-run the check on any
file with `--post-check FILE`. The check also writes two frames, `NAME.check-1.jpg` and
`NAME.check-2.jpg`: **open them and confirm they show the video.** A black-frame test cannot
tell the right picture from the wrong one; a recording of some other window passes it, and in a
real test exactly that happened - a complete, good-sounding file whose every frame was another
application.

After a recording, pass the offset so the outputs carry the video's own clock as well:

```bash
python scripts/align_transcript_frames.py --transcript WORK/audio.srt --frames WORK/frames.json \
    --output WORK/timeline.json --speech-source transcribed --recording-offset 7.0
```

Cite `video_range` (recording time minus the offset), and state the offset and how it was
measured (a stopwatch, or `ffmpeg -af silencedetect` on the recording). A recording can also
end up with only one usable channel; rate each on its own.

Use `--allow-silent` only when picture-only recording is intentional. A silent recording cannot
support audio claims. Recording a complete file still does not prove continuous visual analysis;
the recorded motion must actually be inspected by a video-capable process for visual coverage to
be marked continuous.
