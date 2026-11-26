#!/usr/bin/env python3
"""Normalize caption/transcript data into clean SRT and JSON.

Accepts what browser extraction actually returns:

  * YouTube ``json3``          - {"events": [{"tStartMs":..., "segs":[{"utf8":...}]}]}
  * YouTube timedtext XML      - <text start="1.5" dur="2.0">...</text>
  * WebVTT (.vtt) / SubRip (.srt)
  * Generic JSON               - [{"start":..,"end":..,"text":..}] or {"segments":[...]}
  * What the browser snippets return (references/browser-extraction.md):
      plain "0:06 words" lines; one pager page {"from","next","total","text"} or a list of
      such pages; the stored-text pieces {"n","chars","piece"} - checked for completeness

Auto-generated captions arrive as tiny fragments, often one or two words per cue. Use
``--merge`` to combine them into readable lines before reading or citing them.

Examples
--------
  python normalize_transcript.py captions.json3 --out transcript --merge
  python normalize_transcript.py captions.xml --out transcript --merge --max-chars 200
  python normalize_transcript.py existing.vtt --out transcript
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
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

TIME_RE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})(?:[,.](\d{1,3}))?")


# --------------------------------------------------------------------------- parsing


def parse_time(value: str) -> float:
    match = TIME_RE.search(value.strip())
    if not match:
        raise ValueError(f"Cannot parse timestamp: {value!r}")
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    millis = int((match.group(4) or "0").ljust(3, "0")[:3])
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def clean(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)          # inline karaoke/style tags
    text = text.replace("​", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_json3(data: dict) -> list[dict]:
    segments = []
    for event in data.get("events", []):
        segs = event.get("segs")
        if not segs:
            continue
        text = clean("".join(s.get("utf8", "") for s in segs))
        if not text:
            continue
        start = float(event.get("tStartMs", 0)) / 1000.0
        dur = float(event.get("dDurationMs", 0)) / 1000.0
        segments.append({"start": start, "end": start + dur, "text": text})
    return segments


def parse_generic_json(data) -> list[dict]:
    if isinstance(data, dict):
        for key in ("segments", "transcript", "events", "cues", "results"):
            if key in data:
                data = data[key]
                break
        else:
            raise SystemExit("JSON object has no segments/transcript/cues array.")
    segments = []
    for item in data:
        if not isinstance(item, dict):
            continue
        raw_start = item.get("start", item.get("start_seconds", item.get("t", 0)))
        start = parse_time(raw_start) if isinstance(raw_start, str) else float(raw_start or 0)
        raw_end = item.get("end", item.get("end_seconds"))
        if raw_end is None:
            end = start + float(item.get("duration", item.get("dur", 0)) or 0)
        else:
            end = parse_time(raw_end) if isinstance(raw_end, str) else float(raw_end)
        text = clean(str(item.get("text", item.get("utf8", item.get("speech", "")))))
        if text:
            segments.append({"start": start, "end": max(end, start), "text": text})
    return segments


def parse_xml(raw: str) -> list[dict]:
    root = ET.fromstring(raw)
    segments = []
    for node in root.iter():
        if node.tag not in ("text", "p"):
            continue
        text = clean("".join(node.itertext()))
        if not text:
            continue
        if "start" in node.attrib:                     # timedtext / srv1
            start = float(node.attrib["start"])
            end = start + float(node.attrib.get("dur", 0) or 0)
        elif "t" in node.attrib:                       # srv3
            start = float(node.attrib["t"]) / 1000.0
            end = start + float(node.attrib.get("d", 0) or 0) / 1000.0
        else:
            continue
        segments.append({"start": start, "end": end, "text": text})
    return segments


def parse_srt_or_vtt(raw: str) -> list[dict]:
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r"^WEBVTT.*?(?:\n\n|\Z)", "", raw, flags=re.S)
    segments = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        timing = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if timing is None:
            continue
        left, right = lines[timing].split("-->", 1)
        text = clean(" ".join(lines[timing + 1:]))
        if not text:
            continue
        segments.append({
            "start": parse_time(left),
            "end": parse_time(right.strip().split(" ")[0]),
            "text": text,
        })
    return segments


LINE_RE = re.compile(r"^\s*\[?((?:\d+:)?\d{1,2}:\d{2})\]?[\s\u3000]+(\S.*?)\s*$")


def parse_timed_lines(raw: str) -> list[dict]:
    """A transcript panel as text: one "0:06 words" line per segment, start times only."""
    segments = []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = LINE_RE.match(line)
        if match:
            text = clean(match.group(2))
            if text:
                start = parse_time(match.group(1))
                segments.append({"start": start, "end": start, "text": text})
        elif line.strip() and segments:              # a wrapped line belongs to the segment above it
            segments[-1]["text"] = clean(segments[-1]["text"] + " " + line)
    return segments


def is_page(item) -> bool:
    """One reply of the page snippets: a pager page ({from, next, total, text}) or a stored piece ({n, chars, piece})."""
    if not isinstance(item, dict) or "start" in item or "t" in item or "segments" in item:
        return False
    return isinstance(item.get("piece"), str) or (isinstance(item.get("text"), str)
                                                   and any(k in item for k in ("next", "total", "lastTime", "from")))


def join_pages(pages: list[dict]) -> str:
    """Put the replies back together in order, and refuse a set that is visibly incomplete."""
    if all("piece" in p for p in pages):
        pages = sorted(pages, key=lambda p: p.get("n", 0))
        text = "".join(p["piece"] for p in pages)
        expected = pages[0].get("chars")
        if isinstance(expected, int) and expected != len(text):
            raise SystemExit(f"The pieces add up to {len(text)} characters but the page stored {expected}: a piece is "
                             "missing or was cut. Fetch the missing piece again; do not fill the gap by hand.")
        return text
    pages = sorted(pages, key=lambda p: p.get("from", 0))
    if pages[-1].get("next") not in (None, "null") and "next" in pages[-1]:
        raise SystemExit(f"The last page says more follows (next = {pages[-1]['next']}): the transcript is not complete. "
                         "Fetch the remaining pages first.")
    return "\n".join(p["text"] for p in pages)


def parse_raw(raw: str) -> list[dict]:
    raw = raw.strip()
    if raw[0] in "{[":
        data = json.loads(raw)
        if isinstance(data, dict) and "events" in data:
            return parse_json3(data)
        pages = [data] if is_page(data) else data if (isinstance(data, list) and data and all(is_page(i) for i in data)) else None
        if pages is not None:
            joined = join_pages(pages)
            if not joined.strip():
                return []
            return parse_raw(joined)                 # stored text is either timed lines or a JSON list of cues
        return parse_generic_json(data)
    if raw.lstrip().startswith("<"):
        return parse_xml(raw)
    if "-->" in raw:
        return parse_srt_or_vtt(raw)
    return parse_timed_lines(raw)


def load(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace").strip()
    if not raw:
        raise SystemExit(f"{path} is empty.")
    return parse_raw(raw)


# --------------------------------------------------------------------------- shaping


def merge_segments(segments: list[dict], gap: float, max_chars: int, max_seconds: float = 12.0) -> list[dict]:
    """Combine fragment cues into readable lines.

    A new line starts when the pause exceeds ``gap`` seconds, the line would exceed
    ``max_chars``, the line would run longer than ``max_seconds``, or the previous line ended on
    sentence punctuation. The time limit matters for captions without punctuation (most Chinese
    and Japanese tracks): without it 103 timed lines became 5 blocks of 40 seconds and every
    time anchor in them was lost.
    """
    merged: list[dict] = []
    for seg in segments:
        if not merged:
            merged.append(dict(seg))
            continue
        prev = merged[-1]
        too_long = (len(prev["text"]) + 1 + len(seg["text"]) > max_chars
                    or (max_seconds > 0 and seg["end"] - prev["start"] > max_seconds))
        big_gap = seg["start"] - prev["end"] > gap
        sentence_end = prev["text"].endswith((".", "!", "?", "。", "！", "？"))
        if too_long or big_gap or sentence_end:
            merged.append(dict(seg))
        else:
            prev["text"] = f"{prev['text']} {seg['text']}".strip()
            prev["end"] = max(prev["end"], seg["end"])
    return merged


def dedupe(segments: list[dict]) -> list[dict]:
    """Drop rolling-caption duplicates where a cue repeats the previous cue's text."""
    out: list[dict] = []
    for seg in segments:
        if out and seg["text"] == out[-1]["text"]:
            out[-1]["end"] = max(out[-1]["end"], seg["end"])
            continue
        out.append(seg)
    return out


def fill_missing_ends(segments: list[dict], duration: float | None) -> int:
    """Give a real span to cues that arrived with a start time only.

    A transcript panel in a web page lists one time per line and no end. Left alone, every cue
    is zero seconds long and the transcript appears to stop where its last line STARTS. Each
    such cue is ended where the next one begins; the last one at the video's length when that
    is known, otherwise after a reading-speed estimate. Filled cues are marked.
    """
    filled = 0
    for i, seg in enumerate(segments):
        if seg["end"] > seg["start"]:
            continue
        later = next((s["start"] for s in segments[i + 1:] if s["start"] > seg["start"]), None)
        if later is not None:
            seg["end"] = later
        elif duration and duration > seg["start"]:
            seg["end"] = float(duration)
        else:
            seg["end"] = seg["start"] + min(max(len(seg["text"]) / 15.0, 2.0), 10.0)
        seg["end_estimated"] = True
        filled += 1
    return filled


# --------------------------------------------------------------------------- output


def srt_time(value: float) -> str:
    value = max(0.0, value)
    total = int(value)
    ms = int(round((value - total) * 1000))
    if ms == 1000:
        total, ms = total + 1, 0
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d},{ms:03d}"


def timecode(value: float) -> str:
    total = int(max(0.0, value))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def to_srt(segments: list[dict]) -> str:
    blocks = []
    for i, seg in enumerate(segments, start=1):
        end = max(seg["end"], seg["start"] + 0.2)
        blocks.append(f"{i}\n{srt_time(seg['start'])} --> {srt_time(end)}\n{seg['text']}\n")
    return "\n".join(blocks)


def to_text(segments: list[dict]) -> str:
    return "\n".join(f"[{timecode(s['start'])}] {s['text']}" for s in segments)


def safe_stdio() -> None:
    """Never let a character the console cannot encode crash the script (cp936, cp1252, ...)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass


def main() -> int:
    safe_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", help="Caption file: json3, XML, VTT, SRT, or generic JSON.")
    parser.add_argument("--out", default="transcript", help="Output basename (no extension).")
    parser.add_argument("--merge", action="store_true", help="Combine fragment cues into readable lines.")
    parser.add_argument("--gap", type=float, default=1.2, help="Seconds of silence that force a new line with --merge.")
    parser.add_argument("--max-chars", type=int, default=240, help="Max characters per merged line.")
    parser.add_argument("--max-seconds", type=float, default=12.0,
                        help="With --merge: a merged line never spans more than this many seconds (0 = no limit).")
    parser.add_argument("--duration", type=float,
                        help="Video length in seconds. Used only to end the LAST cue when the source gives "
                             "start times without end times (a page's transcript panel).")
    parser.add_argument("--quiet", action="store_true", help="Only print the JSON summary.")
    args = parser.parse_args()

    path = Path(args.input).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"Input not found: {path}")

    segments = dedupe(load(path))
    if not segments:
        raise SystemExit("No caption segments found. Drop to the next rung of the evidence ladder.")
    filled = fill_missing_ends(segments, args.duration)
    before_merge = len(segments)
    if args.merge:
        typical = sorted(s["end"] - s["start"] for s in segments)[len(segments) // 2]
        if typical >= 1.5:
            print(f"NOTE: these captions already come as lines (typically {typical:.1f} s each); --merge is meant "
                  "for word-by-word auto-captions. Lines are joined up to "
                  f"{args.max_seconds:g} s; leave --merge out to keep every line's own time.", file=sys.stderr)
        segments = merge_segments(segments, args.gap, args.max_chars, args.max_seconds)

    out_base = Path(args.out).expanduser().resolve()
    out_base.parent.mkdir(parents=True, exist_ok=True)
    srt_path = out_base.with_suffix(".srt")
    json_path = out_base.with_suffix(".json")
    txt_path = out_base.with_suffix(".txt")

    srt_path.write_text(to_srt(segments), encoding="utf-8")
    txt_path.write_text(to_text(segments), encoding="utf-8")
    json_path.write_text(
        json.dumps({"source": str(path), "segments": segments}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    summary = {
        "srt": str(srt_path),
        "json": str(json_path),
        "text": str(txt_path),
        "segments": len(segments),
        "covers": f"{timecode(segments[0]['start'])}-{timecode(segments[-1]['end'])}",
    }
    if args.merge:
        summary["merged_from"] = before_merge
        summary["longest_segment_seconds"] = round(max(s["end"] - s["start"] for s in segments), 1)
    if filled:
        summary["ends_estimated"] = filled
        summary["ends_note"] = ("The source gave start times only. Each cue was ended where the next begins"
                                + ("." if args.duration else "; pass --duration so the last one ends with the video."))
    if not args.quiet:
        print(f"Parsed {len(segments)} segments covering {summary['covers']}.", file=sys.stderr)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
