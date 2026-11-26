#!/usr/bin/env python3
"""Extract keyframes (with real PTS), audio, and metadata from a local video using ffmpeg.

v5.2:
- Probes streams first. A file with no audio stream (for example a Route C --allow-silent
  recording) no longer crashes: audio is skipped, frames.json is still written, and the
  result is marked ``"audio": "none"``.
- Hybrid keyframes: scene-change frames plus a max-gap fill, timestamps taken from the
  decoder's real PTS (ffmpeg showinfo), never ``(index - 1) * interval``.
- Near-duplicate frames are removed with a 64-bit difference hash; the frame count is capped.
- Content-hash cache: re-running with the same file content and parameters into the same
  output directory reuses the existing products.

v5.3:
- ``--detail transcript|efficient|balanced|full`` chooses how much picture evidence to take:
  transcript = no automatic frames (only ``--at`` cue frames) and the audio track;
  efficient = sparse (max gap 10 s, cap 50); balanced = the default (max gap 5 s, cap 120);
  full = uncapped. Explicit ``--interval`` / ``--max-frames`` still win.
- ``--start`` / ``--end`` focus the automatic frames on one stretch of the video. For videos
  longer than about ten minutes, focus first: a fixed cap spread over an hour is thin.
- Frames default to 512 px wide - enough to see what is on screen and cheap to look at. Use
  ``--width 1024`` when text has to be read, ``--width 0`` for source width, and
  ``crop_frame_region.py`` for one small region. Frames are never enlarged, and never taller
  than ``--max-height`` (1998 px), so a portrait video cannot produce an image a viewer rejects.
- Cleanup stays inside this run's own products: ``frames/`` in the output directory and the
  staging folder under it. The source file and everything else in the output directory's parent
  are never touched.
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
import math
import re
import sys
import shutil
import subprocess
from pathlib import Path

SCHEMA_VERSION = "5.4"
DEFAULT_WIDTH = 512
MAX_HEIGHT = 1998
# detail -> (max gap / interval in seconds, frame cap; 0 = uncapped, None = no automatic frames)
DETAIL_PRESETS = {"transcript": (None, None), "efficient": (10.0, 50), "balanced": (5.0, 120), "full": (5.0, 0)}
LONG_VIDEO_SECONDS = 600
THUMB_W, THUMB_H = 9, 8
THUMB_BYTES = THUMB_W * THUMB_H
# A finer grey grid for the "did any region change?" test. dHash and the 9x8 mean both average a
# local change away: a subtitle line, a slide's new bullet, scrolling code or a small player window
# in a mostly static screen recording changes a few cells a lot and the whole frame hardly at all.
# 32x18 was too coarse: at 1280x720 one cell is 40x40 px, and a subtitle line REPLACED by another
# line of similar length, or a single digit that changes, moves a cell's mean by only a few grey
# levels (field test: 2 of 5 such frames were dropped, 4 of 5 for the digit). At 160x90 a cell is
# 8x8 px, so different glyphs give clearly different cells.
GRID_W, GRID_H = 160, 90
GRID_BYTES = GRID_W * GRID_H
MAX_CELL_DIFF = 24          # one cell changing this much is a real local change
SOFT_CELL_DIFF = 12         # ... and so are a few cells changing this much
SOFT_CELL_COUNT = 3
DEDUPE_ALGORITHM = 2        # part of the cache key: results of the older test are not reused
BURST_GAP_SECONDS = 0.6
SHOWINFO_RE = re.compile(r"\bn:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:\s*(-?[\d.]+)")
SCORE_RE = re.compile(r"lavfi\.scene_score=([\d.]+)")


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise SystemExit(f"{name} was not found on PATH.")
    return path


def probe_streams(ffprobe: str, video: Path) -> dict:
    """Return duration and which stream types exist. Never raises on odd files."""
    cmd = [ffprobe, "-v", "error", "-show_entries", "stream=codec_type:format=duration",
           "-of", "json", str(video)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          stdin=subprocess.DEVNULL)
    info = {"duration_seconds": None, "has_video": False, "has_audio": False, "probe_ok": proc.returncode == 0}
    if proc.returncode != 0:
        return info
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return info
    types = {s.get("codec_type") for s in data.get("streams", [])}
    info["has_video"] = "video" in types
    info["has_audio"] = "audio" in types
    try:
        info["duration_seconds"] = float(data.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        pass
    return info


def probe_duration(ffprobe: str, video: Path) -> float | None:
    return probe_streams(ffprobe, video)["duration_seconds"]


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=str(cwd) if cwd else None, stdin=subprocess.DEVNULL)


def seconds_to_timecode(value: float) -> str:
    if value is None or value < 0 or math.isnan(value):
        value = 0
    total = int(value)
    millis = int(round((value - total) * 1000))
    if millis == 1000:
        total += 1
        millis = 0
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


# ---------------------------------------------------------------- hashing / cache

def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def frame_set_identity(frames: list[dict]) -> str:
    """Identity of one frame SET: which file name holds which moment.

    Frame files are numbered in time order, so re-extracting with other settings, or adding --at
    frames, RENUMBERS them: frame_000029.jpg stops being the same picture, and anything aligned
    to the old set would point at the wrong image without any error. The id is copied into
    timeline.json / visual_outline.json so the mismatch can be caught.
    """
    return hashlib.sha256(json.dumps([[f["file"], f["time_seconds"]] for f in frames]).encode()).hexdigest()[:16]


def set_aside_stale_outputs(out_dir: Path, frame_set_id: str) -> list[str]:
    """Rename a timeline / outline that was built from another frame set to *.stale.json."""
    moved = []
    for name in ("timeline.json", "visual_outline.json"):
        path = out_dir / name
        if not path.is_file():
            continue
        try:
            built_from = json.loads(path.read_text(encoding="utf-8")).get("frame_set_id")
        except (ValueError, OSError, AttributeError):
            built_from = None
        if built_from != frame_set_id:
            target = path.with_name(path.stem + ".stale.json")
            path.replace(target)
            moved.append(target.name)
    return moved


def previous_numbering(meta_path: Path) -> dict:
    try:
        old = json.loads(meta_path.read_text(encoding="utf-8"))
        return {f["file"]: round(float(f["time_seconds"]), 3) for f in old.get("frames", [])}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def cache_key(content_hash: str, params: dict) -> str:
    # The script's own hash is part of the key, so editing the extractor invalidates old products.
    code = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    blob = json.dumps({"schema": SCHEMA_VERSION, "code": code, "sha256": content_hash, "params": params},
                      sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def cached_result(out_dir: Path, key: str) -> dict | None:
    meta_path = out_dir / "frames.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if meta.get("cache", {}).get("key") != key:
        return None
    frames_dir = Path(meta.get("frames_dir", out_dir / "frames"))
    if not all((frames_dir / f["file"]).is_file() for f in meta.get("frames", [])):
        return None
    audio = meta.get("audio")
    if audio == "failed":
        return None
    if audio not in (None, "none", "skipped") and not Path(audio).is_file():
        return None
    return meta


# ---------------------------------------------------------------- frame selection

def select_expression(mode: str, interval: float, scene_threshold: float) -> str:
    first = "isnan(prev_selected_t)"
    gap = f"gte(t-prev_selected_t,{interval})"
    scene = f"gt(scene,{scene_threshold})"
    if mode == "interval":
        return f"{first}+{gap}"
    if mode == "scene":
        return f"{first}+{scene}"
    return f"{first}+{scene}+{gap}"  # hybrid


def windowed(expr: str, start: float | None, end: float | None) -> str:
    """Restrict a select expression to [start, end] on the media's own clock."""
    if start is None and end is None:
        return expr
    parts = []
    if start is not None:
        parts.append(f"gte(t,{start})")
    if end is not None:
        parts.append(f"lte(t,{end})")
    return "*".join(parts) + f"*({expr})"


def parse_showinfo(stderr: str) -> list[float]:
    times: dict[int, float] = {}
    for line in stderr.splitlines():
        if "showinfo" not in line:
            continue
        match = SHOWINFO_RE.search(line)
        if match:
            times[int(match.group(1))] = float(match.group(3))
    return [times[i] for i in sorted(times)]


def parse_scores(meta_text: str) -> list[float | None]:
    scores: list[float | None] = []
    for line in meta_text.splitlines():
        if line.startswith("frame:"):
            scores.append(None)
        else:
            match = SCORE_RE.search(line)
            if match and scores:
                scores[-1] = float(match.group(1))
    return scores


def dhash_bits(thumb: bytes) -> int:
    bits = 0
    for row in range(THUMB_H):
        for col in range(THUMB_W - 1):
            left = thumb[row * THUMB_W + col]
            right = thumb[row * THUMB_W + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def mean_abs_diff(a: bytes | None, b: bytes | None) -> float:
    if not a or not b or len(a) != len(b):
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def max_abs_diff(a: bytes | None, b: bytes | None) -> int:
    if not a or not b or len(a) != len(b):
        return 255
    return max(abs(x - y) for x, y in zip(a, b))


def is_near_duplicate(frame: dict, last: dict, max_distance: int, max_luma_diff: float = 10.0,
                      max_cell_diff: int = MAX_CELL_DIFF) -> bool:
    """Three tests, all of which must agree before a frame is called a duplicate.

    dHash alone calls every flat frame identical (solid red and solid blue both hash to 0), so the
    9x8 grey levels must also be close. Those two together still miss a LOCAL change, so no single
    cell of the 160x90 grid may differ by more than ``max_cell_diff`` grey levels, and no more
    than a couple of cells by more than ``SOFT_CELL_DIFF``.
    """
    if frame["dhash"] is None or last["dhash"] is None:
        return False
    if not (hamming(frame["dhash"], last["dhash"]) <= max_distance
            and mean_abs_diff(frame.get("thumb"), last.get("thumb")) <= max_luma_diff):
        return False
    return not local_change(frame.get("grid"), last.get("grid"), max_cell_diff)


def local_change(a: bytes | None, b: bytes | None, max_cell_diff: int = MAX_CELL_DIFF) -> bool:
    """True when some small region differs: one cell strongly, or a few cells moderately."""
    if not a or not b or len(a) != len(b):
        return True
    soft = 0
    for x, y in zip(a, b):
        diff = x - y if x >= y else y - x
        if diff > max_cell_diff:
            return True
        if diff > SOFT_CELL_DIFF:
            soft += 1
            if soft >= SOFT_CELL_COUNT:
                return True
    return False


def same_shot(frame: dict, other: dict) -> bool:
    """A loose likeness test for burst thinning: the same shot seen a moment later, not a cut."""
    if frame.get("dhash") is None or other.get("dhash") is None:
        return False
    return (hamming(frame["dhash"], other["dhash"]) <= 12
            and mean_abs_diff(frame.get("thumb"), other.get("thumb")) <= 18.0)


def scale_chain(width: int | None, max_height: int | None = MAX_HEIGHT) -> str:
    """Scale down to at most `width` wide and `max_height` tall. Never enlarges."""
    steps = []
    if width:
        steps.append(f"scale=w='min(iw,{width})':h=-2")
    if max_height:
        steps.append(f"scale=w=-2:h='min(ih,{max_height})'")
    return ",".join(steps) or "null"


def extract_selected(ffmpeg: str, video: Path, staging: Path, mode: str, interval: float,
                     scene_threshold: float, width: int | None, start: float | None = None,
                     end: float | None = None, max_height: int | None = MAX_HEIGHT) -> list[dict]:
    expr = windowed(select_expression(mode, interval, scene_threshold), start, end)
    graph = (
        f"[0:v]select='{expr}',metadata=mode=print:file=scores.txt,showinfo,split=3[a][b][c];"
        f"[a]{scale_chain(width, max_height)}[full];[b]scale={THUMB_W}:{THUMB_H},format=gray[small];"
        f"[c]scale={GRID_W}:{GRID_H},format=gray[grid]"
    )
    cmd = [ffmpeg, "-y", "-hide_banner", "-nostdin", "-i", str(video), "-filter_complex", graph,
           "-map", "[full]", "-fps_mode", "vfr", "-q:v", "2", "auto_%06d.jpg",
           "-map", "[small]", "-fps_mode", "vfr", "-f", "rawvideo", "auto_thumbs.raw",
           "-map", "[grid]", "-fps_mode", "vfr", "-f", "rawvideo", "auto_grid.raw"]
    proc = run(cmd, cwd=staging)
    if proc.returncode != 0:
        raise SystemExit(f"Frame extraction failed:\n{proc.stderr[-2000:]}")
    times = parse_showinfo(proc.stderr)
    scores_path = staging / "scores.txt"
    scores = parse_scores(scores_path.read_text(encoding="utf-8")) if scores_path.exists() else []
    thumbs = (staging / "auto_thumbs.raw").read_bytes() if (staging / "auto_thumbs.raw").exists() else b""
    grids = (staging / "auto_grid.raw").read_bytes() if (staging / "auto_grid.raw").exists() else b""
    files = sorted(staging.glob("auto_*.jpg"))
    if not files and not times:
        return []  # an empty focus window, or a stream with no decodable frame in it
    if len(times) != len(files):
        raise SystemExit(f"PTS/frame mismatch: {len(times)} timestamps for {len(files)} frames.")
    frames = []
    prev_t = None
    for i, (path, t) in enumerate(zip(files, times)):
        score = scores[i] if i < len(scores) else None
        if prev_t is None:
            reason = "first-frame"
        elif mode != "interval" and score is not None and score > scene_threshold:
            reason = "scene-change"
        else:
            reason = "max-gap" if mode == "hybrid" else "interval"
        thumb = thumbs[i * THUMB_BYTES:(i + 1) * THUMB_BYTES]
        grid = grids[i * GRID_BYTES:(i + 1) * GRID_BYTES]
        frames.append({"staged": path, "time_seconds": t, "reason": reason, "scene_score": score,
                       "thumb": thumb if len(thumb) == THUMB_BYTES else None,
                       "grid": grid if len(grid) == GRID_BYTES else None,
                       "dhash": dhash_bits(thumb) if len(thumb) == THUMB_BYTES else None})
        prev_t = t
    return frames


def extract_manual(ffmpeg: str, video: Path, staging: Path, at: list[float], width: int | None,
                   max_height: int | None = MAX_HEIGHT) -> list[dict]:
    frames = []
    for n, t in enumerate(at, start=1):
        name = f"manual_{n:06d}.jpg"
        graph = (f"[0:v]showinfo,split=2[a][b];[a]{scale_chain(width, max_height)}[full];"
                 f"[b]scale={THUMB_W}:{THUMB_H},format=gray[small]")
        # Input seek without -copyts: showinfo reports the found frame's offset from the seek point,
        # so the real time is t + pts_time, on the same zero-based timeline as the automatic frames.
        cmd = [ffmpeg, "-y", "-hide_banner", "-nostdin", "-ss", f"{t}", "-i", str(video),
               "-filter_complex", graph, "-map", "[full]", "-frames:v", "1", "-q:v", "2", name,
               "-map", "[small]", "-frames:v", "1", "-f", "rawvideo", f"manual_{n:06d}.raw"]
        proc = run(cmd, cwd=staging)
        times = parse_showinfo(proc.stderr)
        found = t + max(times[0], 0.0) if times else None
        if proc.returncode != 0 or not (staging / name).exists() or not times:
            # Some containers (e.g. MPEG-TS) cannot input-seek reliably. Fall back to decoding from
            # the start and selecting the first frame at or after t; showinfo then gives its PTS.
            graph = (f"[0:v]select='gte(t,{t})',showinfo,split=2[a][b];[a]{scale_chain(width, max_height)}[full];"
                     f"[b]scale={THUMB_W}:{THUMB_H},format=gray[small]")
            cmd = [ffmpeg, "-y", "-hide_banner", "-nostdin", "-i", str(video), "-filter_complex", graph,
                   "-map", "[full]", "-frames:v", "1", "-q:v", "2", name,
                   "-map", "[small]", "-frames:v", "1", "-f", "rawvideo", f"manual_{n:06d}.raw"]
            proc = run(cmd, cwd=staging)
            times = parse_showinfo(proc.stderr)
            found = times[0] if times else None
        if proc.returncode != 0 or not (staging / name).exists() or found is None:
            frames.append({"error": f"no frame at {t}s", "requested_seconds": t})
            continue
        thumb = (staging / f"manual_{n:06d}.raw").read_bytes()[:THUMB_BYTES]
        frames.append({"staged": staging / name, "time_seconds": found, "reason": "manual",
                       "requested_seconds": t, "scene_score": None,
                       "thumb": thumb if len(thumb) == THUMB_BYTES else None,
                       "dhash": dhash_bits(thumb) if len(thumb) == THUMB_BYTES else None})
    return frames


def dedupe_and_cap(frames: list[dict], max_distance: int, max_frames: int,
                   burst_gap: float = BURST_GAP_SECONDS) -> tuple[list[dict], list[dict]]:
    """Thin scene-change bursts, drop near-duplicates of the last kept frame, then cap the count.

    Manual frames always stay. ``max_distance < 0`` (--no-dedupe) turns off both the burst
    thinning and the duplicate test.
    """
    kept: list[dict] = []
    dropped: list[dict] = []
    ordered = sorted(frames, key=lambda f: f["time_seconds"])
    if max_distance >= 0 and burst_gap > 0:
        # Handheld or shaking footage fires "scene change" several times a second on what is one
        # shot (measured on a Mac: 9 frames in 2.1 s). Inside such a burst the middle frames are
        # dropped - but only when they still LOOK like their neighbours. Real fast cuts and a
        # subtitle that changes several times a second are different pictures and are kept.
        scene = [f for f in ordered if f["reason"] == "scene-change"]
        burst = []
        for i in range(1, len(scene) - 1):
            if (scene[i]["time_seconds"] - scene[i - 1]["time_seconds"] < burst_gap
                    and scene[i + 1]["time_seconds"] - scene[i]["time_seconds"] < burst_gap
                    and same_shot(scene[i], scene[i - 1]) and same_shot(scene[i], scene[i + 1])):
                scene[i]["drop_reason"] = "scene-burst"
                scene[i]["duplicate_of_time"] = scene[i - 1]["time_seconds"]
                burst.append(scene[i])
        dropped += burst
        burst_ids = {id(f) for f in burst}
        ordered = [f for f in ordered if id(f) not in burst_ids]
    for frame in ordered:
        last = kept[-1] if kept else None
        if (max_distance >= 0 and last is not None and frame["reason"] != "manual"
                and is_near_duplicate(frame, last, max_distance)):
            frame["drop_reason"] = "duplicate"
            frame["duplicate_of_time"] = last["time_seconds"]
            dropped.append(frame)
            continue
        kept.append(frame)
    if max_frames > 0 and len(kept) > max_frames:
        manual = [f for f in kept if f["reason"] == "manual"]
        auto = [f for f in kept if f["reason"] != "manual"]
        room = max(max_frames - len(manual), 1)
        if len(auto) > room:
            # Keep scene changes first, then spread the remaining slots evenly in time.
            priority = [f for f in auto if f["reason"] in ("first-frame", "scene-change")]
            rest = [f for f in auto if f not in priority]
            if len(priority) >= room:
                step = (len(priority) - 1) / max(room - 1, 1)
                chosen = [priority[round(i * step)] for i in range(room)] if room > 1 else priority[:1]
            else:
                need = room - len(priority)
                step = len(rest) / need
                chosen = priority + [rest[int(i * step)] for i in range(need)]
            chosen_ids = {id(f) for f in chosen}
            for f in auto:
                if id(f) not in chosen_ids:
                    f["drop_reason"] = "cap"
                    dropped.append(f)
            auto = [f for f in auto if id(f) in chosen_ids]
        kept = sorted(auto + manual, key=lambda f: f["time_seconds"])
    return kept, dropped


def clear_old_frames(frame_dir: Path) -> None:
    for sub in (frame_dir, frame_dir / "_dropped", frame_dir / ".staging"):
        if not sub.is_dir():
            continue
        for old in sub.iterdir():
            if old.is_file() and (old.name.startswith(("frame_", "auto_", "manual_")) or old.name == "scores.txt"):
                old.unlink()


def extract_frames(ffmpeg: str, video: Path, frame_dir: Path, interval: float, width: int | None,
                   mode: str = "hybrid", scene_threshold: float = 0.3, max_frames: int = 120,
                   dedupe_distance: int = 4, at: list[float] | None = None, start: float | None = None,
                   end: float | None = None, max_height: int | None = MAX_HEIGHT,
                   automatic: bool = True, burst_gap: float = BURST_GAP_SECONDS,
                   ) -> tuple[list[dict], list[dict], list[dict]]:
    frame_dir.mkdir(parents=True, exist_ok=True)
    clear_old_frames(frame_dir)
    staging = frame_dir / ".staging"
    staging.mkdir(exist_ok=True)
    auto = (extract_selected(ffmpeg, video, staging, mode, interval, scene_threshold, width, start, end,
                             max_height) if automatic else [])
    manual = extract_manual(ffmpeg, video, staging, at or [], width, max_height)
    errors = [m for m in manual if "error" in m]
    manual = [m for m in manual if "error" not in m]
    kept, dropped = dedupe_and_cap(auto + manual, dedupe_distance, max_frames, burst_gap)

    frames = []
    for index, frame in enumerate(kept, start=1):
        name = f"frame_{index:06d}.jpg"
        frame["staged"].replace(frame_dir / name)
        entry = {"index": index, "time_seconds": round(frame["time_seconds"], 3),
                 "timecode": seconds_to_timecode(frame["time_seconds"]), "file": name,
                 "pts_source": "decoder-pts", "reason": frame["reason"]}
        if frame.get("scene_score") is not None:
            entry["scene_score"] = round(frame["scene_score"], 4)
        if "requested_seconds" in frame:
            entry["requested_seconds"] = frame["requested_seconds"]
        frames.append(entry)

    dropped_dir = frame_dir / "_dropped"
    dropped_out = []
    if dropped:
        dropped_dir.mkdir(exist_ok=True)
    for n, frame in enumerate(sorted(dropped, key=lambda f: f["time_seconds"]), start=1):
        name = f"frame_dropped_{n:06d}.jpg"
        frame["staged"].replace(dropped_dir / name)
        item = {"time_seconds": round(frame["time_seconds"], 3), "file": f"_dropped/{name}",
                "reason": frame["reason"], "drop_reason": frame["drop_reason"]}
        if "duplicate_of_time" in frame:
            item["duplicate_of_time"] = round(frame["duplicate_of_time"], 3)
        dropped_out.append(item)

    for leftover in staging.iterdir():
        if leftover.is_file():
            leftover.unlink()
    staging.rmdir()
    return frames, dropped_out, errors


# ---------------------------------------------------------------- audio

def extract_audio(ffmpeg: str, video: Path, audio_path: Path) -> tuple[bool, str]:
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    proc = run([ffmpeg, "-y", "-hide_banner", "-nostdin", "-i", str(video), "-vn", "-ac", "1",
                "-ar", "16000", "-c:a", "pcm_s16le", str(audio_path)])
    if proc.returncode != 0 or not audio_path.exists():
        return False, proc.stderr[-1500:]
    return True, ""


def parse_at(value: str | None) -> list[float]:
    if not value:
        return []
    out = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        seconds = 0.0
        for piece in part.split(":"):
            seconds = seconds * 60 + float(piece)
        out.append(seconds)
    return sorted(set(out))


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
    parser.add_argument("video", help="Local video path.")
    parser.add_argument("--out-dir", default="video-assets", help="Output directory.")
    parser.add_argument("--frame-mode", choices=["hybrid", "scene", "interval"], default="hybrid",
                        help="hybrid = scene changes + max-gap fill (default); scene = scene changes only; "
                             "interval = fixed cadence. All modes record real PTS.")
    parser.add_argument("--detail", choices=sorted(DETAIL_PRESETS), default="balanced",
                        help="How much picture evidence to take. transcript = no automatic frames (only --at) "
                             "plus the audio; efficient = max gap 10 s, cap 50; balanced = max gap 5 s, cap 120 "
                             "(default); full = uncapped, costly to look at.")
    parser.add_argument("--start", help="Focus: take automatic frames only from this time on (seconds or [hh:]mm:ss).")
    parser.add_argument("--end", help="Focus: take automatic frames only up to this time.")
    parser.add_argument("--interval", type=float, default=None,
                        help="interval mode: seconds between frames; hybrid mode: maximum gap without a frame. "
                             "Default comes from --detail.")
    parser.add_argument("--scene-threshold", type=float, default=0.3, help="ffmpeg scene score threshold (0-1).")
    parser.add_argument("--max-frames", type=int, default=None,
                        help="Cap on kept frames (0 = no cap). Default comes from --detail.")
    parser.add_argument("--dedupe-distance", type=int, default=4,
                        help="Drop a frame whose 64-bit dHash is within this Hamming distance of the "
                             "previous kept frame (and whose grey grid shows no local change). "
                             "-1 disables deduplication.")
    parser.add_argument("--no-dedupe", action="store_true",
                        help="Keep every selected frame (also turns off burst thinning). Use for screen "
                             "recordings, slides or code where small on-screen changes matter and the frame "
                             "count is acceptable.")
    parser.add_argument("--burst-gap", type=float, default=BURST_GAP_SECONDS,
                        help="Scene-change frames closer together than this many seconds that still look "
                             "alike (a shaking camera) are thinned to the first and last (default 0.6). "
                             "0 turns it off.")
    parser.add_argument("--at", help="Extra frames at these times, e.g. '12.5,01:30,1:02:03'. Never deduped.")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH,
                        help="Maximum frame width (default 512). Use 1024 when text must be read, 0 for the "
                             "source width. Frames are never enlarged.")
    parser.add_argument("--max-height", type=int, default=MAX_HEIGHT,
                        help="Maximum frame height (default 1998, 0 = no limit). Protects portrait videos.")
    parser.add_argument("--no-audio", action="store_true", help="Skip audio extraction.")
    parser.add_argument("--force", action="store_true", help="Ignore the content-hash cache and re-extract.")
    args = parser.parse_args()

    preset_interval, preset_cap = DETAIL_PRESETS[args.detail]
    automatic = preset_interval is not None or args.interval is not None
    if args.interval is None:
        args.interval = preset_interval or 5.0
    if args.max_frames is None:
        args.max_frames = preset_cap if preset_cap is not None else 0
    if args.interval <= 0:
        raise SystemExit("--interval must be greater than 0.")
    if args.width < 0 or args.max_height < 0:
        raise SystemExit("--width and --max-height must be 0 or greater.")
    focus_start = parse_at(args.start)[0] if args.start else None
    focus_end = parse_at(args.end)[0] if args.end else None
    if focus_start is not None and focus_end is not None and focus_end <= focus_start:
        raise SystemExit("--end must be later than --start.")
    if not 0 < args.scene_threshold < 1:
        raise SystemExit("--scene-threshold must be between 0 and 1.")

    ffmpeg = require_tool("ffmpeg")
    ffprobe = require_tool("ffprobe")
    video = Path(args.video).expanduser().resolve()
    if not video.exists():
        raise SystemExit(f"Video not found: {video}")
    at = parse_at(args.at)
    if args.no_dedupe:
        args.dedupe_distance = -1

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    frame_dir = out_dir / "frames"
    audio_path = out_dir / "audio.wav"
    meta_path = out_dir / "frames.json"

    params = {"frame_mode": args.frame_mode, "interval": args.interval, "scene_threshold": args.scene_threshold,
              "max_frames": args.max_frames, "dedupe_distance": args.dedupe_distance, "at": at,
              "width": args.width or None, "no_audio": args.no_audio, "detail": args.detail,
              "automatic": automatic, "start": focus_start, "end": focus_end,
              "max_height": args.max_height or None, "burst_gap": args.burst_gap,
              "dedupe_algorithm": DEDUPE_ALGORITHM}
    content_hash = file_sha256(video)
    key = cache_key(content_hash, params)
    if not args.force:
        hit = cached_result(out_dir, key)
        if hit is not None:
            print(json.dumps({"out_dir": str(out_dir), "frames": len(hit["frames"]), "audio": hit["audio"],
                              "cached": True}, indent=2))
            return 0

    before = previous_numbering(meta_path)
    streams = probe_streams(ffprobe, video)
    frames: list[dict] = []
    dropped: list[dict] = []
    frame_errors: list[dict] = []
    if streams["has_video"]:
        frames, dropped, frame_errors = extract_frames(
            ffmpeg, video, frame_dir, args.interval, args.width or None, args.frame_mode,
            args.scene_threshold, args.max_frames, args.dedupe_distance, at, focus_start, focus_end,
            args.max_height or None, automatic, args.burst_gap)
    else:
        frame_dir.mkdir(parents=True, exist_ok=True)
        clear_old_frames(frame_dir)

    if audio_path.exists():
        audio_path.unlink()
    if args.no_audio:
        audio_value, audio_note = "skipped", "--no-audio was given"
    elif not streams["has_audio"]:
        audio_value, audio_note = "none", "the file has no audio stream; no audio claims are possible"
    else:
        audio_value, audio_note = str(audio_path), ""

    metadata = {
        "schema_version": SCHEMA_VERSION,
        "source": str(video),
        "source_sha256": content_hash,
        "duration_seconds": streams["duration_seconds"],
        "has_video_stream": streams["has_video"],
        "has_audio_stream": streams["has_audio"],
        "detail": args.detail,
        "automatic_frames": automatic,
        "focus": {"start_seconds": focus_start, "end_seconds": focus_end},
        "frame_max_width": args.width or None,
        "frame_max_height": args.max_height or None,
        "frame_mode": args.frame_mode,
        "frame_interval_seconds": args.interval,
        "scene_threshold": args.scene_threshold if args.frame_mode != "interval" else None,
        "timestamps": "real decoder PTS (ffmpeg showinfo), seconds from the start of the media",
        "frames_dir": str(frame_dir),
        "audio": audio_value,
        "audio_note": audio_note,
        "frames": frames,
        "frame_set_id": frame_set_identity(frames),
        "dropped_frames": dropped,
        "dropped_by_reason": {reason: sum(1 for d in dropped if d.get("drop_reason") == reason)
                              for reason in sorted({d.get("drop_reason") or "unknown" for d in dropped})},
        "frame_errors": frame_errors,
        "cache": {"key": key, "params": params},
    }
    moved = sorted(name for name, when in before.items()
                   if any(f["file"] == name and round(float(f["time_seconds"]), 3) != when for f in frames))
    metadata["renumbered_from_previous_run"] = bool(moved)
    stale_moved = set_aside_stale_outputs(out_dir, metadata["frame_set_id"])
    # Write frames.json before audio work so a later audio failure can never orphan the frames.
    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    exit_code = 0
    if audio_value == str(audio_path):
        ok, error = extract_audio(ffmpeg, video, audio_path)
        if not ok:
            tail = error.strip().splitlines()[-1] if error.strip() else "unknown error"
            metadata["audio"] = "failed"
            metadata["audio_note"] = f"audio extraction failed: {tail}"
            metadata["cache"]["key"] = None  # never reuse a failed run
            meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
            exit_code = 1

    summary = {"out_dir": str(out_dir), "frames": len(frames), "dropped": len(dropped),
               "audio": metadata["audio"], "cached": False, "detail": args.detail}
    duration = streams["duration_seconds"] or 0
    if automatic and duration > LONG_VIDEO_SECONDS and focus_start is None and focus_end is None:
        summary["hint"] = (f"This video is {duration / 60:.0f} minutes long. Frames spread over the whole of it "
                           "are sparse: read the transcript first, then re-run with --start/--end on the "
                           "stretches that matter, or add cue frames with --at.")
        metadata["coverage_hint"] = summary["hint"]
        meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    summary["frame_set_id"] = metadata["frame_set_id"]
    if metadata["dropped_by_reason"]:
        summary["dropped_by_reason"] = metadata["dropped_by_reason"]
    if stale_moved:
        summary["stale_outputs_moved"] = stale_moved
        summary["realign"] = ("The frame set changed and frame files were renumbered. " + ", ".join(stale_moved)
                              + " belonged to the previous set and were renamed. Re-run "
                              "align_transcript_frames.py; frame ids noted before this run no longer apply.")
    if moved:
        summary["renumbered"] = len(moved)
        summary["warning"] = (f"{len(moved)} frame file name(s) now hold a DIFFERENT moment than in the previous "
                              "run in this folder (adding --at frames or changing settings renumbers all "
                              "frames). Anything built before is stale: re-run align_transcript_frames.py, and "
                              "re-register the frames (evidence_manifest.py add --kind frames) - old ids such "
                              "as E3.f029 would point at other pictures.")
        print("WARNING: " + summary["warning"], file=sys.stderr)
    if not automatic:
        summary["note"] = ("detail=transcript: no automatic frames were taken"
                           + ("; only the --at cue frames." if at else ". Visual evidence is none."))
    print(json.dumps(summary, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
