#!/usr/bin/env python3
"""Align timestamped transcript segments with extracted video frames.

Two views are written:
- timeline.json: for each transcript segment, the frames near it (speech -> pictures).
- visual_outline.json (v5.2): for each kept frame, the span it stands for (from its PTS to the
  next kept frame's PTS) and every transcript segment spoken during that span
  (picture -> speech). Works without a transcript too, e.g. for a silent recording.
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
import json
import re
import sys
from pathlib import Path


TIME_RE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})(?:[,.](\d{1,3}))?")


def parse_time(value: str) -> float:
    match = TIME_RE.search(value.strip())
    if not match:
        raise ValueError(f"Cannot parse timestamp: {value}")
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    millis = int((match.group(4) or "0").ljust(3, "0")[:3])
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def timecode(seconds: float) -> str:
    total = int(max(0, seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    sec = total % 60
    return f"{hours:02d}:{minutes:02d}:{sec:02d}"


def parse_srt_or_vtt(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"^WEBVTT.*?\n\n", "", text, flags=re.S)
    blocks = re.split(r"\n\s*\n", text.strip())
    segments = []
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        start_raw, end_raw = [part.strip().split(" ")[0] for part in lines[timing_index].split("-->", 1)]
        content = " ".join(lines[timing_index + 1 :]).strip()
        if content:
            segments.append({"start": parse_time(start_raw), "end": parse_time(end_raw), "text": content})
    return segments


def parse_json(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("segments", data.get("transcript", []))
    segments = []
    for item in data:
        start = float(item.get("start", item.get("start_seconds", 0)))
        end = float(item.get("end", item.get("end_seconds", start)))
        text = str(item.get("text", item.get("speech", ""))).strip()
        if text:
            segments.append({"start": start, "end": end, "text": text})
    return segments


def load_transcript(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix in {".srt", ".vtt"}:
        return parse_srt_or_vtt(path)
    if suffix == ".json":
        return parse_json(path)
    raise SystemExit("Transcript must be .srt, .vtt, or .json.")


def _words(text: str) -> set:
    return {w for w in re.findall(r"[^\W_]+", text.lower()) if len(w) > 1}


def estimate_shift(transcript: list[dict], reference: list[dict], window: float = 30.0) -> dict:
    """How far a transcript's clock is from a reference recognised from the file's own audio.

    Each line is paired with the reference line that shares most of its words within ``window``
    seconds; the median start-time difference of the confident pairs is the estimate. It is a
    suggestion to check by hand, never applied automatically.
    """
    diffs = []
    for seg in transcript:
        words = _words(seg["text"])
        if len(words) < 3:
            continue
        best, best_score = None, 0.0
        for ref in reference:
            if abs(ref["start"] - seg["start"]) > window:
                continue
            other = _words(ref["text"])
            if not other:
                continue
            score = len(words & other) / len(words | other)
            if score > best_score:
                best, best_score = ref, score
        if best is not None and best_score >= 0.5:
            diffs.append(best["start"] - seg["start"])
    if len(diffs) < 3:
        return {"matched_lines": len(diffs), "suggested_transcript_shift": None,
                "note": "too few lines matched to estimate a shift; compare two lines by hand"}
    diffs.sort()
    median = diffs[len(diffs) // 2]
    spread = diffs[(len(diffs) * 3) // 4] - diffs[len(diffs) // 4]
    steady = spread <= 1.0
    suggestion = round(median, 1) if steady and abs(median) >= 0.7 else None
    return {"matched_lines": len(diffs), "median_difference_seconds": round(median, 2),
            "spread_seconds": round(spread, 2), "suggested_transcript_shift": suggestion,
            "note": ("steady offset: pass it as --transcript-shift after checking two lines" if suggestion else
                     "no steady offset of 0.7 s or more" if steady else
                     "the difference is not steady (drift or different edits); a single shift will not fix it")}


def load_frames_meta(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_frames(path: Path) -> tuple[Path, list[dict]]:
    data = load_frames_meta(path)
    frames_dir = Path(data.get("frames_dir", path.parent / "frames"))
    frames = data.get("frames", [])
    return frames_dir, frames


def build_visual_outline(frames: list[dict], frames_dir: Path, transcript: list[dict] | None,
                         duration: float | None, speech_source: str = "unspecified") -> dict:
    """Reverse map: each frame covers [its time, next frame's time); attach the speech in that span.

    A segment is attached to the span containing its midpoint, so each line appears exactly once;
    ``crosses_boundary`` flags lines that started or ended in a neighbouring span.
    """
    ordered = sorted(frames, key=lambda f: float(f["time_seconds"]))
    segments = sorted(transcript or [], key=lambda s: s["start"])
    last_speech = max((s["end"] for s in segments), default=0.0)
    end_of_media = duration if duration else max([last_speech] + [float(f["time_seconds"]) for f in ordered] + [0.0])
    spans = []
    for i, frame in enumerate(ordered):
        start = float(frame["time_seconds"])
        end = float(ordered[i + 1]["time_seconds"]) if i + 1 < len(ordered) else max(end_of_media, start)
        spans.append({
            "index": frame.get("index", i + 1),
            "start": round(start, 3),
            "end": round(end, 3),
            "range": f"{timecode(start)}-{timecode(end)}",
            "frame": str(frames_dir / frame["file"]),
            "frame_reason": frame.get("reason", "unknown"),
            "speech": [],
            "transcript": "",
            # Filled in by the model after it actually looks at the frame; never by an OCR engine.
            "on_screen_text": None,
            "on_screen_text_label": "burned-in caption text",
        })
    unframed = []
    for seg in segments:
        mid = (seg["start"] + seg["end"]) / 2
        host = None
        for span in spans:
            if span["start"] <= mid < span["end"] or (span is spans[-1] and mid >= span["start"]):
                host = span
                break
        item = {"start": seg["start"], "end": seg["end"], "text": seg["text"]}
        if host is None:
            unframed.append(item)
            continue
        item["crosses_boundary"] = seg["start"] < host["start"] or seg["end"] > host["end"]
        host["speech"].append(item)
    for span in spans:
        span["transcript"] = " ".join(x["text"] for x in span["speech"]).strip()
    first = spans[0]["start"] if spans else None
    return {
        "speech_source": speech_source,
        "duration_seconds": duration,
        "frames": len(spans),
        "uncovered_before_first_frame": round(first, 3) if first else 0.0,
        "unframed_speech": unframed,
        "outline": spans,
    }


def nearby_frames(frames: list[dict], frames_dir: Path, start: float, end: float, pad: float, max_frames: int) -> list[dict]:
    selected = []
    for frame in frames:
        t = float(frame["time_seconds"])
        if start - pad <= t <= end + pad:
            selected.append(
                {
                    "time_seconds": t,
                    "timecode": frame.get("timecode", timecode(t)),
                    "file": str(frames_dir / frame["file"]),
                }
            )
    if len(selected) <= max_frames:
        return selected
    if max_frames <= 1:
        return selected[:1]
    step = (len(selected) - 1) / (max_frames - 1)
    return [selected[round(i * step)] for i in range(max_frames)]


def safe_stdio() -> None:
    """Never let a character the console cannot encode crash the script (cp936, cp1252, ...)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass


def add_video_times(entries: list[dict], offset: float) -> None:
    """Annotate recording-clock entries with the video's own clock. No-op when offset is 0."""
    if not offset:
        return
    for entry in entries:
        start = entry["start"] - offset
        end = entry["end"] - offset
        entry["video_start"] = round(start, 3)
        entry["video_end"] = round(end, 3)
        entry["video_range"] = f"{timecode(start)}-{timecode(end)}"
        entry["before_video_start"] = end <= 0


def main() -> int:
    safe_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--transcript", help="Transcript file: .srt, .vtt, or JSON. Optional for --outline only.")
    parser.add_argument("--frames", required=True, help="frames.json from extract_media_assets.py.")
    parser.add_argument("--output", default="timeline.json")
    parser.add_argument("--outline", help="visual_outline.json path (default: next to --output).")
    parser.add_argument("--speech-source", default="unspecified",
                        choices=["transcribed", "captions-only", "heard", "none", "unspecified"],
                        help="Evidence label of the transcript, copied into visual_outline.json.")
    parser.add_argument("--recording-offset", type=float, default=0.0,
                        help="Route C: seconds between the start of the RECORDING and the start of the "
                             "VIDEO. Every time in a recording is on the recording's clock; with this set, "
                             "each entry also carries video_start / video_end / video_range "
                             "(recording time minus the offset) for citing the video's own timeline.")
    parser.add_argument("--transcript-shift", type=float, default=0.0,
                        help="Seconds to ADD to every transcript time before aligning. Site captions are "
                             "often timed to the programme without the intro the downloaded file has "
                             "(measured on TED: captions 3.4 s early). Check two or three lines against "
                             "the audio or a frame, then pass the difference. Recorded in the output.")
    parser.add_argument("--estimate-shift-from", metavar="REFERENCE",
                        help="A transcript recognised from THIS file's audio (.srt/.vtt/.json). Lines of "
                             "--transcript are matched to it by their words and the typical time difference "
                             "is reported as suggested_transcript_shift. Nothing is shifted: check it, then "
                             "pass --transcript-shift yourself.")
    parser.add_argument("--pad", type=float, default=2.0, help="Seconds around each transcript segment to include frames.")
    parser.add_argument("--max-frames", type=int, default=3, help="Max frames per transcript segment.")
    args = parser.parse_args()

    frames_path = Path(args.frames).expanduser().resolve()
    meta = load_frames_meta(frames_path)
    frames_dir, frames = load_frames(frames_path)
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    outline_path = Path(args.outline).expanduser().resolve() if args.outline else output.parent / "visual_outline.json"

    transcript = load_transcript(Path(args.transcript).expanduser().resolve()) if args.transcript else None
    shift_report = None
    if transcript is not None and args.estimate_shift_from:
        reference = load_transcript(Path(args.estimate_shift_from).expanduser().resolve())
        shift_report = estimate_shift(transcript, reference)
    if transcript is not None and args.transcript_shift:
        for segment in transcript:
            segment["start"] = max(0.0, segment["start"] + args.transcript_shift)
            segment["end"] = max(0.0, segment["end"] + args.transcript_shift)
    result = {"outline": str(outline_path)}
    if transcript is not None:
        timeline = []
        for segment in transcript:
            timeline.append(
                {
                    "start": segment["start"],
                    "end": segment["end"],
                    "range": f"{timecode(segment['start'])}-{timecode(segment['end'])}",
                    "transcript": segment["text"],
                    "frames": nearby_frames(frames, frames_dir, segment["start"], segment["end"], args.pad, args.max_frames),
                }
            )
        add_video_times(timeline, args.recording_offset)
        timeline_doc = {"segments": timeline}
        if args.recording_offset:
            timeline_doc = {"timeline": "recording", "recording_offset_seconds": args.recording_offset,
                            "segments": timeline}
        if meta.get("frame_set_id"):
            timeline_doc["frame_set_id"] = meta["frame_set_id"]
        if args.transcript_shift:
            timeline_doc["transcript_shift_seconds"] = args.transcript_shift
        output.write_text(json.dumps(timeline_doc, indent=2, ensure_ascii=False), encoding="utf-8")
        result.update({"output": str(output), "segments": len(timeline)})
    speech_source = args.speech_source if transcript is not None else "none"
    outline = build_visual_outline(frames, frames_dir, transcript, meta.get("duration_seconds"), speech_source)
    add_video_times(outline["outline"], args.recording_offset)
    if args.recording_offset:
        outline["timeline"] = "recording"
        outline["recording_offset_seconds"] = args.recording_offset
        for span in outline["outline"]:
            add_video_times(span["speech"], args.recording_offset)
        add_video_times(outline["unframed_speech"], args.recording_offset)
    if meta.get("frame_set_id"):
        outline["frame_set_id"] = meta["frame_set_id"]
    if args.transcript_shift:
        outline["transcript_shift_seconds"] = args.transcript_shift
    outline_path.parent.mkdir(parents=True, exist_ok=True)
    outline_path.write_text(json.dumps(outline, indent=2, ensure_ascii=False), encoding="utf-8")
    result["outline_frames"] = outline["frames"]
    if args.transcript_shift:
        result["transcript_shift_seconds"] = args.transcript_shift
    if shift_report is not None:
        result["shift_check"] = shift_report
        if shift_report.get("suggested_transcript_shift") and not args.transcript_shift:
            print(f"NOTE: the transcript looks {abs(shift_report['suggested_transcript_shift']):g} s "
                  f"{'early' if shift_report['suggested_transcript_shift'] > 0 else 'late'} against the audio "
                  f"({shift_report['matched_lines']} matching lines). Check two lines, then re-run with "
                  f"--transcript-shift {shift_report['suggested_transcript_shift']:g}.", file=sys.stderr)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
