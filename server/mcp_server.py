#!/usr/bin/env python3
"""watch-video-like-human as an MCP server (stdio): the skill's scripts, callable as tools.

    python server/mcp_server.py [--root DIR]          # on the machine itself
    docker run -i --rm -v DIR:/work IMAGE mcp         # the same server inside the tools image

This is one more way in, not a second implementation: every tool builds an argument list and runs
the script the skill already ships, then hands back what the script printed. Nothing is decided
here about what counts as evidence - the scripts and the agent do that.

What it will not do, on purpose:
  - touch a file outside the work root (--root, default: the folder it was started in);
  - build a command line for a shell: scripts are started directly, with a list of arguments;
  - read a browser's login state: the fetch tool has no such parameter;
  - install anything: the setup tool only prints the plan;
  - record the screen: Route C needs the person's own screen and stays with the agent on the host.

The MCP SDK is needed only by this file. The skill itself stays standard library only.

    pip install -r server/requirements.txt            # Python 3.11 or later
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:                                              # MCP SDK 2.x
    from mcp.server.mcpserver.exceptions import ToolError
except Exception:                                 # noqa: BLE001 - any failure means "not this layout"
    try:                                          # MCP SDK 1.x
        from mcp.server.fastmcp.exceptions import ToolError
    except Exception:                             # noqa: BLE001 - no SDK: still importable for --list-tools and tests
        class ToolError(Exception):
            """Stand-in when the MCP SDK is not installed."""

SERVER_NAME = "watch-video-like-human"
SERVER_VERSION = "5.5.0"
HERE = Path(__file__).resolve().parent
SCRIPTS = Path(os.environ.get("WVLH_SCRIPTS") or HERE.parent / "skills" / "watch-video-like-human" / "scripts")
STATE = {"root": os.path.realpath(os.getcwd())}
DEFAULT_TIMEOUT = 3600.0
WINDOWS_DEVICE = re.compile(r"(?i)CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[0-9]|LPT[0-9]")
NOT_OFFERED = {
    "record_browser_playback": "Screen recording (Route C) is not a tool here: it captures the person's own screen "
                               "and sound. The agent runs scripts/record_browser_playback.py on the host itself.",
    "install": "Nothing is installed through this server. setup_plan prints the plan; the person (or the agent on "
               "the host, with their consent) runs scripts/setup_tools.py.",
    "browser_login": "The fetch tool cannot use a browser's login state. That choice belongs to the person, on the "
                     "host, with scripts/fetch_media.py.",
    "browser": "Route B runs in the agent's own browser tool; see references/browser-mcp.md.",
}

INSTRUCTIONS = (
    "Tools of the watch-video-like-human skill: Route 0 (a file the user already has) and Route A (allowed "
    "yt-dlp retrieval). Read the skill's SKILL.md for the order to use them in. "
    "Three evidence channels stay separate: frames you actually opened count as seen; audio you transcribed or "
    "listened to counts as heard; captions and transcripts are text you read - reading them is not watching and "
    "not hearing. Every result carries an 'evidence' note saying which channel it belongs to and what it does "
    "not prove. A tool that wrote frames has not looked at them. Rate the channels with evidence_manifest_rate "
    "only as far as you really went, and put the block from evidence_manifest_render at the top of the answer. "
    "File arguments are relative to the work root and may not leave it. There is no tool for screen recording, "
    "installing software or the browser: those stay with the agent on the host."
)

EVIDENCE = {
    "none": {"channel": "none", "note": "Information about the machine or the plan. Not evidence about any video."},
    "media": {"channel": "none yet", "counts_as": "a media file was retrieved",
              "does_not_count_as": ["watched", "heard"],
              "note": "A file on disk has not been seen or heard. Extract frames and open them; transcribe the audio."},
    "captions": {"channel": "captions (text)", "counts_as": "captions read, once you read them",
                 "does_not_count_as": ["watched", "heard"],
                 "note": "Captions are text. Reading them is not watching the picture and not hearing the audio "
                         "(audio rating: captions-only)."},
    "frames": {"channel": "visual", "counts_as": "frames written to disk",
               "does_not_count_as": ["frames seen"],
               "note": "The frames exist; they count as seen only after you open the image files. List the ones "
                       "you opened in evidence_manifest_rate (frames_inspected)."},
    "asr": {"channel": "audio (speech to text)", "counts_as": "audio transcribed by a recogniser on this machine",
            "does_not_count_as": ["watched", "transcript read"],
            "note": "Recognised text can be wrong, most of all names and numbers. It is read only after you read it "
                    "(read_transcript keeps the log)."},
    "text": {"channel": "transcript (text)", "counts_as": "transcript text read, for the segments served",
             "does_not_count_as": ["watched", "heard"],
             "note": "Where the text came from decides the audio rating: a recogniser = transcribed, a caption "
                     "track = captions-only. Reading it is never 'watched'."},
    "alignment": {"channel": "alignment", "counts_as": "speech and frames paired by timestamp",
                  "does_not_count_as": ["frames seen", "heard"],
                  "note": "Pairing files by time does not add evidence to either channel."},
    "record": {"channel": "record keeping", "note": "The manifest records what was done. It adds no evidence."},
    "sheet": {"channel": "visual", "counts_as": "contact sheets written to disk",
              "does_not_count_as": ["frames seen", "frames seen at full size"],
              "note": "A sheet nobody opened counts for nothing. A sheet you opened counts as its frames seen as "
                      "tiles (reduced size): list the sheet id in frames_inspected. Small text and fine detail "
                      "still need the frame itself or a crop."},
    "view": {"channel": "none", "counts_as": "a page or a pack for a person to look at the record",
             "does_not_count_as": ["frames seen", "watched", "heard"],
             "note": "Made from the manifest. Making it, or opening it, adds no evidence to any channel."},
    "disclosure": {"channel": "disclosure", "note": "Generated from the manifest. Put it first in the answer, unchanged."},
}


# ---------------------------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------------------------

def work_root() -> str:
    return STATE["root"]


def inside(value: Any, what: str) -> str:
    """The real, absolute form of a path argument - or a refusal when it is not under the work root."""
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ToolError(f"{what}: a file path is needed.")
    path = Path(value)
    if os.name == "nt" and any(WINDOWS_DEVICE.fullmatch(part.split(".")[0].strip()) for part in path.parts):
        raise ToolError(f"{what}: '{value}' names a device, not a file.")
    if not path.is_absolute():
        path = Path(work_root()) / path
    real = os.path.realpath(str(path))               # follows links: a link that leaves the root is refused too
    root = work_root()
    try:
        common = os.path.commonpath([os.path.normcase(real), os.path.normcase(root)])
    except ValueError:                                # another drive, or a device path
        common = None
    if common != os.path.normcase(root):
        raise ToolError(f"{what}: '{value}' is outside the work root ({root}). Only files under the work root can "
                        "be used; start the server with --root to choose another folder.")
    return real


def web_url(value: Any) -> str:
    if (not isinstance(value, str) or len(value) > 4096
            or not re.fullmatch(r"https?://[^\s\x00-\x1f\x7f]+", value)):
        raise ToolError("url: an http:// or https:// address is needed. Local files go through the file tools.")
    return value


def plain(value: Any, what: str, pattern: str = r"[A-Za-z0-9][A-Za-z0-9.*,_:\-]{0,79}") -> str:
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ToolError(f"{what}: not a valid value: {value!r}")
    return value


def tail(text: str, limit: int) -> str:
    return text if len(text) <= limit else "[... %d characters cut ...]\n%s" % (len(text) - limit, text[-limit:])


def flag(argv: List[str], name: str, value: Any) -> None:
    """--name=value: one argument, so a value can never be taken for another option."""
    if value is not None and value != "":
        argv.append("%s=%s" % (name, value))


def switch(argv: List[str], name: str, on: Any) -> None:
    if on:
        argv.append(name)


def run_script(name: str, argv: List[str], evidence: str, timeout: Optional[float] = None) -> Dict[str, Any]:
    """Start one of the skill's scripts directly (no shell) and return what it printed."""
    script = SCRIPTS / name
    if not script.is_file():
        return {"ok": False, "reason": "script_not_in_this_installation", "script": name,
                "note": "This copy does not carry %s (the Docker image leaves out what only makes sense on the "
                        "host). Run it on the host instead." % name,
                "evidence": EVIDENCE["none"]}
    command = [sys.executable, "-B", str(script), *[str(a) for a in argv]]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    limit = float(timeout or DEFAULT_TIMEOUT)
    try:
        proc = subprocess.run(command, cwd=work_root(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=env, timeout=limit)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "timeout", "script": name, "arguments": [str(a) for a in argv],
                "timeout_seconds": limit, "evidence": EVIDENCE["none"],
                "note": "Stopped after the time limit. Nothing it may have written counts as complete."}
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    try:
        parsed = json.loads(out) if out.strip() else None
    except ValueError:
        parsed = None
    ok = proc.returncode == 0
    return {"ok": ok, "exit_code": proc.returncode, "script": name, "arguments": [str(a) for a in argv],
            "work_root": work_root(), "result": parsed,
            "stdout": None if parsed is not None else tail(out, 8000),
            "stderr": tail(err, 4000),
            "evidence": EVIDENCE[evidence] if ok else EVIDENCE["none"]}


# ---------------------------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------------------------

def about() -> Dict[str, Any]:
    """What this server is: its work root, the scripts it can run, and what it deliberately does not offer."""
    return {"ok": True, "server": SERVER_NAME, "version": SERVER_VERSION, "work_root": work_root(),
            "python": sys.version.split()[0],
            "scripts": sorted(p.stem for p in SCRIPTS.glob("*.py")) if SCRIPTS.is_dir() else [],
            "tools": [fn.__name__ for fn in TOOLS], "not_offered": NOT_OFFERED,
            "three_channels": INSTRUCTIONS, "evidence": EVIDENCE["none"]}


def probe_capabilities(url: Optional[str] = None, has_browser: Optional[str] = None,
                       network_test: bool = False, verbose: bool = False) -> Dict[str, Any]:
    """Report what the machine THIS SERVER RUNS ON can do (ffmpeg, yt-dlp, speech recognisers, routes).

    Inside Docker this describes the container, not the host: Route B and Route C are decided on the host.
    url: optional video address for a light yt-dlp check (nothing is downloaded).
    has_browser: "yes" or "no" - whether the agent has a browser tool that can run page scripts.
    """
    argv = ["--json"]
    switch(argv, "--no-network-test", not network_test)
    switch(argv, "--verbose", verbose)
    if url is not None:
        flag(argv, "--url", web_url(url))
    if has_browser is not None:
        flag(argv, "--has-browser", plain(has_browser, "has_browser", r"yes|no"))
    return run_script("probe_capabilities.py", argv, "none", timeout=300)


def setup_plan(tier: str = "base", whisper_engine: str = "auto") -> Dict[str, Any]:
    """Print the install plan for a tier (base, whisper, recording, all). Plan only: nothing is ever installed here."""
    argv = ["--json"]
    flag(argv, "--tier", plain(tier, "tier", r"base|whisper|recording|all"))
    flag(argv, "--whisper-engine", plain(whisper_engine, "whisper_engine", r"auto|faster-whisper|openai-whisper"))
    answer = run_script("setup_tools.py", argv, "none", timeout=300)
    answer["installed_anything"] = False
    if answer.get("exit_code") == 2:               # the plan has steps for a person: a result, not a failure
        answer["ok"] = True
    return answer


def fetch_media(url: str, what: str = "captions", out_dir: str = "video-work", lang: str = "en",
                no_auto_subs: bool = False, timeout_seconds: Optional[float] = None) -> Dict[str, Any]:
    """Route A: allowed retrieval with yt-dlp. what = info | captions | audio | video.

    The address is handed to yt-dlp and to nothing else. No browser login is used: a video that needs
    one is a decision for the person, on the host. Captions fetched here are text - reading them is
    neither watching nor hearing.
    """
    what = plain(what, "what", r"info|captions|audio|video")
    argv = [web_url(url)]
    flag(argv, "--out-dir", inside(out_dir, "out_dir"))
    flag(argv, "--lang", plain(lang, "lang"))
    argv.append("--" + what)
    switch(argv, "--no-auto-subs", no_auto_subs)
    return run_script("fetch_media.py", argv, {"info": "none", "captions": "captions"}.get(what, "media"),
                      timeout=timeout_seconds)


def extract_media_assets(video: str, out_dir: str = "video-assets", frame_mode: str = "hybrid",
                         detail: str = "balanced", start: Optional[str] = None, end: Optional[str] = None,
                         interval: Optional[float] = None, scene_threshold: Optional[float] = None,
                         max_frames: Optional[int] = None, at: Optional[str] = None, width: Optional[int] = None,
                         no_audio: bool = False, force: bool = False,
                         timeout_seconds: Optional[float] = None) -> Dict[str, Any]:
    """Cut frames (and audio.wav) from a local video into out_dir; writes frames.json.

    The frames are on disk afterwards, not seen: open the image files before saying anything about the picture.
    start / end / at take seconds or [hh:]mm:ss.
    """
    argv = [inside(video, "video")]
    flag(argv, "--out-dir", inside(out_dir, "out_dir"))
    flag(argv, "--frame-mode", plain(frame_mode, "frame_mode", r"hybrid|scene|interval"))
    flag(argv, "--detail", plain(detail, "detail"))
    for name, value in (("--start", start), ("--end", end), ("--at", at)):
        if value is not None:
            flag(argv, name, plain(value, name[2:], r"[0-9][0-9:.,\s]{0,400}"))
    flag(argv, "--interval", interval)
    flag(argv, "--scene-threshold", scene_threshold)
    flag(argv, "--max-frames", max_frames)
    flag(argv, "--width", width)
    switch(argv, "--no-audio", no_audio)
    switch(argv, "--force", force)
    return run_script("extract_media_assets.py", argv, "frames", timeout=timeout_seconds)


def transcribe_local(media: Optional[str] = None, output: Optional[str] = None, language: Optional[str] = None,
                     model: Optional[str] = None, backend: str = "auto", max_end: Optional[float] = None,
                     list_backends: bool = False, timeout_seconds: Optional[float] = None) -> Dict[str, Any]:
    """Speech to text on this machine (faster-whisper, openai-whisper or mlx-whisper, whichever is installed).

    list_backends=true only reports which recognisers can be imported. Otherwise media is audio.wav from
    extract_media_assets (or any media file) and an .srt is written beside it. The first use of a model
    downloads it. Set language: auto-detection guesses from the first seconds.
    """
    if list_backends:
        return run_script("transcribe_local.py", ["--list"], "none", timeout=300)
    if media is None:
        raise ToolError("media: a file is needed (or list_backends=true).")
    argv = [inside(media, "media")]
    if output is not None:
        flag(argv, "--output", inside(output, "output"))
    if language is not None:
        flag(argv, "--language", plain(language, "language"))
    if model is not None:
        flag(argv, "--model", plain(model, "model", r"[A-Za-z0-9][A-Za-z0-9._/\-]{0,99}"))
    flag(argv, "--backend", plain(backend, "backend", r"[a-z][a-z\-]{0,30}"))
    flag(argv, "--max-end", max_end)
    return run_script("transcribe_local.py", argv, "asr", timeout=timeout_seconds)


def align_transcript_frames(frames: str, transcript: Optional[str] = None, output: str = "timeline.json",
                            outline: Optional[str] = None, speech_source: str = "unspecified",
                            recording_offset: Optional[float] = None, transcript_shift: Optional[float] = None,
                            pad: Optional[float] = None, max_frames: Optional[int] = None) -> Dict[str, Any]:
    """Pair transcript segments with frames by time; writes timeline.json and visual_outline.json.

    speech_source labels where the text came from: transcribed | captions-only | heard | none | unspecified.
    Say captions-only for a caption track - pairing it with frames does not make it heard.
    """
    argv: List[str] = []
    flag(argv, "--frames", inside(frames, "frames"))
    if transcript is not None:
        flag(argv, "--transcript", inside(transcript, "transcript"))
    flag(argv, "--output", inside(output, "output"))
    if outline is not None:
        flag(argv, "--outline", inside(outline, "outline"))
    flag(argv, "--speech-source", plain(speech_source, "speech_source", r"transcribed|captions-only|heard|none|unspecified"))
    flag(argv, "--recording-offset", recording_offset)
    flag(argv, "--transcript-shift", transcript_shift)
    flag(argv, "--pad", pad)
    flag(argv, "--max-frames", max_frames)
    return run_script("align_transcript_frames.py", argv, "alignment", timeout=600)


def read_transcript(transcript: str, offset: int = 0, limit: int = 200, mode: str = "page",
                    duration: Optional[float] = None, gap_seconds: Optional[float] = None,
                    max_cues: Optional[int] = None, record_in_log: bool = True) -> Dict[str, Any]:
    """Read a transcript (.srt, .vtt, JSON) page by page; a log beside the file records how much was served.

    mode: page (segments from offset, use next_offset to go on) | status (how much has been served) |
    gaps (windows without speech) | cues (places where the speaker points at the picture).
    What you read here is text. It is never 'watched', and it is 'heard' only if a recogniser produced it.
    """
    mode = plain(mode, "mode", r"page|status|gaps|cues")
    argv = [inside(transcript, "transcript"), "--json"]
    if mode == "page":
        flag(argv, "--offset", int(offset))
        flag(argv, "--limit", int(limit))
        switch(argv, "--no-log", not record_in_log)
    else:
        argv.append("--" + mode)
    flag(argv, "--duration", duration)
    if mode == "gaps":
        flag(argv, "--gap-seconds", gap_seconds)
    if mode == "cues":
        flag(argv, "--max-cues", max_cues)
    return run_script("read_transcript.py", argv, "text" if mode in ("page", "cues") else "none", timeout=300)


def normalize_transcript(input: str, out: str = "transcript", merge: bool = False, gap: Optional[float] = None,
                         max_chars: Optional[int] = None, max_seconds: Optional[float] = None,
                         duration: Optional[float] = None) -> Dict[str, Any]:
    """Turn a caption file (json3, XML, VTT, SRT, or what a Route B snippet returned) into clean SRT and JSON.

    out is the output name without extension. The result is still caption text: captions-only for the audio rating.
    """
    argv = [inside(input, "input"), "--quiet"]
    flag(argv, "--out", inside(out, "out"))
    switch(argv, "--merge", merge)
    flag(argv, "--gap", gap)
    flag(argv, "--max-chars", max_chars)
    flag(argv, "--max-seconds", max_seconds)
    flag(argv, "--duration", duration)
    return run_script("normalize_transcript.py", argv, "captions", timeout=300)


def evidence_manifest_init(source: str, manifest: str = "evidence_manifest.json", title: Optional[str] = None,
                           source_duration: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    """Start the evidence manifest for one video. source is its address, or a local file under the work root."""
    argv = ["init"]
    flag(argv, "--manifest", inside(manifest, "manifest"))
    flag(argv, "--source", source if re.match(r"https?://", str(source)) and web_url(source) else inside(source, "source"))
    flag(argv, "--title", title)
    flag(argv, "--source-duration", source_duration)
    switch(argv, "--force", force)
    return run_script("evidence_manifest.py", argv, "record", timeout=120)


def evidence_manifest_route(route: str, status: str, manifest: str = "evidence_manifest.json", reason: str = "") -> Dict[str, Any]:
    """Record a route attempt: route 0 | A | B | C, status succeeded | partial | failed | blocked | skipped."""
    argv = ["route"]
    flag(argv, "--manifest", inside(manifest, "manifest"))
    flag(argv, "--route", plain(route, "route", r"0|A|B|C"))
    flag(argv, "--status", plain(status, "status", r"succeeded|partial|failed|blocked|skipped"))
    flag(argv, "--reason", reason)
    return run_script("evidence_manifest.py", argv, "record", timeout=120)


def evidence_manifest_add(kind: str, path: str, manifest: str = "evidence_manifest.json", command: str = "",
                          caption_origin: Optional[str] = None, language: Optional[str] = None,
                          speech_confirmed: bool = False, time: Optional[str] = None,
                          confirmed_shows_video: bool = False, transcript_source: Optional[str] = None,
                          note: str = "") -> Dict[str, Any]:
    """Record a product file (frames.json, a transcript, captions, a screenshot ...) with its hash.

    kind transcript needs transcript_source: asr | cloud-asr | captions | manual. Use kind captions (or
    transcript_source captions) for caption text: the manifest then keeps it out of the 'heard' channel.
    command is the text of the command that produced the file; it is recorded, never run.
    """
    argv = ["add"]
    flag(argv, "--manifest", inside(manifest, "manifest"))
    flag(argv, "--kind", plain(kind, "kind", r"[a-z][a-z_\-]{0,40}"))
    flag(argv, "--path", inside(path, "path"))
    flag(argv, "--command", command)
    if caption_origin is not None:
        flag(argv, "--caption-origin", plain(caption_origin, "caption_origin", r"[a-z][a-z_\-]{0,40}"))
    if language is not None:
        flag(argv, "--language", plain(language, "language"))
    switch(argv, "--speech-confirmed", speech_confirmed)
    flag(argv, "--time", time)
    switch(argv, "--confirmed-shows-video", confirmed_shows_video)
    if transcript_source is not None:
        flag(argv, "--transcript-source", plain(transcript_source, "transcript_source", r"asr|cloud-asr|captions|manual"))
    flag(argv, "--note", note)
    return run_script("evidence_manifest.py", argv, "record", timeout=600)


def evidence_manifest_rate(visual: str, audio: str, alignment: str, manifest: str = "evidence_manifest.json",
                           frames_inspected: str = "", on_screen_text: Optional[str] = None,
                           on_screen_note: str = "", on_screen_frames: Optional[str] = None,
                           visual_evidence: Optional[str] = None, audio_evidence: Optional[str] = None,
                           alignment_evidence: Optional[str] = None, gaps: Optional[List[str]] = None,
                           source_duration: Optional[str] = None, media_covers: Optional[str] = None,
                           transcript_read: Optional[str] = None) -> Dict[str, Any]:
    """Rate each channel as far as you really went - the script checks the ratings against the recorded files.

    visual: none | second-hand | sampled | continuous.   frames_inspected: the frame ids you opened.
    audio: none | second-hand | captions-only | transcribed | heard.   Caption text is captions-only.
    alignment: none | chapter-level | timestamp-aligned.   gaps: known limits, one sentence each.
    """
    argv = ["rate"]
    flag(argv, "--manifest", inside(manifest, "manifest"))
    flag(argv, "--visual", plain(visual, "visual", r"none|second-hand|sampled|continuous"))
    flag(argv, "--audio", plain(audio, "audio", r"none|second-hand|captions-only|transcribed|heard"))
    flag(argv, "--alignment", plain(alignment, "alignment", r"none|chapter-level|timestamp-aligned"))
    flag(argv, "--frames-inspected", frames_inspected)
    flag(argv, "--on-screen-text", on_screen_text)
    flag(argv, "--on-screen-note", on_screen_note)
    flag(argv, "--on-screen-frames", on_screen_frames)
    flag(argv, "--visual-evidence", visual_evidence)
    flag(argv, "--audio-evidence", audio_evidence)
    flag(argv, "--alignment-evidence", alignment_evidence)
    for gap in gaps or []:
        flag(argv, "--gap", gap)
    flag(argv, "--source-duration", source_duration)
    flag(argv, "--media-covers", media_covers)
    flag(argv, "--transcript-read", transcript_read)
    return run_script("evidence_manifest.py", argv, "record", timeout=120)


def evidence_manifest_verify(manifest: str = "evidence_manifest.json") -> Dict[str, Any]:
    """Hash every recorded file again and check the ratings against them. ok=false means the manifest does not hold."""
    argv = ["verify"]
    flag(argv, "--manifest", inside(manifest, "manifest"))
    return run_script("evidence_manifest.py", argv, "record", timeout=600)


def evidence_manifest_render(manifest: str = "evidence_manifest.json", output: Optional[str] = None,
                             format: str = "markdown", allow_unverified: bool = False) -> Dict[str, Any]:
    """Produce the disclosure block from the manifest (in 'text', or written to output). It goes first in the answer."""
    argv = ["render"]
    flag(argv, "--manifest", inside(manifest, "manifest"))
    target = inside(output, "output") if output is not None else None
    flag(argv, "--output", target)
    flag(argv, "--format", plain(format, "format", r"markdown|json"))
    switch(argv, "--allow-unverified", allow_unverified)
    answer = run_script("evidence_manifest.py", argv, "disclosure", timeout=120)
    if answer.get("ok"):
        if target is not None:
            answer["text"] = Path(target).read_text(encoding="utf-8")
        elif answer.get("stdout") is not None:
            answer["text"] = answer["stdout"]
        else:
            answer["text"] = json.dumps(answer.get("result"), ensure_ascii=False, indent=2)
    return answer


def contact_sheet(frames: str, out_dir: Optional[str] = None, only: Optional[str] = None,
                  start: Optional[str] = None, end: Optional[str] = None, columns: int = 4, rows: int = 3,
                  tile_width: int = 480) -> Dict[str, Any]:
    """Put extracted frames on contact sheets (a grid, each tile labelled #INDEX TIME); writes sheets.json.

    For looking over many frames at once before opening the ones that matter. only: frame indexes such as
    1,3-8. A sheet you open counts as its frames seen as tiles, not at full size; a sheet you did not open
    counts for nothing. Register sheets.json with evidence_manifest_add (kind contact-sheets).
    """
    argv: List[str] = []
    flag(argv, "--frames", inside(frames, "frames"))
    if out_dir is not None:
        flag(argv, "--out-dir", inside(out_dir, "out_dir"))
    if only is not None:
        flag(argv, "--only", plain(only, "only", r"[0-9][0-9,\-\s]{0,400}"))
    for name, value in (("--start", start), ("--end", end)):
        if value is not None:
            flag(argv, name, plain(value, name[2:], r"[0-9][0-9:.]{0,20}"))
    flag(argv, "--columns", int(columns))
    flag(argv, "--rows", int(rows))
    flag(argv, "--tile-width", int(tile_width))
    return run_script("contact_sheet.py", argv, "sheet", timeout=900)


def evidence_manifest_view(manifest: str = "evidence_manifest.json", output: Optional[str] = None,
                           video: Optional[str] = None, no_video: bool = False,
                           link_pictures: bool = False) -> Dict[str, Any]:
    """Write one HTML file that shows the record: timeline, frames with their seen / not-opened state, text, claims.

    It opens offline and loads nothing from the network. video: the file for the player (under the work
    root); without it the recorded media file is used when it is under the work root. The page is for a
    person to look at - making it adds no evidence.
    """
    argv = ["view"]
    flag(argv, "--manifest", inside(manifest, "manifest"))
    if output is not None:
        flag(argv, "--output", inside(output, "output"))
    if video is not None:
        flag(argv, "--video", inside(video, "video"))
    switch(argv, "--no-video", no_video)
    switch(argv, "--link-pictures", link_pictures)
    flag(argv, "--within", work_root())
    return run_script("evidence_manifest.py", argv, "view", timeout=900)


def evidence_manifest_pack(manifest: str = "evidence_manifest.json", output: Optional[str] = None,
                           include_video: bool = False, video: Optional[str] = None, all_frames: bool = False,
                           accept_findings: bool = False) -> Dict[str, Any]:
    """Zip the view page, a copy of the manifest with relative paths, the pictures used and the transcripts.

    The video stays out unless include_video is true (it can be large, and it can be private). Before
    anything is written the texts are checked for local paths, email addresses and keys: with findings
    nothing is packed (ok=false) until the person has looked and accept_findings is true.
    """
    argv = ["pack"]
    flag(argv, "--manifest", inside(manifest, "manifest"))
    if output is not None:
        flag(argv, "--output", inside(output, "output"))
    switch(argv, "--include-video", include_video)
    if video is not None:
        flag(argv, "--video", inside(video, "video"))
    switch(argv, "--all-frames", all_frames)
    switch(argv, "--accept-findings", accept_findings)
    flag(argv, "--within", work_root())
    return run_script("evidence_manifest.py", argv, "view", timeout=1800)


def evidence_manifest_lint(file: str, anywhere: bool = False) -> Dict[str, Any]:
    """Check the disclosure block of a written answer (a Markdown file) against the format."""
    argv = ["lint"]
    flag(argv, "--file", inside(file, "file"))
    switch(argv, "--anywhere", anywhere)
    return run_script("evidence_manifest.py", argv, "record", timeout=120)


TOOLS = [about, probe_capabilities, setup_plan, fetch_media, extract_media_assets, transcribe_local,
         align_transcript_frames, read_transcript, normalize_transcript, evidence_manifest_init,
         evidence_manifest_route, evidence_manifest_add, evidence_manifest_rate, evidence_manifest_verify,
         evidence_manifest_render, evidence_manifest_lint, contact_sheet, evidence_manifest_view,
         evidence_manifest_pack]


# ---------------------------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", help="Work root: the only folder whose files the tools may read or write. "
                                       "Default: WVLH_MCP_ROOT, else the folder this was started in.")
    parser.add_argument("--list-tools", action="store_true",
                        help="Print the tool names as JSON and exit (works without the MCP SDK).")
    args = parser.parse_args()
    if args.list_tools:
        print(json.dumps({"server": SERVER_NAME, "version": SERVER_VERSION, "tools": [fn.__name__ for fn in TOOLS],
                          "not_offered": sorted(NOT_OFFERED)}, indent=2))
        return 0
    root = args.root or os.environ.get("WVLH_MCP_ROOT") or os.getcwd()
    if not os.path.isdir(root):
        print("mcp_server: the work root is not a folder: %s" % root, file=sys.stderr)
        return 2
    STATE["root"] = os.path.realpath(root)
    try:
        try:
            from mcp.server import MCPServer as Server                   # MCP SDK 2.x
        except ImportError:
            from mcp.server.fastmcp import FastMCP as Server             # MCP SDK 1.x
    except ImportError as exc:
        print("mcp_server: the MCP SDK is not installed for this Python (%s: %s).\n"
              "  It is needed only by this server; the skill's scripts work without it.\n"
              "  Install it (Python 3.11 or later):  %s -m pip install -r %s\n"
              "  Or use the Docker image, which has it:  docker run -i --rm -v DIR:/work IMAGE mcp"
              % (sys.executable, exc, sys.executable, HERE / "requirements.txt"), file=sys.stderr)
        return 3
    server = Server(SERVER_NAME, instructions=INSTRUCTIONS)
    for fn in TOOLS:
        server.tool()(fn)
    print("mcp_server: %s %s, work root %s, %d tools, stdio" % (SERVER_NAME, SERVER_VERSION, STATE["root"], len(TOOLS)),
          file=sys.stderr)
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
