#!/usr/bin/env python3
"""Page through a transcript from the first segment to the last (v5.3).

Complete notes need the complete transcript. Reading the opening and the ending, searching for
keywords or sampling a few pages is not reading it. This script serves the transcript in pages,
gives every segment a stable 1-based index (cite these in `evidence_manifest.py claim
--segments`), and keeps a read log beside the transcript so that "read in full" is a recorded
fact rather than a claim:

  python read_transcript.py WORK/transcript.srt                 # page 1 (segments 1-200)
  python read_transcript.py WORK/transcript.srt --offset 200    # continue at next_offset
  ...                                                           # until next_offset is null
  python read_transcript.py WORK/transcript.srt --status        # how much has been served
  python read_transcript.py WORK/transcript.srt --gaps --duration 1830

`--gaps` lists every window longer than 20 s with no speech. A gap is a lead, not a verdict:
look at the frames in that window. It may be silence, a break, music, a demo with no narration,
or a part the transcript missed.

`timing` in the output is `segment` or `chunk`. Chunk-level timing (long blocks, typical of a
remote ASR that returns one timestamp per audio chunk) tells you the range a sentence lies in,
not when it was said: cite the range, never a precise anchor invented from it.

`--cues` lists the moments where the speaker points at the picture ("look here", "as you can
see", "this chart", "看这里", "如图", "注意这个"...). The words say that something on screen
matters right then, and automatic keyframes often miss it. Read the transcript first, then add
frames at those moments - the output ends with a ready-made `--at` list:

  python read_transcript.py WORK/transcript.srt --cues
  python extract_media_assets.py VIDEO --out-dir WORK --at 272.0,430.5,595.0

A cue is a candidate, found by matching phrases. It does not say what is on screen: open the
frame. `--cues` serves no page and does not count as reading the transcript.

Accepts .srt, .vtt and JSON ([{start,end,text}] or {"segments": [...]}).
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

GAP_SECONDS = 20.0
CHUNK_MEDIAN_SECONDS = 20.0
MAX_LIMIT = 500
# Phrases a presenter uses when the picture carries the point. Deliberately specific: a bare
# "this" or "这个" would match almost every sentence.
CUE_PHRASES = [
    "look at", "look here", "take a look", "as you can see", "you can see", "you'll see", "notice",
    "as shown", "shown here", "on the screen", "on screen", "on the slide", "this slide", "this chart",
    "this graph", "this diagram", "this figure", "this table", "this picture", "this image", "over here",
    "right here", "highlighted", "circled", "the arrow", "watch what happens", "let me show",
    "\u770b\u8fd9\u91cc", "\u770b\u8fd9\u4e2a", "\u770b\u4e00\u4e0b", "\u770b\u4e0b", "\u5927\u5bb6\u770b", "\u6211\u4eec\u770b", "\u6765\u770b",
    "\u53ef\u4ee5\u770b\u5230", "\u80fd\u770b\u5230", "\u770b\u5230\u8fd9", "\u6ce8\u610f\u8fd9", "\u6ce8\u610f\u770b", "\u8bf7\u6ce8\u610f",
    "\u5982\u56fe", "\u56fe\u4e2d", "\u56fe\u4e0a", "\u8fd9\u5f20\u56fe", "\u8fd9\u4e2a\u56fe", "\u8fd9\u5e45\u56fe", "\u8fd9\u5f20\u8868",
    "\u8fd9\u4e2a\u8868", "\u5c4f\u5e55\u4e0a", "\u753b\u9762", "\u8fd9\u4e00\u9875", "\u8fd9\u9875", "\u8fd9\u91cc\u5199",
    "\u5199\u7684\u662f", "\u7bad\u5934", "\u5708\u51fa", "\u6807\u7ea2", "\u753b\u7ebf", "\u9ec4\u8272\u7684", "\u7ea2\u8272\u7684",
    "\u7ed9\u5927\u5bb6\u6f14\u793a", "\u6f14\u793a\u4e00\u4e0b", "\u5de6\u8fb9\u8fd9", "\u53f3\u8fb9\u8fd9", "\u4e0a\u9762\u8fd9", "\u4e0b\u9762\u8fd9",
]
CUE_MERGE_SECONDS = 5.0
TIME_RE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})(?:[,.](\d{1,3}))?")


def utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass


def parse_clock(value: str) -> float:
    match = TIME_RE.search(value)
    if not match:
        raise ValueError(value)
    millis = int((match.group(4) or "0").ljust(3, "0")[:3])
    return int(match.group(1) or 0) * 3600 + int(match.group(2)) * 60 + int(match.group(3)) + millis / 1000


def transcript_segments(path: Path) -> list[dict]:
    """Segments in file order, empty ones skipped. Index = 1-based position in this list.

    evidence_manifest.py carries the same function; the two must number segments identically.
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


def clock(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    whole = int(seconds)
    return f"{whole // 3600:02d}:{whole % 3600 // 60:02d}:{whole % 60:02d}"


def timing_kind(segments: list[dict]) -> str:
    if not segments:
        return "segment"
    lengths = sorted(s["end"] - s["start"] for s in segments)
    return "chunk" if lengths[len(lengths) // 2] >= CHUNK_MEDIAN_SECONDS else "segment"


def find_gaps(segments: list[dict], threshold: float, duration: float | None) -> list[dict]:
    gaps = []
    ordered = sorted(segments, key=lambda s: s["start"])
    cursor, before = 0.0, None
    for seg in ordered:
        if seg["start"] - cursor > threshold:
            gaps.append({"start": round(cursor, 3), "end": round(seg["start"], 3),
                         "seconds": round(seg["start"] - cursor, 3),
                         "after_segment": before, "before_segment": seg["index"]})
        if seg["end"] >= cursor:
            cursor, before = seg["end"], seg["index"]
    if duration is not None and duration - cursor > threshold:
        gaps.append({"start": round(cursor, 3), "end": round(duration, 3),
                     "seconds": round(duration - cursor, 3), "after_segment": before, "before_segment": None})
    return gaps


def find_cues(segments: list[dict], phrases: list[str], limit: int, merge_seconds: float = CUE_MERGE_SECONDS,
              start: float | None = None, end: float | None = None) -> tuple[list[dict], int]:
    """Moments where the speech points at the picture. Returns (cues, how many were cut by the limit)."""
    chunk = timing_kind(segments) == "chunk"
    lowered = [p.lower() for p in phrases if p.strip()]
    cues: list[dict] = []
    for seg in sorted(segments, key=lambda s: s["start"]):
        if (start is not None and seg["end"] < start) or (end is not None and seg["start"] > end):
            continue
        text = seg["text"].lower()
        hits = [p for p in lowered if p in text]
        if not hits:
            continue
        # With chunk-level timing the phrase may sit anywhere in the block: take the middle and say so.
        at = (seg["start"] + seg["end"]) / 2 if chunk else seg["start"]
        if cues and at - cues[-1]["at_seconds"] <= merge_seconds:
            cues[-1]["segments"].append(seg["index"])
            cues[-1]["phrases"] = sorted(set(cues[-1]["phrases"]) | set(hits))
            continue
        cues.append({"at_seconds": round(at, 3), "clock": clock(at), "segments": [seg["index"]],
                     "phrases": sorted(hits), "text": seg["text"][:160],
                     "precision": "chunk (somewhere in this block)" if chunk else "segment start"})
    cut = max(0, len(cues) - limit) if limit else 0
    if cut:
        # keep the cues with the most phrase hits, then restore time order
        keep = sorted(sorted(cues, key=lambda c: -len(c["phrases"]))[:limit], key=lambda c: c["at_seconds"])
        cues = keep
    return cues, cut


def merge_ranges(ranges: list[list[int]]) -> list[list[int]]:
    merged: list[list[int]] = []
    for start, end in sorted(r for r in ranges if r[1] > r[0]):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def log_path_for(transcript: Path) -> Path:
    return transcript.with_name(transcript.name + ".readlog.json")


def load_log(path: Path, sha: str, total: int) -> dict:
    fresh = {"transcript_sha256": sha, "total_segments": total, "served": [], "complete": False}
    try:
        log = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fresh
    if log.get("transcript_sha256") != sha or log.get("total_segments") != total:
        return fresh  # the transcript changed: what was read before no longer counts
    log["served"] = merge_ranges([list(r) for r in log.get("served", [])])
    return log


def progress(log: dict) -> dict:
    served = sum(end - start for start, end in log["served"])
    total = log["total_segments"]
    missing = []
    cursor = 0
    for start, end in log["served"]:
        if start > cursor:
            missing.append(f"{cursor + 1}-{start}")
        cursor = max(cursor, end)
    if cursor < total:
        missing.append(f"{cursor + 1}-{total}")
    return {"segments_served": served, "total_segments": total,
            "complete": total > 0 and served >= total, "missing_segments": missing}


def main() -> int:
    utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("transcript", help=".srt, .vtt or JSON transcript.")
    parser.add_argument("--offset", type=int, default=0, help="0-based position to start at (use next_offset).")
    parser.add_argument("--limit", type=int, default=200, help=f"Segments per page (1-{MAX_LIMIT}).")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of readable lines.")
    parser.add_argument("--status", action="store_true", help="Only report how much has been served so far.")
    parser.add_argument("--gaps", action="store_true", help="List windows with no speech; serves no segments.")
    parser.add_argument("--gap-seconds", type=float, default=GAP_SECONDS)
    parser.add_argument("--duration", type=float, help="Media duration in seconds, to find a gap at the end.")
    parser.add_argument("--cues", action="store_true",
                        help="List moments where the speaker points at the picture, with an --at list. "
                             "Serves no segments.")
    parser.add_argument("--cue-phrase", action="append", default=[],
                        help="An extra phrase to treat as a visual cue. Repeatable.")
    parser.add_argument("--max-cues", type=int, default=20, help="Most cues to list (0 = all).")
    parser.add_argument("--start", type=float, help="--cues only: ignore speech before this second.")
    parser.add_argument("--end", type=float, help="--cues only: ignore speech after this second.")
    parser.add_argument("--log", help="Read-log path. Default: TRANSCRIPT.readlog.json beside the transcript.")
    parser.add_argument("--no-log", action="store_true", help="Do not record this page in the read log.")
    args = parser.parse_args()

    path = Path(args.transcript).expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"Transcript not found: {path}")
    if not 1 <= args.limit <= MAX_LIMIT:
        raise SystemExit(f"--limit must be between 1 and {MAX_LIMIT}.")
    if args.offset < 0:
        raise SystemExit("--offset must be 0 or greater.")
    try:
        segments = transcript_segments(path)
    except (ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not parse {path}: {exc}")
    total = len(segments)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    log_file = Path(args.log).expanduser().resolve() if args.log else log_path_for(path)
    log = load_log(log_file, sha, total)
    timing = timing_kind(segments)

    if args.gaps:
        gaps = find_gaps(segments, args.gap_seconds, args.duration)
        result = {"transcript": str(path), "total_segments": total, "timing": timing,
                  "gap_threshold_seconds": args.gap_seconds, "gaps": gaps,
                  "note": "A gap is a lead to check in the frames, not proof that content is missing."}
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"{len(gaps)} window(s) longer than {args.gap_seconds:g}s without speech "
                  f"(timing: {timing}; {total} segments)")
            for gap in gaps:
                after = (f"after segment {gap['after_segment']}" if gap["after_segment"] is not None
                         else "from the start of the video")
                before = (f"before segment {gap['before_segment']}" if gap["before_segment"] is not None
                          else "to the end of the video")
                print(f"  {clock(gap['start'])}-{clock(gap['end'])}  {gap['seconds']:.0f}s  {after}, {before}")
            print(result["note"])
        return 0

    if args.cues:
        cues, cut = find_cues(segments, CUE_PHRASES + args.cue_phrase, args.max_cues, start=args.start, end=args.end)
        at_list = ",".join(f"{c['at_seconds']:g}" for c in cues)
        follow = sorted({round(c["at_seconds"] + extra, 3) for c in cues for extra in (0, 5, 10)})
        at_follow = ",".join(f"{t:g}" for t in follow)
        note = ("Candidates only, found by phrase matching. Open each frame; the words do not say what "
                "is on screen. Not a substitute for reading the transcript. A cue's time is where its "
                "sentence STARTS: what it points at can appear several seconds later (measured: a title "
                "card at the cue, the diagram 16 s after it), so the second list adds frames 5 and 10 s on. "
                "No cue found does not mean nothing is shown: the built-in phrases are few - add the "
                "speaker's own with --cue-phrase.")
        if timing == "chunk":
            note += " Timing is chunk-level: the cue is somewhere in its block, so add a few frames around it."
        if args.json:
            print(json.dumps({"transcript": str(path), "total_segments": total, "timing": timing, "cues": cues,
                              "at": at_list, "at_with_follow_ups": at_follow, "not_listed": cut, "note": note},
                             indent=2, ensure_ascii=False))
        else:
            print(f"{len(cues)} visual cue(s) in {total} segments (timing: {timing})"
                  + (f"; {cut} more not listed, raise --max-cues" if cut else ""))
            for cue in cues:
                print(f"  {cue['clock']}  [{','.join(str(i) for i in cue['segments'])}]  {cue['text']}")
            print(f"--at {at_list}" if at_list else "--at (none)")
            if at_list:
                print(f"--at {at_follow}    (each cue plus 5 s and 10 s after it)")
            print(note)
        return 0

    if args.status:
        print(json.dumps({"transcript": str(path), "timing": timing, "read_log": str(log_file), **progress(log),
                          "proves": "every listed range was printed by this script; it cannot prove the text "
                                    "was read or understood"},
                         indent=2, ensure_ascii=False))
        return 0

    page = segments[args.offset:args.offset + args.limit]
    end = args.offset + len(page)
    next_offset = end if end < total else None
    if page and not args.no_log:
        log["served"] = merge_ranges(log["served"] + [[args.offset, end]])
        state = progress(log)
        log["complete"] = state["complete"]
        log["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        log_file.write_text(json.dumps(log, indent=2), encoding="utf-8")
    state = progress(log)
    reminder = ("Transcript served to the end. (That is all this log can show: every page was printed. "
                "Whether it was understood is the reader's responsibility.)" if state["complete"] else
                "Not finished: keep reading until next_offset is null. Do not write complete notes "
                "from a partial read.")
    if timing == "chunk":
        reminder += (" Timing is chunk-level: a block's time range is not the time of a sentence in it. "
                     "Cite ranges; locate exact moments with frames.")
    if args.json:
        print(json.dumps({"transcript": str(path), "total_segments": total, "offset": args.offset,
                          "limit": args.limit, "timing": timing, "segments": page,
                          "next_offset": next_offset, "progress": state, "reminder": reminder},
                         indent=2, ensure_ascii=False))
    else:
        if page:
            print(f"# {path.name}: segments {args.offset + 1}-{end} of {total} (timing: {timing})")
        else:
            print(f"# {path.name}: no segments at offset {args.offset} - the transcript has {total} "
                  f"(timing: {timing})")
        for seg in page:
            print(f"[{seg['index']}] {clock(seg['start'])}-{clock(seg['end'])}  {seg['text']}")
        print(f"# next_offset: {'null' if next_offset is None else next_offset}  "
              f"served so far: {state['segments_served']}/{total}")
        print(f"# {reminder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
