#!/usr/bin/env python3
"""Keep a traceable evidence manifest for one video analysis (v5.3).

evidence_manifest.json records which route was used (and which failed first), every
product file with its path, SHA-256 and the command that produced it, the rating of each
evidence channel, and optional claim-to-evidence links. `verify` re-hashes every file and
refuses ratings the files cannot support; `render` prints the "What I Actually Did"
disclosure block straight from the manifest, each line tagged with the evidence ids it
rests on.

Typical run
-----------
  python evidence_manifest.py init   -m WORK/evidence_manifest.json --source URL_OR_FILE
  python evidence_manifest.py route  -m WORK/evidence_manifest.json --route A --status succeeded --reason "yt-dlp download"
  python evidence_manifest.py add    -m WORK/evidence_manifest.json --kind frames --path WORK/frames.json --command "python scripts/extract_media_assets.py ..."
  python evidence_manifest.py add    -m WORK/evidence_manifest.json --kind transcript --path WORK/transcript.srt --transcript-source asr --command "whisper ..."
  python evidence_manifest.py add    -m WORK/evidence_manifest.json --kind visual_outline --path WORK/visual_outline.json --command "python scripts/align_transcript_frames.py ..."
  python evidence_manifest.py rate   -m WORK/evidence_manifest.json --visual sampled --frames-inspected E1.f001,E1.f004 --audio transcribed --alignment timestamp-aligned
  python evidence_manifest.py claim  -m WORK/evidence_manifest.json --text "The speaker shows a state diagram at 01:35" --evidence E2.f004,E3
  python evidence_manifest.py verify -m WORK/evidence_manifest.json
  python evidence_manifest.py render -m WORK/evidence_manifest.json

v5.3 - note-grade records
-------------------------
  python evidence_manifest.py add   -m M --kind crops --path WORK/crops.json --command "python scripts/crop_frame_region.py ..."
  python evidence_manifest.py claim -m M --text "..." --start 01:35 --end 01:52 --frames E1.f004,E5.c001 --segments 41-44 --assessment confirmed
  python evidence_manifest.py claim -m M --text "..." --start 02:10 --end 02:30 --segments 51-53 --assessment transcript-only
  python evidence_manifest.py issue -m M --start 03:05 --end 03:12 --summary "Option letter hidden by the cursor" --attempted "frames at 03:05 and 03:09" --attempted "crop of the answer row" --unresolved-reason "the letter is never uncovered"
  python evidence_manifest.py issue-update -m M --id I1 --status resolved --note "visible at 03:40, crop E5.c002"
  python evidence_manifest.py rate  ... --transcript-read full     # checked against read_transcript.py's read log
  python evidence_manifest.py list  -m M                           # claims and issues as Markdown tables

v5.4 - after real-video tests on Windows and macOS
--------------------------------------------------
  python evidence_manifest.py route -m M --route C --status partial --reason "audio clean; picture covered from 00:35"
  python evidence_manifest.py rate  ... --source-duration 7:46      # the real video's length; a recording
                                                                    # that covers part of it gets a "Partial" verdict
  python evidence_manifest.py rate  ... --on-screen-text "on-screen text" --on-screen-frames E1.f066
  python evidence_manifest.py claim ... --segments 22-24 --transcript E5   # required when captions AND a transcript are recorded
  python evidence_manifest.py claim-update -m M --id C2 --status withdrawn --note "misread the frame"
  python evidence_manifest.py init  -m M --source URL --source-duration 7:46
  python evidence_manifest.py rate  ... --on-screen-note "labels 'Horizon', '~5 km'"
  python evidence_manifest.py route -m M --route A --status succeeded --browser-login firefox   # with the user's yes

A claim record keeps the time range, the statement, the frame / crop ids, the transcript segment
indices (with the text they had when the claim was made) and a judgement. Saving a claim checks
that the references exist; it does not certify that the statement is true. An issue keeps what
could not be settled, what was tried and why it stayed open - never a guessed answer.
"""

from __future__ import annotations

import os
import sys

# macOS: a python.org framework Python (seen with 3.7) leaves __PYVENV_LAUNCHER__ in the environment.
# A child that inherits it - uv, the private environment's interpreter, a tool installed there -
# takes the wrong interpreter for its own. This process has already read the variable at start-up;
# nothing started from here should see it.
os.environ.pop("__PYVENV_LAUNCHER__", None)


def _interpreter_flags():
    """The options this interpreter was started with, for the interpreter that takes over or is asked."""
    flags, out = sys.flags, []
    if flags.isolated or (getattr(flags, "safe_path", False) and flags.ignore_environment):
        out.append("-I")
    else:
        if flags.ignore_environment:
            out.append("-E")
        if flags.no_user_site:
            out.append("-s")
    if flags.dont_write_bytecode:
        out.append("-B")
    if flags.optimize:
        out.append("-" + "O" * min(int(flags.optimize), 2))
    if getattr(sys.stdout, "write_through", False):
        out.append("-u")
    for option in sys.warnoptions:
        out += ["-W", option]
    for name in ("utf8", "dev", "faulthandler"):
        value = getattr(sys, "_xoptions", {}).get(name)
        if value is not None:
            out += ["-X", name if value is True else "%s=%s" % (name, value)]
    return out


def _continue_under(python, marker):
    """Run this same script under another interpreter: same interpreter options, same arguments.

    On macOS and Linux this process BECOMES the other one (same process id), so whoever stops it by
    that id - a person, a host, a timeout - really stops the work. Windows has no such call: the work
    runs in a child. Ctrl+C and Ctrl+Break reach both, and this process waits for the child to finish
    cleaning up. A forced end (TerminateProcess) reaches only the process it names - see
    references/recording-notes.md.
    """
    env = dict(os.environ)
    env[marker] = "1"
    if getattr(sys.flags, "safe_path", False):
        env["PYTHONSAFEPATH"] = "1"
    command = [python] + _interpreter_flags() + [os.path.abspath(__file__)] + sys.argv[1:]
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (AttributeError, ValueError, OSError):
            pass
    if os.name != "nt":
        os.execve(python, command, env)
    import subprocess
    child = subprocess.Popen(command, env=env)
    try:
        while True:
            try:
                return child.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                continue
            except KeyboardInterrupt:      # the child got the same Ctrl+C; it decides how to finish
                continue
    finally:
        if child.poll() is None:
            child.kill()


if sys.version_info < (3, 9):  # checked before anything else, so an old interpreter gets a clear answer
    # Too old to run this script. When setup_tools.py has made a private Python, hand over to it.
    # (Everything down to here must stay valid for Python 3.7: no syntax newer than that.)
    _venv = os.path.join(os.environ.get("WVLH_HOME") or os.path.join(os.path.expanduser("~"), ".watch-video-like-human"),
                         "venv")
    _private = os.path.join(_venv, "Scripts", "python.exe") if os.name == "nt" else os.path.join(_venv, "bin", "python")
    _problem = "and there is no private Python in %s yet." % _venv
    _then = ("With the user's yes, the same command plus --yes creates a private Python there; the system\n"
             "Python is not touched, and after that this script hands over to it by itself.")
    if os.path.isfile(_private):
        _then = ("It lists the steps to replace that folder. Nothing there is deleted or moved for you.")
        if os.environ.get("WVLH_OLD_PYTHON_HANDOFF"):      # one hand-over only: never a loop
            _problem = "and that IS the private Python in %s: it is too old as well." % _venv
        else:
            sys.stderr.write("Python %d.%d is too old for this script; running it under %s instead.\n"
                             % (sys.version_info[0], sys.version_info[1], _private))
            try:
                sys.exit(_continue_under(_private, "WVLH_OLD_PYTHON_HANDOFF"))
            except OSError as _error:
                _problem = "and the private Python %s cannot be started (%s)." % (_private, _error)
    elif os.path.lexists(_private):      # a link whose target is gone
        _problem = "and the private Python %s cannot be started (what it links to is gone)." % _private
        _then = ("It lists the steps to replace that folder. Nothing there is deleted or moved for you.")
    sys.exit("This script needs Python 3.9 or newer; this interpreter is Python %d.%d,\n"
             "%s\n"
             "See what to do (this installs nothing):\n"
             "  \"%s\" \"%s\"\n"
             "%s"
             % (sys.version_info[0], sys.version_info[1], _problem, sys.executable,
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup_tools.py"), _then))
os.environ.pop("WVLH_OLD_PYTHON_HANDOFF", None)      # it has done its job; nothing started from here needs it


def _private_tools_first():
    """Put the folder that setup_tools.py manages, if it exists, at the front of PATH."""
    home = os.environ.get("WVLH_HOME") or os.path.join(os.path.expanduser("~"), ".watch-video-like-human")
    for sub in ("bin", os.path.join("venv", "Scripts" if os.name == "nt" else "bin")):
        folder = os.path.join(home, sub)
        if os.path.isdir(folder) and folder not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")


_private_tools_first()

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "evidence-manifest/1"
SKILL_VERSION = "5.4"
ROUTES = {"0": "0 - user file", "A": "A - download", "B": "B - browser extraction",
          "C": "C - screen + loopback recording"}
KINDS = ["media", "audio", "frames", "captions", "transcript", "timeline", "visual_outline",
         "metadata", "screenshot", "continuous-analysis", "audio-native-analysis",
         "keyframe-analysis", "native-model-report", "crops", "evidence-draft", "notes",
         "recording-check", "other"]
CAPTION_ORIGINS = {"human": "human-written captions", "auto-asr": "auto-generated (machine speech recognition) captions",
                   "translated": "machine-translated captions",
                   "human-translation": "captions translated by people (not the language spoken; a translation, "
                                        "not what was said)",
                   "unknown": "captions of unknown origin"}
BLOCKED_VERDICT = "No reliable video analysis"
# "second-hand" = an external OCR engine, vision model or native video model reported it; the
# answering model did not see or hear it. It ranks below every first-hand level.
VISUAL = ["none", "second-hand", "sampled", "continuous"]
AUDIO = ["none", "second-hand", "captions-only", "transcribed", "heard"]
ALIGNMENT = ["none", "chapter-level", "timestamp-aligned"]
EXTERNAL_OCR = "external OCR text (second-hand)"
PICTURE_TEXT = "on-screen text"     # titles, slides, credits, a player's overlaid captions: text in the picture
ON_SCREEN = ["none", EXTERNAL_OCR, "burned-in caption text", PICTURE_TEXT]
READ_BY_MODEL = ("burned-in caption text", PICTURE_TEXT)
PARTIAL_BELOW = 0.9   # the media covers less than this share of the video -> the verdict says "Partial"
SECOND_HAND_KINDS = ("keyframe-analysis", "native-model-report")
# Judgement on one claim -> the tag it carries in drafts and notes ("" = no tag needed).
ASSESSMENTS = {
    "confirmed": "",                      # the transcript says it and an inspected picture shows it
    "transcript-only": "[仅转录]",          # said, but no picture was found that shows it
    "picture-only": "[仅画面、未讲解]",       # on screen, never explained in speech
    "unverified": "[待证]",                # could not be settled from the material
    "conflict": "[待证]",                  # transcript and picture disagree and it is unresolved
    "not-understood": "[未理解]",           # the material is there but its meaning is unclear
}
ISSUE_STATUS = ["open", "resolved", "wont-fix"]
CHUNK_SEGMENT_SECONDS = 30.0
READ_LEVELS = ["full", "partial", "none"]
TIME_RE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})(?:[,.](\d{1,3}))?")


def safe_stdio() -> None:
    """Never let a character the console cannot encode crash the script (cp936, cp1252, ...)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def clock(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    total = int(max(0, seconds))
    hours, minutes, secs = total // 3600, (total % 3600) // 60, total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def load(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Manifest not found: {path}. Run `init` first.")
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, manifest: dict) -> None:
    manifest["updated"] = now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def file_record(path: Path, manifest_path: Path) -> dict:
    record = {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
    try:
        record["relpath"] = path.relative_to(manifest_path.parent).as_posix()
    except ValueError:
        pass
    return record


def resolve(record: dict, manifest_path: Path) -> Path | None:
    """Find a recorded file: the absolute path first, then relative to the manifest (moved folder)."""
    direct = Path(record["path"])
    if direct.is_file():
        return direct
    if record.get("relpath"):
        moved = manifest_path.parent / record["relpath"]
        if moved.is_file():
            return moved
    return None


# ---------------------------------------------------------------- transcript facts

def parse_clock(value: str) -> float:
    match = TIME_RE.search(value)
    if not match:
        raise ValueError(value)
    millis = int((match.group(4) or "0").ljust(3, "0")[:3])
    return int(match.group(1) or 0) * 3600 + int(match.group(2)) * 60 + int(match.group(3)) + millis / 1000


def transcript_segments(path: Path) -> list[dict]:
    """Segments in file order, empty ones skipped. Index = 1-based position in this list.

    read_transcript.py carries the same function; the two must number segments identically.
    """
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    out: list[dict] = []
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("segments", data.get("transcript", []))
        for item in data:
            if isinstance(item, dict) and str(item.get("text", "")).strip():
                start = float(item.get("start", item.get("start_seconds", 0)) or 0)
                end = float(item.get("end", item.get("end_seconds", start)) or start)
                out.append({"start": start, "end": max(end, start), "text": " ".join(str(item["text"]).split())})
    else:
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            if "-->" in lines[i]:
                left, right = lines[i].split("-->", 1)
                body = []
                i += 1
                while i < len(lines) and lines[i].strip() and "-->" not in lines[i]:
                    body.append(lines[i].strip())
                    i += 1
                if body and i < len(lines) and "-->" in lines[i]:
                    body.pop()  # the next cue's number or id, when no blank line separates the cues
                joined = " ".join(re.sub(r"<[^>]+>", "", " ".join(body)).split())
                if joined:
                    start = parse_clock(left)
                    out.append({"start": start, "end": max(parse_clock(right), start), "text": joined})
            else:
                i += 1
    for n, seg in enumerate(out, start=1):
        seg["index"] = n
    return out


FILLER_RE = re.compile(r"^(?:o+h+|a+h+|u+h+|m+|h+m+|(?:la)+|(?:na)+|yeah|you|thank|thanks|for|watching|music|applause|"
                       r"\u266a+|\[.*?\]|\(.*?\)|[\W_]+)$", re.I)


def speech_doubt(segments: list[dict]) -> dict | None:
    """Does this recognised transcript look like noise over music rather than speech?

    A recogniser run over a track with no voice still prints something: "Oh, oh, oh...", "la la",
    "Thank you." (field test: a music-only video came back as a transcript and was disclosed as
    'transcribed'). This looks only at the text - how repetitive it is and how much of it is
    filler - and never decides alone: it adds a warning that a person or the agent must settle.
    """
    words = [w for seg in segments for w in re.findall(r"[^\W_]+", seg["text"].lower())]
    if len(segments) < 2 or len(words) < 4:
        return None
    unique = len(set(words)) / len(words)
    filler = sum(1 for seg in segments
                 if all(FILLER_RE.match(part.strip()) for part in re.split(r"[,.!?;\u3001\u3002\s]+", seg["text"]) if part.strip()))
    filler_share = filler / len(segments)
    cjk = sum(1 for w in words if any("\u3040" <= ch <= "\u9fff" for ch in w))
    if cjk > len(words) / 2:               # unspaced scripts: one "word" per segment says nothing about variety
        unique = max(unique, 0.5) if filler_share < 0.6 else unique
    # A recogniser over music also prints a line and then prints it again: the same sentence in
    # two segments, or one segment that says its phrase twice ("get it started, get it started").
    tokens = [re.findall(r"[^\W_]+", seg["text"].lower()) for seg in segments]
    keys = [" ".join(tok) for tok in tokens]

    def echo(tok: list) -> bool:
        half = len(tok) // 2
        return len(tok) >= 4 and len(tok) % 2 == 0 and tok[:half] == tok[half:]
    suspicious = sum(1 for i, seg in enumerate(segments)
                     if (keys[i] and keys.count(keys[i]) > 1) or echo(tokens[i])
                     or all(FILLER_RE.match(part.strip())
                            for part in re.split(r"[,.!?;\u3001\u3002\s]+", seg["text"]) if part.strip()))
    repeat_share = suspicious / len(segments)
    spoken = sum(max(0.0, seg["end"] - seg["start"]) for seg in segments)
    span = max(seg["end"] for seg in segments) - min(seg["start"] for seg in segments)
    thin = span >= 60 and spoken / span < 0.25          # a few lines scattered over minutes
    if unique < 0.2 or filler_share >= 0.6 or repeat_share >= 0.6 or (thin and repeat_share >= 0.4):
        return {"unique_word_ratio": round(unique, 2), "filler_segment_share": round(filler_share, 2),
                "repeated_or_filler_segment_share": round(repeat_share, 2),
                "speech_share_of_span": round(spoken / span, 2) if span > 0 else None,
                "words": len(words), "segments": len(segments)}
    return None


def transcript_facts(path: Path) -> dict:
    """Segment count and covered span of an .srt / .vtt / JSON transcript. Best effort."""
    try:
        segments = transcript_segments(path)
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        return {"segments": None}
    if not segments:
        return {"segments": 0}
    lengths = sorted(s["end"] - s["start"] for s in segments)
    return {"segments": len(segments), "first_start": round(min(s["start"] for s in segments), 3),
            "last_end": round(max(s["end"] for s in segments), 3),
            "median_segment_seconds": round(lengths[len(lengths) // 2], 2),
            "speech_doubt": speech_doubt(segments)}


def parse_seconds(value: str | None, label: str) -> float | None:
    """'95', '95.5', '01:35' or '1:02:03.250' -> seconds."""
    if value is None or str(value).strip() == "":
        return None
    seconds = 0.0
    try:
        for piece in str(value).strip().split(":"):
            seconds = seconds * 60 + float(piece)
    except ValueError:
        raise SystemExit(f"{label} must be seconds or [hh:]mm:ss, got: {value}")
    if seconds < 0:
        raise SystemExit(f"{label} must not be negative.")
    return round(seconds, 3)


def parse_indices(value: str | None) -> list[int]:
    """'41-44,50' -> [41, 42, 43, 44, 50]. 1-based transcript segment indices."""
    out: set[int] = set()
    for part in split_ids(value):
        try:
            if "-" in part:
                low, high = (int(p) for p in part.split("-", 1))
            else:
                low = high = int(part)
        except ValueError:
            raise SystemExit(f"--segments takes 1-based indices such as 41-44,50. Got: {part}")
        if low < 1 or high < low or high - low > 2000:
            raise SystemExit(f"--segments range is not valid: {part}")
        out.update(range(low, high + 1))
    return sorted(out)


def read_log_state(transcript: Path) -> dict:
    """What read_transcript.py recorded for this exact transcript file."""
    log_path = transcript.with_name(transcript.name + ".readlog.json")
    try:
        log = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"found": False, "complete": False, "served": 0, "total": None}
    if log.get("transcript_sha256") != sha256_file(transcript):
        return {"found": True, "complete": False, "served": 0, "total": None, "stale": True}
    served = sum(max(0, int(e) - int(b)) for b, e in log.get("served", []))
    total = int(log.get("total_segments") or 0)
    return {"found": True, "complete": total > 0 and served >= total, "served": served, "total": total}


# ---------------------------------------------------------------- commands

def cmd_init(args) -> int:
    path = Path(args.manifest).expanduser().resolve()
    if path.exists() and not args.force:
        raise SystemExit(f"{path} already exists. Pass --force to start over.")
    manifest = {"schema": SCHEMA, "skill_version": SKILL_VERSION, "created": now(), "updated": now(),
                "source": {"input": args.source, "title": args.title,
                           "video_duration_seconds": parse_seconds(getattr(args, "source_duration", None),
                                                                   "--source-duration")},
                "route": {"used": None, "history": []},
                "artifacts": [], "ratings": {}, "claims": [], "issues": [], "gaps": []}
    save(path, manifest)
    print(json.dumps({"manifest": str(path), "created": True}))
    return 0


def cmd_route(args) -> int:
    path = Path(args.manifest).expanduser().resolve()
    manifest = load(path)
    entry = {"route": args.route, "status": args.status, "reason": args.reason, "at": now()}
    if args.browser_login:
        if args.route != "A":
            raise SystemExit("--browser-login records fetch_media.py --cookies-from-browser, which is Route A only.")
        entry["browser_login"] = args.browser_login.strip().lower()
    manifest["route"]["history"].append(entry)
    if args.status in ("succeeded", "partial"):
        manifest["route"]["used"] = args.route
        manifest["route"].pop("blocked", None)      # an earlier blocked route no longer describes this one
        if args.status == "partial":
            manifest["route"]["partial"] = True
        else:
            manifest["route"].pop("partial", None)
    elif args.status == "blocked" and manifest["route"]["used"] is None:
        manifest["route"]["used"] = args.route
        manifest["route"]["blocked"] = True
    save(path, manifest)
    print(json.dumps({"route_used": manifest["route"]["used"], "history": len(manifest["route"]["history"])}))
    return 0


def next_id(manifest: dict) -> str:
    return f"E{len(manifest['artifacts']) + 1}"


def add_artifact(manifest: dict, manifest_path: Path, kind: str, file_path: Path, command: str,
                 note: str = "", details: dict | None = None) -> dict:
    artifact = {"id": next_id(manifest), "kind": kind, **file_record(file_path, manifest_path),
                "produced_by": command or "unrecorded", "recorded_at": now()}
    if note:
        artifact["note"] = note
    if details:
        artifact["details"] = details
    manifest["artifacts"].append(artifact)
    return artifact


def cmd_add(args) -> int:
    path = Path(args.manifest).expanduser().resolve()
    manifest = load(path)
    target = Path(args.path).expanduser().resolve()
    if not target.is_file():
        raise SystemExit(f"File not found: {target}")
    added = []

    if args.kind == "frames":
        meta = json.loads(target.read_text(encoding="utf-8"))
        frames_dir = Path(meta.get("frames_dir", target.parent / "frames"))
        if not frames_dir.is_dir():
            frames_dir = target.parent / "frames"
        frames = []
        for frame in meta.get("frames", []):
            frame_path = frames_dir / frame["file"]
            if not frame_path.is_file():
                raise SystemExit(f"frames.json lists a frame that does not exist: {frame_path}")
            frames.append({"n": frame.get("index"), "time_seconds": frame["time_seconds"],
                           "reason": frame.get("reason"), **file_record(frame_path, path)})
        details = {"frame_mode": meta.get("frame_mode"), "duration_seconds": meta.get("duration_seconds"),
                   "source_media": meta.get("source"), "source_sha256": meta.get("source_sha256"),
                   "audio_in_file": meta.get("audio"), "has_audio_stream": meta.get("has_audio_stream"),
                   "dropped_frames": len(meta.get("dropped_frames", [])), "frames": frames,
                   "frame_set_id": meta.get("frame_set_id"),
                   "dropped_by_reason": meta.get("dropped_by_reason") or {}}
        artifact = add_artifact(manifest, path, "frames", target, args.command, args.note, details)
        for frame in frames:
            frame["id"] = f"{artifact['id']}.f{int(frame['n'] or 0):03d}"
        added.append(artifact["id"])
        if meta.get("source_sha256") and not manifest["source"].get("media_sha256"):
            manifest["source"]["media_sha256"] = meta["source_sha256"]
        if meta.get("duration_seconds") and not manifest["source"].get("duration_seconds"):
            manifest["source"]["duration_seconds"] = meta["duration_seconds"]
        audio = meta.get("audio")
        if audio not in (None, "none", "skipped", "failed"):
            audio_path = Path(audio) if Path(audio).is_file() else target.parent / "audio.wav"
            if audio_path.is_file():
                wav = add_artifact(manifest, path, "audio", audio_path, args.command,
                                   "audio track extracted from the same media file")
                added.append(wav["id"])
    elif args.kind == "crops":
        meta = json.loads(target.read_text(encoding="utf-8"))
        crops_dir = Path(meta.get("crops_dir", target.parent / "crops"))
        if not crops_dir.is_dir():
            crops_dir = target.parent / "crops"
        crops = []
        for crop in meta.get("crops", []):
            crop_path = crops_dir / crop["file"]
            if not crop_path.is_file():
                raise SystemExit(f"crops.json lists a crop that does not exist: {crop_path}")
            crops.append({"n": crop.get("index"), "time_seconds": crop.get("time_seconds"),
                          "region": crop.get("region"), "pixel_box": crop.get("pixel_box"),
                          "source_size": crop.get("source_size"), "output_size": crop.get("output_size"),
                          "source_kind": crop.get("source_kind"), **file_record(crop_path, path)})
        artifact = add_artifact(manifest, path, "crops", target, args.command, args.note, {"crops": crops})
        for crop in crops:
            crop["id"] = f"{artifact['id']}.c{int(crop['n'] or 0):03d}"
        added.append(artifact["id"])
    else:
        details = {}
        if args.kind in ("transcript", "captions"):
            details = transcript_facts(target)
            details["transcript_source"] = args.transcript_source or ("captions" if args.kind == "captions" else None)
            if args.kind == "transcript" and not args.transcript_source:
                raise SystemExit("--transcript-source asr|cloud-asr|captions|manual is required for --kind transcript.")
            if args.transcript_source == "cloud-asr":
                # transcribe_cloud.py's JSON says which service did it and which ranges failed
                try:
                    cloud = json.loads(target.with_suffix(".json").read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    cloud = {}
                if isinstance(cloud, dict):
                    details["service"] = {"backend": cloud.get("backend"), "host": cloud.get("endpoint_host"),
                                          "model": cloud.get("model")}
                    details["failed_chunks"] = [{"start": c.get("start"), "end": c.get("end")}
                                                for c in cloud.get("failed_chunks", [])]
        if args.kind == "captions" and args.caption_origin:
            details["caption_origin"] = args.caption_origin
        if args.speech_confirmed:
            if args.kind != "transcript":
                raise SystemExit("--speech-confirmed belongs to a recognised transcript (--kind transcript).")
            details["speech_confirmed"] = True
        if args.language:
            if args.kind not in ("captions", "transcript"):
                raise SystemExit("--language describes a captions or transcript file.")
            language = args.language.strip()
            if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language):
                raise SystemExit("--language is a language code such as en, zh-Hans or pt-BR: the track that was "
                                 "really read, as the player or the file reports it.")
            details["language"] = language
        if args.kind == "screenshot":
            # Route B: a still of the page. Its time is the player's currentTime when it was taken.
            details["time_seconds"] = parse_seconds(args.time, "--time")
        if args.kind == "recording-check":
            # record_browser_playback.py's post-recording self-check (NAME.postcheck.json)
            try:
                check_report = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raise SystemExit(f"{target} is not a post-recording check report.")
            details = {"video": check_report.get("video"), "audio": check_report.get("audio"),
                       "ok": check_report.get("ok"), "frames_sampled": check_report.get("frames_sampled"),
                       "black_frames": check_report.get("black_frames"),
                       "confirmed_shows_video": bool(args.confirmed_shows_video)}
        if args.kind in ("timeline", "visual_outline", "metadata"):
            try:
                doc = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                doc = {}
            if isinstance(doc, dict) and args.kind != "metadata":
                if doc.get("frame_set_id"):
                    details["frame_set_id"] = doc["frame_set_id"]
                if doc.get("transcript_shift_seconds"):
                    details["transcript_shift_seconds"] = doc["transcript_shift_seconds"]
                if doc.get("recording_offset_seconds") is not None:
                    details["recording_offset_seconds"] = doc["recording_offset_seconds"]
            if isinstance(doc, dict) and args.kind == "metadata":
                # Route B has no media file: the page's own duration is the only runtime there is.
                length = doc.get("duration_seconds", doc.get("duration"))
                if isinstance(length, (int, float)) and length > 0 and not manifest["source"].get("video_duration_seconds"):
                    manifest["source"]["video_duration_seconds"] = float(length)
        if args.kind == "media":
            sha = sha256_file(target)
            manifest["source"].setdefault("media_sha256", sha)
        artifact = add_artifact(manifest, path, args.kind, target, args.command, args.note, details or None)
        added.append(artifact["id"])

    save(path, manifest)
    print(json.dumps({"added": added, "artifacts": len(manifest["artifacts"])}))
    return 0


def split_ids(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def of_kind(manifest: dict, *kinds: str) -> list[dict]:
    return [a for a in manifest["artifacts"] if a["kind"] in kinds]


def all_frames(manifest: dict) -> list[dict]:
    return [f for a in of_kind(manifest, "frames") for f in a.get("details", {}).get("frames", [])]


def all_crops(manifest: dict) -> list[dict]:
    return [c for a in of_kind(manifest, "crops") for c in a.get("details", {}).get("crops", [])]


def viewable_ids(manifest: dict) -> set[str]:
    """Everything that is a picture the answering model can open: frames, crops, screenshots."""
    return ({f["id"] for f in all_frames(manifest) if "id" in f}
            | {c["id"] for c in all_crops(manifest) if "id" in c}
            | {a["id"] for a in of_kind(manifest, "screenshot")})


def known_ids(manifest: dict) -> set[str]:
    return {a["id"] for a in manifest["artifacts"]} | viewable_ids(manifest)


def compute_verdict(visual: str, audio: str, on_screen: str) -> str:
    first_hand_audio = audio in ("captions-only", "transcribed", "heard")
    if visual == "second-hand" and audio == "second-hand":
        return "Second-hand report from an external model (nothing seen or heard first-hand)"
    if visual == "second-hand":
        base = compute_verdict("none", audio, "none")
        return (f"{base} + second-hand frame descriptions" if first_hand_audio
                else "Second-hand frame descriptions only (no frame seen first-hand)")
    if audio == "second-hand":
        base = compute_verdict(visual, "none", on_screen)
        return (f"{base} + second-hand audio report" if visual in ("sampled", "continuous")
                else "Second-hand audio report only (nothing heard or transcribed first-hand)")
    if visual == "continuous" and audio in ("transcribed", "heard"):
        return "Complete audiovisual analysis"
    if visual in ("sampled", "continuous") and audio in ("transcribed", "heard"):
        return "Complete audio + sampled visuals"
    if visual in ("sampled", "continuous") and audio == "captions-only":
        return "Captions + sampled visuals"
    if visual in ("sampled", "continuous"):
        return ("Frames + burned-in caption text (sampled)" if on_screen == "burned-in caption text"
                else "Frames only")
    if audio == "captions-only":
        return "Captions only"
    if audio in ("transcribed", "heard"):
        return "Audio transcript only"
    return "No reliable video analysis"


def partial_verdict(verdict: str, fraction: float | None = None) -> str:
    """The same verdict, said honestly when the media covers only part of the video."""
    if verdict.startswith("Complete "):
        text = "Partial " + verdict[len("Complete "):]
    else:
        text = verdict + " (partial)"
    return text + (f" - about {round(fraction * 100)}% of the video" if fraction is not None else "")


UNKNOWN_NOTE = "completeness unknown: the source video's length is not recorded"


def unknown_verdict(verdict: str) -> str:
    """A screen recording is as long as someone let it run. Without the video's real length nobody
    can say that it covers the whole video, so the word "Complete" is not available."""
    if verdict.startswith("Complete audiovisual analysis"):
        return "Audiovisual analysis of the recording - " + UNKNOWN_NOTE
    if verdict.startswith("Complete "):
        rest = verdict[len("Complete "):]
        return rest[0].upper() + rest[1:] + " - " + UNKNOWN_NOTE
    return verdict


def needs_source_length(manifest: dict) -> bool:
    route = manifest.get("route", {})
    return route.get("used") == "C" and not route.get("blocked")


def coverage_facts(manifest: dict, source_duration: float | None, covers: str | None) -> dict | None:
    """How much of the real video the media in hand covers. None when the video's length is unknown."""
    total = source_duration or manifest["source"].get("video_duration_seconds")
    if not total:
        return None
    offsets = [a["details"]["recording_offset_seconds"] for a in of_kind(manifest, "timeline", "visual_outline")
               if a.get("details", {}).get("recording_offset_seconds") is not None]
    media_length = manifest["source"].get("duration_seconds")
    if covers:
        left, _, right = covers.partition("-")
        begin, end = parse_seconds(left, "--media-covers"), parse_seconds(right, "--media-covers")
    elif offsets and media_length:
        begin = max(0.0, -float(offsets[0]))
        end = min(float(total), float(media_length) - float(offsets[0]))
    elif media_length and manifest["route"].get("used") in ("0", "A", "C"):
        begin, end = 0.0, min(float(total), float(media_length))
    else:
        return {"video_duration_seconds": float(total), "covers": None, "fraction": None, "partial": False}
    end = max(end, begin)
    fraction = min(1.0, (end - begin) / float(total))
    return {"video_duration_seconds": float(total), "covers": [round(begin, 3), round(end, 3)],
            "fraction": round(fraction, 3), "partial": fraction < PARTIAL_BELOW,
            "recording_offset_seconds": offsets[0] if offsets else None}


def cmd_rate(args) -> int:
    path = Path(args.manifest).expanduser().resolve()
    manifest = load(path)
    frames_read = split_ids(args.on_screen_frames)
    if args.frames_inspected == "all":
        inspected = sorted(viewable_ids(manifest))
    else:
        inspected = split_ids(args.frames_inspected)
    manifest["ratings"] = {
        "visual": {"level": args.visual, "inspected": inspected,
                   "evidence": split_ids(args.visual_evidence)
                   or [a["id"] for a in (of_kind(manifest, *SECOND_HAND_KINDS) if args.visual == "second-hand"
                                         else of_kind(manifest, "frames", "screenshot", "continuous-analysis"))]},
        "audio": {"level": args.audio, "evidence": split_ids(args.audio_evidence)
                  or [a["id"] for a in (of_kind(manifest, "native-model-report") if args.audio == "second-hand"
                                        else of_kind(manifest, "audio", "transcript", "audio-native-analysis")
                                        if args.audio == "transcribed"
                                        else of_kind(manifest, "audio", "transcript", "captions",
                                                     "audio-native-analysis"))]},
        "alignment": {"level": args.alignment, "evidence": split_ids(args.alignment_evidence)
                      or [a["id"] for a in of_kind(manifest, "timeline", "visual_outline")]},
        "on_screen_text": {"level": args.on_screen_text, "frames_read": frames_read,
                           "note": (args.on_screen_note or "").strip()},
        "transcript_read": {"level": args.transcript_read},
        "verdict": compute_verdict(args.visual, args.audio, args.on_screen_text),
        "rated_at": now(),
    }
    facts = coverage_facts(manifest, parse_seconds(args.source_duration, "--source-duration"), args.media_covers)
    if facts:
        manifest["ratings"]["coverage"] = facts
        if facts["partial"] or manifest["route"].get("partial"):
            manifest["ratings"]["verdict"] = partial_verdict(manifest["ratings"]["verdict"],
                                                             facts["fraction"] if facts["partial"] else None)
    elif manifest["route"].get("partial"):
        manifest["ratings"]["verdict"] = partial_verdict(manifest["ratings"]["verdict"])
    elif needs_source_length(manifest):
        manifest["ratings"]["verdict"] = unknown_verdict(manifest["ratings"]["verdict"])
        if manifest["ratings"]["verdict"] != compute_verdict(args.visual, args.audio, args.on_screen_text):
            print("NOTE: this is a screen recording and the video's real length is not on record, so the "
                  "verdict cannot say 'Complete'. Run `rate` again with --source-duration [hh:]mm:ss (or give "
                  "it to `init`).", file=sys.stderr)
    for gap in args.gap or []:
        if gap not in manifest["gaps"]:
            manifest["gaps"].append(gap)
    save(path, manifest)
    print(json.dumps({"verdict": manifest["ratings"]["verdict"]}))
    return 0


def pick_transcript(manifest: dict, wanted: str | None) -> dict:
    transcripts = of_kind(manifest, "transcript", "captions")
    if wanted:
        for artifact in transcripts:
            if artifact["id"] == wanted:
                return artifact
        raise SystemExit(f"--transcript {wanted} is not a recorded transcript or captions artifact.")
    if len(transcripts) == 1:
        return transcripts[0]
    if not transcripts:
        raise SystemExit("--segments needs a recorded transcript: run `add --kind transcript|captions` first.")
    raise SystemExit("Several transcripts are recorded; say which one with --transcript "
                     + "|".join(a["id"] for a in transcripts))


def cmd_claim(args) -> int:
    path = Path(args.manifest).expanduser().resolve()
    manifest = load(path)
    evidence = split_ids(args.evidence)
    frames = split_ids(args.frames)
    indices = parse_indices(args.segments)
    start = parse_seconds(args.start, "--start")
    end = parse_seconds(args.end, "--end")
    structured = bool(frames or indices or args.assessment or start is not None)

    unknown = [e for e in evidence + frames if e not in known_ids(manifest)]
    if unknown or not (evidence or frames or indices):
        raise SystemExit("A claim needs existing evidence: at least one real picture (--frames) or one "
                         f"transcript segment (--segments). Unknown or missing ids: {unknown or 'none given'}")
    not_pictures = [f for f in frames if f not in viewable_ids(manifest)]
    if not_pictures:
        raise SystemExit(f"--frames takes frame, crop or screenshot ids. Not pictures: {not_pictures}")

    claim = {"id": f"C{len(manifest['claims']) + 1}", "text": args.text, "evidence": list(evidence)}
    if structured:
        if start is None:
            raise SystemExit("A claim with --frames, --segments or --assessment needs --start (and usually --end).")
        if end is not None and end < start:
            raise SystemExit("--end is before --start.")
        assessment = args.assessment or "unverified"
        if assessment == "confirmed" and not (frames and indices):
            raise SystemExit("'confirmed' means the transcript says it and a picture shows it: give both "
                             "--frames and --segments, or use transcript-only / picture-only.")
        if assessment == "transcript-only" and (frames or not indices):
            raise SystemExit("'transcript-only' takes --segments and no --frames.")
        if assessment == "picture-only" and (indices or not frames):
            raise SystemExit("'picture-only' takes --frames and no --segments.")
        if assessment in ("unverified", "conflict", "not-understood") and not args.reasoning.strip():
            raise SystemExit(f"'{assessment}' needs --reasoning: what was checked and what is still open.")
        claim.update({"start": start, "end": end, "frames": frames, "assessment": assessment,
                      "tag": ASSESSMENTS[assessment], "reasoning": args.reasoning.strip(),
                      "time_precision": "segment"})
        if indices:
            artifact = pick_transcript(manifest, args.transcript)
            found = resolve(artifact, path)
            if found is None:
                raise SystemExit(f"{artifact['id']}: transcript file is missing: {artifact['path']}")
            by_index = {seg["index"]: seg for seg in transcript_segments(found)}
            missing = [i for i in indices if i not in by_index]
            if missing:
                raise SystemExit(f"--segments {missing} do not exist in {artifact['id']} "
                                 f"(it has segments 1-{len(by_index)}). Use the index printed by "
                                 "read_transcript.py, not the row number on a page.")
            excerpt = [by_index[i] for i in indices]
            claim["transcript"] = {"artifact": artifact["id"], "indices": indices,
                                   "excerpt": [{"index": e["index"], "start": e["start"], "end": e["end"],
                                                "text": e["text"]} for e in excerpt]}
            if any(e["end"] - e["start"] >= CHUNK_SEGMENT_SECONDS for e in excerpt):
                claim["time_precision"] = "chunk"  # a block's range, not the moment a sentence was said
            if artifact["id"] not in claim["evidence"]:
                claim["evidence"].append(artifact["id"])
        claim["evidence"] = list(dict.fromkeys(claim["evidence"] + frames))
    manifest["claims"].append(claim)
    save(path, manifest)
    print(json.dumps({"claim": claim["id"], "evidence": claim["evidence"],
                      "assessment": claim.get("assessment"), "tag": claim.get("tag"),
                      "time_precision": claim.get("time_precision"),
                      "note": "references checked; this does not certify the statement"}))
    return 0


def cmd_claim_update(args) -> int:
    """Withdraw (or restore) a claim. The record stays; a withdrawn claim is not checked or counted."""
    path = Path(args.manifest).expanduser().resolve()
    manifest = load(path)
    for claim in manifest.get("claims", []):
        if claim["id"] == args.id:
            if args.status == "withdrawn" and not (args.note or "").strip():
                raise SystemExit("--note is required: say why the claim is withdrawn.")
            claim["status"] = args.status
            claim.setdefault("status_history", []).append({"status": args.status, "note": args.note, "at": now()})
            save(path, manifest)
            print(json.dumps({"claim": claim["id"], "status": claim["status"],
                              "note": "kept on record with the reason; ids of other claims do not change"}))
            return 0
    raise SystemExit(f"No claim with id {args.id}. Known: {', '.join(c['id'] for c in manifest['claims']) or 'none'}")


def cmd_issue(args) -> int:
    path = Path(args.manifest).expanduser().resolve()
    manifest = load(path)
    start = parse_seconds(args.start, "--start")
    end = parse_seconds(args.end, "--end")
    if end is not None and end < start:
        raise SystemExit("--end is before --start.")
    if not args.summary.strip():
        raise SystemExit("--summary must say what could not be settled.")
    frames = split_ids(args.frames)
    claims = split_ids(args.claims)
    unknown = ([f for f in frames if f not in known_ids(manifest)]
               + [c for c in claims if c not in {x["id"] for x in manifest.get("claims", [])}])
    if unknown:
        raise SystemExit(f"Unknown ids: {unknown}")
    issues = manifest.setdefault("issues", [])
    duplicate = next((i for i in issues if i["summary"] == args.summary.strip() and i["start"] == start), None)
    if duplicate:
        print(json.dumps({"issue": duplicate["id"], "duplicate": True, "status": duplicate["status"]}))
        return 0
    issue = {"id": f"I{len(issues) + 1}", "status": "open", "start": start, "end": end,
             "summary": args.summary.strip(), "details": args.details.strip(),
             "attempted": [a.strip() for a in (args.attempted or []) if a.strip()],
             "unresolved_reason": args.unresolved_reason.strip(),
             "frames": frames, "segments": parse_indices(args.segments), "claims": claims,
             "history": [{"status": "open", "at": now(), "note": "recorded"}]}
    issues.append(issue)
    save(path, manifest)
    print(json.dumps({"issue": issue["id"], "status": "open",
                      "note": "recorded, not solved - list it under the open items of the answer"}))
    return 0


def cmd_issue_update(args) -> int:
    path = Path(args.manifest).expanduser().resolve()
    manifest = load(path)
    issue = next((i for i in manifest.get("issues", []) if i["id"] == args.id), None)
    if issue is None:
        raise SystemExit(f"No issue {args.id} in this manifest.")
    if not args.note.strip():
        raise SystemExit("--note is required: say what actually settled it, or why it is being closed. "
                         "A record existing, or a tool working again, does not resolve the question.")
    issue["status"] = args.status
    issue["history"].append({"status": args.status, "at": now(), "note": args.note.strip()})
    save(path, manifest)
    print(json.dumps({"issue": issue["id"], "status": issue["status"]}))
    return 0


def tables(manifest: dict) -> str:
    """Claims and issues as Markdown, for the draft or the notes' open-items section."""
    def span(item):
        if item.get("start") is None:
            return ""
        text = clock(item["start"]) + (f"-{clock(item['end'])}" if item.get("end") is not None else "")
        return text + (" (chunk-level)" if item.get("time_precision") == "chunk" else "")

    def cell(text):
        return str(text or "").replace("|", "/").replace("\n", " ")

    lines = ["### Claims", "", "| id | time | claim | tag | pictures | transcript segments | reasoning |",
             "|---|---|---|---|---|---|---|"]
    for claim in manifest.get("claims", []):
        indices = claim.get("transcript", {}).get("indices", [])
        tag = claim.get("tag", "")
        if claim.get("status") == "withdrawn":
            tag = "WITHDRAWN: " + cell((claim.get("status_history") or [{}])[-1].get("note"))
        lines.append(f"| {claim['id']} | {span(claim)} | {cell(claim['text'])} | {tag} | "
                     f"{', '.join(claim.get('frames', []))} | {', '.join(str(i) for i in indices)} | "
                     f"{cell(claim.get('reasoning'))} |")
    lines += ["", "### Issues", "", "| id | status | time | what could not be settled | tried | why it is still open |",
              "|---|---|---|---|---|---|"]
    for issue in manifest.get("issues", []):
        lines.append(f"| {issue['id']} | {issue['status']} | {span(issue)} | {cell(issue['summary'])} | "
                     f"{cell('; '.join(issue.get('attempted', [])))} | {cell(issue.get('unresolved_reason'))} |")
    return "\n".join(lines)


def cmd_list(args) -> int:
    path = Path(args.manifest).expanduser().resolve()
    block = tables(load(path))
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError, OSError):
        pass
    if args.output:
        Path(args.output).expanduser().resolve().write_text(block + "\n", encoding="utf-8")
    print(block)
    return 0


def check(manifest: dict, manifest_path: Path) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors mean the disclosure is not supported by the files."""
    errors: list[str] = []
    warnings: list[str] = []
    ids = known_ids(manifest)

    for artifact in manifest["artifacts"]:
        found = resolve(artifact, manifest_path)
        if found is None:
            errors.append(f"{artifact['id']} ({artifact['kind']}): file missing: {artifact['path']}")
        elif sha256_file(found) != artifact["sha256"]:
            errors.append(f"{artifact['id']} ({artifact['kind']}): file changed since it was recorded: {found}")
        if artifact.get("produced_by") in (None, "", "unrecorded"):
            warnings.append(f"{artifact['id']} ({artifact['kind']}): no source command recorded")
        for frame in artifact.get("details", {}).get("frames", []):
            frame_file = resolve(frame, manifest_path)
            if frame_file is None:
                errors.append(f"{frame.get('id')}: frame file missing: {frame['path']}")
            elif sha256_file(frame_file) != frame["sha256"]:
                errors.append(f"{frame.get('id')}: frame file changed since it was recorded")
        for crop in artifact.get("details", {}).get("crops", []):
            crop_file = resolve(crop, manifest_path)
            if crop_file is None:
                errors.append(f"{crop.get('id')}: crop file missing: {crop['path']}")
            elif sha256_file(crop_file) != crop["sha256"]:
                errors.append(f"{crop.get('id')}: crop file changed since it was recorded")

    route = manifest.get("route", {})
    history = route.get("history", [])
    if not route.get("used"):
        errors.append("no route is marked as the one used"
                      + (f" ({len(history)} attempt(s) are on record, none succeeded)" if history else "")
                      + ": `failed` and `skipped` only add history. Record the route that produced the "
                        "material with --status succeeded (or partial), or - when nothing worked - the last "
                        "route tried with --status blocked")
    elif not any(h["route"] == route["used"] and h["status"] in ("succeeded", "partial", "blocked") for h in history):
        errors.append("route.used does not match any succeeded/partial/blocked entry in route.history")

    ratings = manifest.get("ratings") or {}
    if not ratings:
        errors.append("no ratings recorded: run `rate`")
        return errors, warnings

    for channel in ("visual", "audio", "alignment"):
        for ref in ratings[channel]["evidence"]:
            if ref not in ids:
                errors.append(f"{channel} rating cites unknown evidence id {ref}")

    visual = ratings["visual"]["level"]
    frames = all_frames(manifest)
    if visual == "sampled" and not viewable_ids(manifest):
        errors.append("visual is 'sampled' but no frames or screenshots are recorded")
    if visual == "continuous" and not of_kind(manifest, "continuous-analysis"):
        errors.append("visual is 'continuous' but there is no 'continuous-analysis' artifact: holding a "
                      "complete file is not continuous inspection")
    if visual == "none" and frames:
        warnings.append("frames are recorded but visual is rated 'none'")
    second_hand = of_kind(manifest, *SECOND_HAND_KINDS)
    if visual == "second-hand" and not second_hand:
        errors.append("visual is 'second-hand' but no keyframe-analysis or native-model-report is recorded")
    if ratings["audio"]["level"] == "second-hand" and not of_kind(manifest, "native-model-report"):
        errors.append("audio is 'second-hand' but no native-model-report is recorded")
    if ratings["on_screen_text"]["level"] == EXTERNAL_OCR and not of_kind(manifest, "keyframe-analysis"):
        errors.append("on-screen text is external OCR but no keyframe-analysis artifact is recorded")
    cited_first_hand = (set(ratings["visual"].get("inspected", []))
                        | (set(ratings["on_screen_text"]["frames_read"])
                           if ratings["on_screen_text"]["level"] in READ_BY_MODEL else set()))
    for artifact in second_hand:
        if artifact["id"] in cited_first_hand:
            errors.append(f"{artifact['id']} is second-hand ({artifact['kind']}) and cannot be cited as a "
                          "frame the model inspected or read itself")
    inspected = ratings["visual"].get("inspected", [])
    viewable = viewable_ids(manifest)
    for ref in inspected:
        if ref not in viewable:
            errors.append(f"visual.inspected cites {ref}, which is not a recorded frame, crop or screenshot")
    if visual == "sampled" and not inspected:
        errors.append("visual is 'sampled' but --frames-inspected lists no frame: extracting frames is not "
                      "looking at them. Pass the ids actually opened, or 'all'")
    for ref in ratings["on_screen_text"]["frames_read"]:
        if inspected and ref not in inspected:
            errors.append(f"on-screen text was read from {ref}, which is not listed in --frames-inspected")

    audio = ratings["audio"]["level"]
    alignment_level = ratings["alignment"]["level"]
    transcripts = of_kind(manifest, "transcript", "captions")
    sources = {t.get("details", {}).get("transcript_source") for t in transcripts}
    if audio == "transcribed":
        if not ({"asr", "cloud-asr"} & sources):
            errors.append("audio is 'transcribed' but no transcript with --transcript-source asr is recorded")
        if not of_kind(manifest, "audio", "media"):
            errors.append("audio is 'transcribed' but no audio or media file is recorded")
        silent = [a["id"] for a in of_kind(manifest, "frames")
                  if a.get("details", {}).get("audio_in_file") == "none"]
        if silent and not of_kind(manifest, "audio"):
            errors.append(f"audio is 'transcribed' but {', '.join(silent)} says the file has no audio stream")
    if audio == "captions-only" and not ({"captions", "manual"} & sources):
        errors.append("audio is 'captions-only' but no captions artifact is recorded")
    if audio == "heard" and not of_kind(manifest, "audio-native-analysis"):
        errors.append("audio is 'heard' but there is no 'audio-native-analysis' artifact")
    doubtful = [t["id"] for t in transcripts if t.get("details", {}).get("transcript_source") in ("asr", "cloud-asr")
                and t.get("details", {}).get("speech_doubt") and not t.get("details", {}).get("speech_confirmed")]
    if audio == "transcribed" and doubtful:
        warnings.append(f"{', '.join(doubtful)}: the recognised text is mostly repetition or filler, which is what a "
                        "recogniser prints over music with little or no voice (three runs over one such track gave "
                        "three different texts). Listen to a stretch or look at the frames: "
                        "if nobody speaks, rate audio 'none' and say the track is music; if it is speech, re-add "
                        "the transcript with --speech-confirmed")
    blocks = [t["id"] for t in transcripts if (t.get("details", {}).get("median_segment_seconds") or 0) >= CHUNK_SEGMENT_SECONDS]
    if alignment_level == "timestamp-aligned" and blocks and len(blocks) == len([t for t in transcripts if t.get("details", {}).get("segments")]):
        warnings.append(f"{', '.join(blocks)}: the text is in blocks of {CHUNK_SEGMENT_SECONDS:g} s or more, so 'timestamp-aligned' "
                        "holds only to the block - cite ranges. If the source had a time for every line, "
                        "normalize it again without --merge")
    if audio == "none" and ({"asr", "cloud-asr"} & sources):
        warnings.append("an ASR transcript is recorded but audio is rated 'none'")

    alignment = ratings["alignment"]["level"]
    if alignment == "timestamp-aligned" and not of_kind(manifest, "timeline", "visual_outline"):
        # Route B has no frames.json to align against: timed captions plus screenshots that each
        # carry the player's time are timestamp-aligned on their own.
        timed_text = any((t.get("details", {}).get("segments") or 0) > 0 for t in transcripts)
        untimed = [a["id"] for a in of_kind(manifest, "screenshot")
                   if a.get("details", {}).get("time_seconds") is None]
        if not timed_text:
            errors.append("alignment is 'timestamp-aligned' but no timeline or visual_outline is recorded")
        for ref in untimed:
            errors.append(f"alignment is 'timestamp-aligned' but screenshot {ref} has no --time")
    if alignment == "chapter-level" and not of_kind(manifest, "metadata", "timeline", "visual_outline"):
        errors.append("alignment is 'chapter-level' but no metadata artifact with chapters is recorded")

    on_screen = ratings["on_screen_text"]
    frame_ids = viewable_ids(manifest)
    if on_screen["level"] in READ_BY_MODEL:
        if not on_screen["frames_read"]:
            errors.append(f"on-screen text is '{on_screen['level']}' but --on-screen-frames lists no frames")
        for ref in on_screen["frames_read"]:
            if ref not in frame_ids:
                errors.append(f"on-screen text cites {ref}, which is not a recorded frame")

    expected = compute_verdict(visual, audio, on_screen["level"])
    facts = ratings.get("coverage") or {}
    if facts.get("partial") or route.get("partial"):
        expected = partial_verdict(expected, facts.get("fraction") if facts.get("partial") else None)
    elif not facts and needs_source_length(manifest):
        expected = unknown_verdict(expected)
    if ratings.get("verdict") != expected:
        errors.append("stored verdict does not match the channel ratings")
    if route.get("used") == "C" and not route.get("blocked") and not facts:
        warnings.append("Route C: the video's real length is not recorded, so the runtime shown is the "
                        "recording's and the verdict cannot say 'Complete'. Re-run `rate` with --source-duration "
                        "(and check the offset)")

    # A timeline or outline built from an older frame set points at the wrong pictures.
    current = {a["details"].get("frame_set_id") for a in of_kind(manifest, "frames")
               if a.get("details", {}).get("frame_set_id")}
    for artifact in of_kind(manifest, "timeline", "visual_outline"):
        built_from = artifact.get("details", {}).get("frame_set_id")
        on_disk = resolve(artifact, manifest_path)
        if on_disk is not None:
            try:        # the file itself is the authority; details only remember what it said when added
                built_from = json.loads(on_disk.read_text(encoding="utf-8")).get("frame_set_id") or built_from
            except (ValueError, OSError, AttributeError):
                pass
        if built_from and current and built_from not in current:
            errors.append(f"{artifact['id']} ({artifact['kind']}) was built from a different set of frames "
                          "than the one recorded (frames were re-extracted or renumbered, for example by "
                          "adding --at). Re-run align_transcript_frames.py and add the new file")

    # Route C: a recording is only as good as what was really on the screen and in the loopback device.
    if route.get("used") == "C" and not route.get("blocked"):
        checks = of_kind(manifest, "recording-check")
        if not checks:
            errors.append("Route C was used but no post-recording check is recorded: add NAME.postcheck.json "
                          "with `add --kind recording-check`")
        for artifact in checks:
            detail = artifact.get("details", {})
            if visual in ("sampled", "continuous") and detail.get("video") in ("black", "no_frames"):
                errors.append(f"{artifact['id']}: the recording's picture is {detail.get('video')}, "
                              f"so visual cannot be '{visual}'")
            if visual in ("sampled", "continuous") and not detail.get("confirmed_shows_video"):
                errors.append(f"{artifact['id']}: nobody confirmed that the check frames show the video. A "
                              "recording of another window passes every automatic test; open the check "
                              "frames, then re-add with --confirmed-shows-video")
            if audio in ("transcribed", "heard") and detail.get("audio") in ("digital_silence", "no_audio_track", "none"):
                errors.append(f"{artifact['id']}: the recording's audio is {detail.get('audio')}, "
                              f"so audio cannot be '{audio}'")

    read_level = (ratings.get("transcript_read") or {}).get("level")
    if read_level == "full":
        states = []
        for artifact in transcripts:
            found = resolve(artifact, manifest_path)
            if found is not None:
                states.append((artifact["id"], read_log_state(found)))
        if not transcripts:
            errors.append("transcript-read is 'full' but no transcript or captions artifact is recorded")
        elif not any(state["complete"] for _, state in states):
            detail = "; ".join(f"{i}: " + (f"{st['served']}/{st['total']} segments served" if st["total"]
                                           else "no read log for this file") for i, st in states)
            errors.append("transcript-read is 'full' but read_transcript.py's read log does not show any "
                          f"transcript served to the end ({detail}). Page it until next_offset is null")

    duration = manifest["source"].get("duration_seconds")
    segment_cache: dict[str, dict] = {}
    for claim in manifest.get("claims", []):
        if claim.get("status") == "withdrawn":
            continue        # kept on record with its reason; no longer part of the answer
        for ref in claim["evidence"]:
            if ref not in ids:
                errors.append(f"claim {claim['id']} cites unknown evidence id {ref}")
        if "assessment" not in claim:
            continue
        cid = claim["id"]
        start, end = claim.get("start"), claim.get("end")
        if duration and start is not None and max(start, end or start) > float(duration) + 1:
            errors.append(f"claim {cid}: time range runs past the media duration ({clock(float(duration))})")
        for ref in claim.get("frames", []):
            if ref not in viewable:
                errors.append(f"claim {cid} cites {ref}, which is not a recorded frame, crop or screenshot")
            elif ref not in inspected:
                errors.append(f"claim {cid} rests on {ref}, which is not listed in --frames-inspected: "
                              "a picture nobody opened supports nothing")
        cited = claim.get("transcript")
        if cited:
            artifact = next((a for a in transcripts if a["id"] == cited["artifact"]), None)
            found = resolve(artifact, manifest_path) if artifact else None
            if found is None:
                errors.append(f"claim {cid}: its transcript {cited['artifact']} is not available")
                continue
            if cited["artifact"] not in segment_cache:
                try:
                    segment_cache[cited["artifact"]] = {s["index"]: s for s in transcript_segments(found)}
                except (ValueError, json.JSONDecodeError, TypeError):
                    segment_cache[cited["artifact"]] = {}
            by_index = segment_cache[cited["artifact"]]
            bad = [i for i in cited["indices"] if i not in by_index]
            if bad:
                errors.append(f"claim {cid} cites transcript segments {bad} that do not exist in {cited['artifact']}")
            elif start is not None and not any(
                    by_index[i]["start"] <= (end if end is not None else start) + 1
                    and by_index[i]["end"] >= start - 1 for i in cited["indices"]):
                errors.append(f"claim {cid}: none of its transcript segments overlaps its time range "
                              f"{clock(start)}-{clock(end if end is not None else start)}; a time anchor must "
                              "come from the cited segment or frame, not from memory")
        if claim["assessment"] == "confirmed" and not (claim.get("frames") and cited):
            errors.append(f"claim {cid} is 'confirmed' without both a picture and a transcript segment")

    claim_ids = {c["id"] for c in manifest.get("claims", [])}
    for issue in manifest.get("issues", []):
        for ref in issue.get("frames", []):
            if ref not in ids:
                errors.append(f"issue {issue['id']} cites unknown id {ref}")
        for ref in issue.get("claims", []):
            if ref not in claim_ids:
                errors.append(f"issue {issue['id']} cites unknown claim {ref}")
        if issue["status"] == "open" and not issue.get("attempted"):
            warnings.append(f"issue {issue['id']} records nothing under --attempted: say what was tried")
    return errors, warnings


def cmd_verify(args) -> int:
    path = Path(args.manifest).expanduser().resolve()
    manifest = load(path)
    errors, warnings = check(manifest, path)
    for line in errors:
        print(f"ERROR   {line}", file=sys.stderr)
    for line in warnings:
        print(f"WARNING {line}", file=sys.stderr)
    print(json.dumps({"ok": not errors, "errors": errors, "warnings": warnings,
                      "artifacts": len(manifest["artifacts"]), "frames": len(all_frames(manifest)),
                      "crops": len(all_crops(manifest)), "claims": len(manifest.get("claims", [])),
                      "open_issues": sum(1 for i in manifest.get("issues", []) if i["status"] == "open")},
                     indent=2))
    return 0 if not errors else 1


def refs(ids: list[str]) -> str:
    return f" [{', '.join(ids)}]" if ids else ""


def render_block(manifest: dict) -> str:
    route = manifest["route"]
    ratings = manifest["ratings"]
    frames = sorted(all_frames(manifest), key=lambda f: f["time_seconds"])
    shots = sorted(of_kind(manifest, "screenshot"),
                   key=lambda a: (a.get("details", {}).get("time_seconds") is None,
                                  a.get("details", {}).get("time_seconds") or 0))
    duration = manifest["source"].get("duration_seconds")
    history = " -> ".join(f"{h['route']} {h['status']}" + (f" ({h['reason']})" if h.get("reason") else "")
                          + (f" [with the user's browser login: {h['browser_login']}]" if h.get("browser_login") else "")
                          for h in route["history"]) or "none recorded"
    used_entries = [h for h in route["history"] if h["route"] == route["used"]]
    used_blocked = (used_entries[-1]["status"] == "blocked") if used_entries else bool(route.get("blocked"))
    used = ROUTES.get(route["used"], str(route["used"])) + (
        " (blocked)" if used_blocked else
        " (partial - see the route history)" if route.get("partial") else "")
    crop_ids = {c["id"] for c in all_crops(manifest) if "id" in c}
    facts = ratings.get("coverage") or {}

    visual = ratings["visual"]
    if visual["level"] == "sampled" and frames:
        shown = ", ".join(clock(f["time_seconds"]) for f in frames[:12])
        more = f", ... (+{len(frames) - 12} more, all in the manifest)" if len(frames) > 12 else ""
        reasons: dict[str, int] = {}
        for f in frames:
            reasons[f.get("reason") or "unknown"] = reasons.get(f.get("reason") or "unknown", 0) + 1
        mix = ", ".join(f"{count} {name}" for name, count in sorted(reasons.items()))
        by_id = {f["id"]: f for f in frames}
        seen = [i for i in dict.fromkeys(visual.get("inspected", [])) if i in by_id]   # frames only
        seen_crops = [i for i in dict.fromkeys(visual.get("inspected", [])) if i in crop_ids]
        seen_clock: dict[str, int] = {}
        for stamp in sorted(by_id[i]["time_seconds"] for i in seen):
            seen_clock[clock(stamp)] = seen_clock.get(clock(stamp), 0) + 1
        seen_times = ", ".join(label if n == 1 else f"{label} x{n}" for label, n in seen_clock.items())
        if len(seen) >= len(frames):
            looked = f"all {len(frames)} looked at"
        else:
            looked = f"{len(seen)} of {len(frames)} actually looked at ({seen_times})"
        if seen_crops:
            looked += f", plus {len(seen_crops)} region crop{'s' if len(seen_crops) != 1 else ''}"
        visual_line = f"sampled - {looked}; {len(frames)} frames extracted ({mix}) at {shown}{more}"
    elif visual["level"] == "sampled" and shots:
        seen = [i for i in visual.get("inspected", []) if i in {s["id"] for s in shots}]
        times = ", ".join(clock(s["details"]["time_seconds"]) for s in shots[:12]
                          if s.get("details", {}).get("time_seconds") is not None)
        visual_line = (f"sampled - {len(seen)} of {len(shots)} page screenshots actually looked at"
                       + (f"; taken at {times}" if times else "; times not recorded")
                       + " (stills of the player in the page, not frames of a media file)")
    elif visual["level"] == "second-hand":
        visual_line = "second-hand - no frame was looked at by me; descriptions come from an external model"
    else:
        visual_line = visual["level"]

    audio = ratings["audio"]
    transcripts = [a for a in manifest["artifacts"] if a["kind"] in ("transcript", "captions")]
    audio_line = audio["level"]
    languages = sorted({t["details"]["language"] for t in transcripts if t.get("details", {}).get("language")})
    spans = [t["details"] for t in transcripts if t.get("details", {}).get("segments")]
    cloud = [t for t in transcripts if t.get("details", {}).get("transcript_source") == "cloud-asr"]
    if audio["level"] == "transcribed":
        audio_line += " - speech recognised from the real audio track; not listened to as audio"
        if cloud:
            service = cloud[0]["details"].get("service") or {}
            audio_line += (f"; recognition was done by a third-party cloud service "
                           f"({service.get('host') or service.get('backend') or 'unnamed'}), the audio was uploaded to it")
    elif audio["level"] == "captions-only":
        audio_line += " - no audio was heard or transcribed"
        origins = sorted({t["details"]["caption_origin"] for t in transcripts
                          if t.get("details", {}).get("caption_origin")})
        if origins:
            audio_line += "; text is " + " and ".join(CAPTION_ORIGINS[o] for o in origins)
        if not languages and of_kind(manifest, "screenshot") and manifest["route"].get("used") == "B":
            audio_line += "; caption language not recorded"
    elif audio["level"] == "none":
        audio_line += " - no audio evidence of any kind"
    noisy = [t["id"] for t in transcripts if t.get("details", {}).get("transcript_source") in ("asr", "cloud-asr")
             and t.get("details", {}).get("speech_doubt") and not t.get("details", {}).get("speech_confirmed")]
    if noisy and audio["level"] == "transcribed":
        audio_line += ("; WARNING: the recognised text is mostly repetition or filler (" + ", ".join(noisy)
                       + ") - typical of a recogniser run over music with no voice; not confirmed as speech")
    if languages and audio["level"] in ("captions-only", "transcribed"):
        audio_line += "; language of the text: " + ", ".join(languages)
    elif audio["level"] == "second-hand":
        audio_line += " - an external video model reported on the audio; I did not hear or transcribe it"

    coverage = []
    recorded = route.get("used") == "C"
    video_length = facts.get("video_duration_seconds") or manifest["source"].get("video_duration_seconds")
    if video_length and (recorded or not duration):
        coverage.append(f"video runtime {clock(video_length)}")
    if duration:
        coverage.append(f"{'recording length' if recorded else 'runtime'} {clock(duration)}")
    if facts.get("recording_offset_seconds") is not None:
        coverage.append(f"recording offset {facts['recording_offset_seconds']:g}s "
                        "(video time = recording time - offset)")
    if facts.get("covers") and facts.get("partial"):
        coverage.append(f"the media covers only {clock(facts['covers'][0])}-{clock(facts['covers'][1])} of the "
                        f"video (about {round(facts['fraction'] * 100)}%)")
    timed = [t for t in transcripts if t.get("details", {}).get("segments")]
    if len(timed) == 1:
        d = timed[0]["details"]
        coverage.append(f"transcript {clock(d['first_start'])}-{clock(d['last_end'])} in {d['segments']} segments")
    for t in timed if len(timed) > 1 else []:
        d = t["details"]
        label = "captions" if t["kind"] == "captions" else "transcript"
        coverage.append(f"{label} {t['id']} {clock(d['first_start'])}-{clock(d['last_end'])} "
                        f"in {d['segments']} segments")
    if len(timed) > 1:
        coverage.append("(the same speech in each; segment counts are not added up)")
    if recorded and not video_length:
        coverage.append("source video length NOT recorded, so completeness is unknown - give it with "
                        "`rate --source-duration` or `init --source-duration`")
    shifts = sorted({a["details"]["transcript_shift_seconds"] for a in of_kind(manifest, "timeline", "visual_outline")
                     if a.get("details", {}).get("transcript_shift_seconds")})
    if shifts:
        coverage.append(f"transcript times shifted by {shifts[0]:g}s to match the file")
    if frames:
        frame_ids = {f["id"] for f in frames}
        opened = len({i for i in ratings["visual"].get("inspected", []) if i in frame_ids})
        coverage.append(f"{len(frames)} frames extracted over {clock(frames[0]['time_seconds'])}"
                        f"-{clock(frames[-1]['time_seconds'])}, {opened} of them inspected")
        bursts = sum((a.get("details", {}).get("dropped_by_reason") or {}).get("scene-burst", 0)
                     for a in of_kind(manifest, "frames"))
        if bursts:
            coverage.append(f"{bursts} look-alike frame(s) of scene-change bursts thinned out before numbering")
    if shots:
        timed = [s["details"]["time_seconds"] for s in shots if s.get("details", {}).get("time_seconds") is not None]
        coverage.append(f"{len(shots)} page screenshot(s)"
                        + (f" over {clock(min(timed))}-{clock(max(timed))}" if timed else ""))
    for check_artifact in of_kind(manifest, "recording-check"):
        detail = check_artifact.get("details", {})
        coverage.append(f"recording self-check: picture {detail.get('video')}, audio {detail.get('audio')}, "
                        + ("check frames confirmed to show the video" if detail.get("confirmed_shows_video")
                           else "check frames NOT confirmed") + f" [{check_artifact['id']}]")
    crops = all_crops(manifest)
    if crops:
        coverage.append(f"{len(crops)} region crop(s) at source resolution")
    read_level = (ratings.get("transcript_read") or {}).get("level")
    if read_level == "full":
        coverage.append("transcript read in full (paged to the end, per the read log)")
    elif read_level == "partial":
        coverage.append("transcript read only in part - not a basis for complete notes")
    elif read_level == "none":
        coverage.append("transcript not read")
    on_screen = ratings["on_screen_text"]
    on_screen_line = on_screen["level"]
    count = len(on_screen["frames_read"])
    plural = "frame" if count == 1 else "frames"
    if on_screen["level"] == "burned-in caption text":
        on_screen_line += f" - read by the model from {count} {plural}; no OCR engine; not audio evidence"
    elif on_screen["level"] == PICTURE_TEXT:
        on_screen_line += (f" - text that is part of the picture (titles, slides, credits, a player's overlaid "
                           f"captions), read by the model from {count} {plural}; no OCR engine; not audio evidence")
    elif on_screen["level"] == EXTERNAL_OCR:
        on_screen_line += " - produced by an external OCR engine, not read by the model; not audio evidence"
    if on_screen.get("note"):
        on_screen_line += f" ({on_screen['note']})"
    external = [a for a in manifest["artifacts"] if a["kind"] in SECOND_HAND_KINDS]

    lines = [
        "## What I Actually Did",
        f"- **路由 Route:** {used}",
        f"- **路由过程 Route history:** {history}",
        f"- **Verdict:** {ratings['verdict']}",
        f"- **Visual:** {visual_line}{refs(visual['evidence'])}",
        f"- **Audio:** {audio_line}{refs(audio['evidence'])}",
        f"- **Alignment:** {ratings['alignment']['level']}{refs(ratings['alignment']['evidence'])}",
        f"- **On-screen text:** {on_screen_line}{refs(on_screen['frames_read'])}",
        f"- **Coverage:** {'; '.join(coverage) or 'not measured'}",
    ]
    if external:
        lines.append("- **Second-hand evidence:** "
                     + "; ".join(f"{a['kind']} [{a['id']}]" + (f" - {a['note']}" if a.get("note") else "")
                                 for a in external)
                     + " - reported by an external engine or model, not seen or heard by me; "
                       "it does not raise any rating above")
    structured = [c for c in manifest.get("claims", []) if "assessment" in c and c.get("status") != "withdrawn"]
    withdrawn = sum(1 for c in manifest.get("claims", []) if c.get("status") == "withdrawn")
    if structured:
        counts: dict[str, int] = {}
        for claim in structured:
            label = claim["tag"] or "confirmed by transcript and picture"
            counts[label] = counts.get(label, 0) + 1
        chunk = sum(1 for c in structured if c.get("time_precision") == "chunk")
        lines.append(f"- **Claims on record:** {len(structured)} - "
                     + ", ".join(f"{n} {label}" for label, n in counts.items())
                     + (f"; {chunk} with chunk-level time (a range, not an exact anchor)" if chunk else "")
                     + (f"; {withdrawn} withdrawn and not counted" if withdrawn else "")
                     + " - references were checked, the statements were not certified")
    open_issues = [i for i in manifest.get("issues", []) if i["status"] == "open"]
    if open_issues:
        lines.append("- **Unresolved issues:** " + "; ".join(
            f"{i['id']} {clock(i['start'])}" + (f"-{clock(i['end'])}" if i.get("end") is not None else "")
            + f" {i['summary']}" for i in open_issues) + " - recorded, not solved, no answer guessed")
    missing = [f"{clock(c['start'])}-{clock(c['end'])}" for t in cloud
               for c in t["details"].get("failed_chunks", [])]
    all_gaps = list(manifest.get("gaps", []))
    if missing:
        all_gaps.append("no transcript for " + ", ".join(missing) + " (cloud transcription failed there)")
    if any(h.get("browser_login") for h in route["history"]):
        all_gaps.append("the download used the user's own browser login, with their consent; nothing about "
                        "the account is recorded")
    if all_gaps:
        lines.append(f"- **Known gaps:** {'; '.join(all_gaps)}")
    lines.append("- **Evidence manifest:** evidence_manifest.json - ids in [brackets] resolve to files "
                 "with SHA-256 and source command")
    return "\n".join(lines)


def cmd_render(args) -> int:
    path = Path(args.manifest).expanduser().resolve()
    manifest = load(path)
    errors, _ = check(manifest, path)
    if errors and not args.allow_unverified:
        for line in errors:
            print(f"ERROR   {line}", file=sys.stderr)
        raise SystemExit("Manifest does not verify; refusing to render a disclosure it cannot support. "
                         "Fix the errors, or pass --allow-unverified to see the block anyway.")
    block = render_block(manifest)
    try:  # the block contains non-ASCII labels; emit UTF-8 whatever the console code page is
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError, OSError):
        pass
    if args.format == "json":
        # The same disclosure as data, for hosts and tools that want fields instead of Markdown.
        ratings = manifest["ratings"]
        lines = []
        for line in block.splitlines()[1:]:
            label, _, text = line[2:].partition(":** ")
            ids = re.findall(r"\[([A-Z]\d+(?:\.[a-z]\d+)?(?:, [A-Z]\d+(?:\.[a-z]\d+)?)*)\]\s*$", text)
            lines.append({"label": label.strip("*"), "text": text,
                          "evidence": ids[0].split(", ") if ids else []})
        block = json.dumps({"schema": "disclosure/1", "route": manifest["route"]["used"],
                            "blocked": bool(manifest["route"].get("blocked")),
                            "route_history": manifest["route"]["history"], "verdict": ratings["verdict"],
                            "levels": {"visual": ratings["visual"]["level"], "audio": ratings["audio"]["level"],
                                       "alignment": ratings["alignment"]["level"],
                                       "on_screen_text": ratings["on_screen_text"]["level"]},
                            "lines": lines, "markdown": render_block(manifest)}, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).expanduser().resolve().write_text(block + "\n", encoding="utf-8")
    print(block)
    return 0


LINE_RE = re.compile(r"^- \*\*(?P<label>[^*]+?):\*\*\s*(?P<text>.*)$")


def lint_disclosure(text: str, must_be_first: bool = True) -> tuple[list[str], dict]:
    """Check a disclosure block that was written by hand against the format. Returns (errors, fields)."""
    errors: list[str] = []
    rows = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    content = [line for line in rows if line.strip()]
    heading = "## What I Actually Did"
    if heading not in [line.strip() for line in rows]:
        return [f"no '{heading}' heading"], {}
    if must_be_first and content and content[0].strip() != heading:
        errors.append(f"the disclosure must come first; the answer starts with: {content[0][:60]!r}")
    start = [line.strip() for line in rows].index(heading) + 1
    fields: dict[str, str] = {}
    for line in rows[start:]:
        if line.startswith("## "):
            break
        match = LINE_RE.match(line.strip())
        if match:
            label = match.group("label").strip()
            key = {"路由 Route": "Route", "路由过程 Route history": "Route history"}.get(label, label)
            fields[key] = match.group("text").strip()

    def level(key: str, allowed: list[str]) -> str | None:
        value = fields.get(key)
        if value is None:
            return None
        clean = value.replace("**", "").strip()
        for candidate in sorted(allowed, key=len, reverse=True):
            if clean == candidate or clean.startswith(candidate + " ") or clean.startswith(candidate + ";"):
                return candidate
        errors.append(f"{key}: {value[:50]!r} does not start with one of {allowed}")
        return None

    if "Route" not in fields:
        errors.append("no Route line: every answer names the route used")
    elif not re.match(r"^(0|A|B|C)\b", fields["Route"].replace("**", "")):
        errors.append(f"Route must start with 0, A, B or C: {fields['Route'][:40]!r}")
    verdict = fields.get("Verdict", "").replace("**", "").strip()
    if not verdict:
        errors.append("no Verdict line")
    if verdict.startswith(BLOCKED_VERDICT):
        return errors, fields   # a blocked attempt states the route and the verdict; nothing else is owed
    for key in ("Visual", "Audio", "Alignment", "Coverage"):
        if key not in fields:
            errors.append(f"no {key} line: each channel is rated separately, even when it is 'none'")
    visual = level("Visual", VISUAL)
    audio = level("Audio", AUDIO)
    level("Alignment", ALIGNMENT)
    on_screen = level("On-screen text", ON_SCREEN) or "none"
    if visual and audio and verdict:
        expected = compute_verdict(visual, audio, on_screen)
        if not (verdict.startswith(expected) or verdict.startswith(partial_verdict(expected))
                or verdict.startswith(unknown_verdict(expected))):
            errors.append(f"Verdict {verdict[:60]!r} does not match the ratings; visual={visual}, "
                          f"audio={audio} gives {expected!r}")
    if visual == "sampled" and not re.search(r"\d", fields.get("Visual", "")):
        errors.append("Visual is 'sampled' but gives no frame count or timestamps")
    return errors, fields


def cmd_lint(args) -> int:
    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"File not found: {path}")
    errors, fields = lint_disclosure(path.read_text(encoding="utf-8-sig", errors="replace"),
                                     must_be_first=not args.anywhere)
    for line in errors:
        print(f"ERROR   {line}", file=sys.stderr)
    print(json.dumps({"ok": not errors, "errors": errors, "fields": sorted(fields)}, indent=2))
    return 0 if not errors else 1


def main() -> int:
    safe_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("-m", "--manifest", default="evidence_manifest.json")

    p = sub.add_parser("init", help="Start a manifest.")
    common(p)
    p.add_argument("--source", required=True, help="The URL or local file being analysed.")
    p.add_argument("--title")
    p.add_argument("--source-duration",
                   help="Length of the ORIGINAL video, seconds or [hh:]mm:ss. Give it for Route C and for "
                        "focused extracts: when the material covers clearly less, the Verdict says 'Partial'.")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("route", help="Append a route attempt.")
    common(p)
    p.add_argument("--route", required=True, choices=sorted(ROUTES))
    p.add_argument("--status", required=True, choices=["succeeded", "partial", "failed", "blocked", "skipped"],
                   help="partial = the route produced evidence for one channel but not the other, or for "
                        "only part of the video; say which in --reason.")
    p.add_argument("--reason", default="")
    p.add_argument("--browser-login", metavar="BROWSER",
                   help="Route A only: the download used the user's own browser login (fetch_media.py "
                        "--cookies-from-browser), with their consent. Give the browser's name. Nothing about "
                        "the account is recorded.")
    p.set_defaults(fn=cmd_route)

    p = sub.add_parser("add", help="Record a product file with its hash and source command.")
    common(p)
    p.add_argument("--kind", required=True, choices=KINDS)
    p.add_argument("--path", required=True)
    p.add_argument("--command", default="", help="The exact command that produced the file.")
    p.add_argument("--caption-origin", choices=sorted(CAPTION_ORIGINS),
                   help="For --kind captions: who wrote them. Shown on the Audio line.")
    p.add_argument("--language", help="For --kind captions / transcript: the language code of the text that was "
                                      "REALLY read (e.g. en, zh-Hans). Shown in the disclosure; a caption track in "
                                      "another language than the one asked for must not pass as the transcript.")
    p.add_argument("--speech-confirmed", action="store_true",
                   help="For --kind transcript: the text looked like recogniser noise (repetition, filler) and "
                        "you checked that somebody really speaks. Without it the disclosure carries a warning.")
    p.add_argument("--time", help="For --kind screenshot: the player's time when it was taken (seconds or mm:ss).")
    p.add_argument("--confirmed-shows-video", action="store_true",
                   help="For --kind recording-check: you opened the check frames and they show the video.")
    p.add_argument("--transcript-source", choices=["asr", "cloud-asr", "captions", "manual"],
                   help="asr = recognised locally; cloud-asr = by a third-party service (transcribe_cloud.py).")
    p.add_argument("--note", default="")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("rate", help="Record the rating of every evidence channel.")
    common(p)
    p.add_argument("--visual", required=True, choices=VISUAL)
    p.add_argument("--audio", required=True, choices=AUDIO)
    p.add_argument("--alignment", required=True, choices=ALIGNMENT)
    p.add_argument("--on-screen-text", default="none", choices=ON_SCREEN,
                   help="One of these exact values (it is a level, not a description).")
    p.add_argument("--on-screen-note", default="",
                   help="Free text: what on-screen text was read, e.g. \"labels 'Horizon', '~5 km'\". "
                        "Shown on the On-screen text line; it does not change the level.")
    p.add_argument("--on-screen-frames", help="Frame ids actually read for burned-in text, e.g. E2.f001,E2.f004")
    p.add_argument("--frames-inspected", default="",
                   help="Ids of the frames/screenshots actually opened and looked at, or 'all'. "
                        "Required when --visual is sampled: extracted is not inspected.")
    p.add_argument("--visual-evidence")
    p.add_argument("--audio-evidence")
    p.add_argument("--alignment-evidence")
    p.add_argument("--gap", action="append", help="A known gap or limitation. Repeatable.")
    p.add_argument("--source-duration", help="Length of the real video (seconds or [hh:]mm:ss) when the media "
                                             "in hand is not the whole of it - always for a screen recording.")
    p.add_argument("--media-covers", metavar="START-END",
                   help="Which stretch of the video the media covers, in video time, e.g. 0:00-2:20. Derived "
                        "from the recording offset when omitted.")
    p.add_argument("--transcript-read", choices=READ_LEVELS,
                   help="How much of the transcript was read. 'full' is checked against the read log "
                        "written by read_transcript.py and is required before writing complete notes.")
    p.set_defaults(fn=cmd_rate)

    p = sub.add_parser("claim", help="Link one statement of the answer to evidence ids.")
    common(p)
    p.add_argument("--text", required=True)
    p.add_argument("--evidence", help="Comma-separated ids, e.g. E2.f004,E3 (simple form).")
    p.add_argument("--start", help="Start of the time range, seconds or [hh:]mm:ss.")
    p.add_argument("--end", help="End of the time range.")
    p.add_argument("--frames", help="Frame / crop / screenshot ids actually looked at, e.g. E1.f004,E5.c001")
    p.add_argument("--segments", help="1-based transcript segment indices from read_transcript.py, e.g. 41-44,50")
    p.add_argument("--transcript", help="Transcript artifact id, when more than one is recorded.")
    p.add_argument("--assessment", choices=sorted(ASSESSMENTS),
                   help="confirmed = said and shown; transcript-only -> [仅转录]; picture-only -> "
                        "[仅画面、未讲解]; unverified / conflict -> [待证]; not-understood -> [未理解].")
    p.add_argument("--reasoning", default="", help="What was checked and why the judgement holds.")
    p.set_defaults(fn=cmd_claim)

    p = sub.add_parser("claim-update", help="Withdraw a claim that was recorded by mistake (kept, not checked).")
    common(p)
    p.add_argument("--id", required=True, help="Claim id, e.g. C4.")
    p.add_argument("--status", required=True, choices=["withdrawn", "active"])
    p.add_argument("--note", default="", help="Why. Required when withdrawing.")
    p.set_defaults(fn=cmd_claim_update)

    p = sub.add_parser("issue", help="Record a problem that could not be settled. Never a guessed answer.")
    common(p)
    p.add_argument("--start", required=True, help="Where in the video, seconds or [hh:]mm:ss.")
    p.add_argument("--end")
    p.add_argument("--summary", required=True, help="What could not be settled, in one sentence.")
    p.add_argument("--details", default="")
    p.add_argument("--attempted", action="append", help="One thing that was tried. Repeatable.")
    p.add_argument("--unresolved-reason", default="", help="Why it is still open.")
    p.add_argument("--frames", help="Related frame / crop ids.")
    p.add_argument("--segments", help="Related transcript segment indices.")
    p.add_argument("--claims", help="Related claim ids, e.g. C3")
    p.set_defaults(fn=cmd_issue)

    p = sub.add_parser("issue-update", help="Change an issue's status, with the reason.")
    common(p)
    p.add_argument("--id", required=True)
    p.add_argument("--status", required=True, choices=ISSUE_STATUS)
    p.add_argument("--note", required=True)
    p.set_defaults(fn=cmd_issue_update)

    p = sub.add_parser("list", help="Print claims and issues as Markdown tables.")
    common(p)
    p.add_argument("--output")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("verify", help="Re-hash every file and check the ratings against them.")
    common(p)
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("render", help="Print the disclosure block generated from the manifest.")
    common(p)
    p.add_argument("--output")
    p.add_argument("--allow-unverified", action="store_true")
    p.add_argument("--format", choices=["markdown", "json"], default="markdown",
                   help="json = the same disclosure as fields (schema disclosure/1).")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("lint", help="Check a hand-written disclosure block against the format.")
    p.add_argument("--file", required=True, help="A Markdown file containing the answer.")
    p.add_argument("--anywhere", action="store_true", help="Do not require the block to be the first thing.")
    p.set_defaults(fn=cmd_lint)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
