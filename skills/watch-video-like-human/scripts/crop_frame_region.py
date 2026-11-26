#!/usr/bin/env python3
"""Crop one region of a video frame at the SOURCE resolution (v5.3).

Use it when a formula, a question, a table cell or a handwritten note is too small to read in
the normal keyframes. Climb the ladder in this order - cropping is the last step, not the first:

  1. re-extract at full width      extract_media_assets.py VIDEO --width 0 --at 83.4
  2. add nearby frames             ... --at 82,83.4,85   (the board may be clearer a moment later)
  3. crop the region               crop_frame_region.py VIDEO --at 83.4 --region 0.05,0.30,0.50,0.25

The region is ``x,y,width,height`` as fractions (0-1) of the frame, origin at the top left.
The crop is taken from the decoded source frame, before any scaling, and written as a lossless
PNG. It is only ever scaled DOWN (``--max-width``), never up: enlarging adds pixels, not detail,
and a crop cannot recover anything the source video does not contain.

An already extracted image can be cropped too (``--image frames/frame_000012.jpg``), for Route B
screenshots where no media file exists. That crop is no sharper than the image it came from, and
the record says so.

Every crop is appended to ``OUT_DIR/crops.json`` with the real frame time (decoder PTS), the
region, the pixel box and the source size, so it can be registered in the evidence manifest:

  python evidence_manifest.py add -m WORK/evidence_manifest.json --kind crops --path WORK/crops.json
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
import math
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

SCHEMA_VERSION = "5.3"
SHOWINFO_RE = re.compile(r"\bn:\s*\d+\s+pts:\s*-?\d+\s+pts_time:\s*(-?[\d.]+).*?\bs:(\d+)x(\d+)")
LIMIT_NOTE = ("cropped from the source frame, never enlarged; a crop cannot recover detail the "
              "source video does not contain")
IMAGE_NOTE = ("cropped from an already extracted image, so it is no sharper than that image; "
              "crop from the media file at source resolution when one exists")


def safe_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass


def parse_region(value: str) -> tuple[float, float, float, float]:
    """'x,y,w,h' as 0-1 fractions. Rejects anything that leaves the frame."""
    try:
        parts = [float(p) for p in value.replace(" ", "").split(",")]
    except ValueError:
        raise SystemExit(f"--region must be four numbers x,y,width,height (0-1), got: {value}")
    if len(parts) != 4 or any(math.isnan(p) or math.isinf(p) for p in parts):
        raise SystemExit(f"--region must be four numbers x,y,width,height (0-1), got: {value}")
    x, y, w, h = parts
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1):
        raise SystemExit("--region values are fractions of the frame: 0 <= x,y < 1 and 0 < width,height <= 1. "
                         f"Got {value}. Pixels are not accepted - divide by the frame size.")
    if x + w > 1 + 1e-9 or y + h > 1 + 1e-9:
        raise SystemExit(f"--region {value} runs past the frame edge (x+width and y+height must be <= 1).")
    return x, y, min(w, 1 - x), min(h, 1 - y)


def pixel_box(region: tuple[float, float, float, float], width: int, height: int) -> dict:
    """Outward-rounded pixel box, always at least 1x1 and inside the frame."""
    x, y, w, h = region
    left = max(0, min(width - 1, math.floor(x * width)))
    top = max(0, min(height - 1, math.floor(y * height)))
    right = max(left + 1, min(width, math.ceil((x + w) * width - 1e-9)))
    bottom = max(top + 1, min(height, math.ceil((y + h) * height - 1e-9)))
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}


def parse_time(value: str) -> float:
    seconds = 0.0
    try:
        for piece in value.strip().split(":"):
            seconds = seconds * 60 + float(piece)
    except ValueError:
        raise SystemExit(f"--at must be seconds or [hh:]mm:ss, got: {value}")
    if seconds < 0:
        raise SystemExit("--at must not be negative.")
    return seconds


def png_size(path: Path) -> tuple[int, int] | None:
    try:
        head = path.read_bytes()[:24]
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          stdin=subprocess.DEVNULL)


def decode_frame(ffmpeg: str, source: Path, at: float | None, staging: Path) -> tuple[float | None, int, int]:
    """Write the full source frame as a lossless PNG; return (real time, width, height)."""
    if staging.exists():
        staging.unlink()
    attempts = []
    if at is None:
        attempts.append([ffmpeg, "-y", "-hide_banner", "-nostdin", "-i", str(source),
                         "-vf", "showinfo", "-frames:v", "1", str(staging)])
    else:
        # Input seek: showinfo reports the offset from the seek point, so real time = at + pts_time.
        attempts.append([ffmpeg, "-y", "-hide_banner", "-nostdin", "-ss", f"{at}", "-i", str(source),
                         "-vf", "showinfo", "-frames:v", "1", str(staging)])
        # Containers that cannot seek (MPEG-TS...): decode from the start, take the first frame >= at.
        attempts.append([ffmpeg, "-y", "-hide_banner", "-nostdin", "-i", str(source),
                         "-vf", f"select='gte(t,{at})',showinfo", "-frames:v", "1", str(staging)])
    error = ""
    for n, cmd in enumerate(attempts):
        proc = run(cmd)
        match = SHOWINFO_RE.search(proc.stderr)
        if proc.returncode == 0 and staging.is_file() and match:
            offset = max(float(match.group(1)), 0.0)
            if at is None:
                found = None
            else:
                found = at + offset if n == 0 else offset
            return found, int(match.group(2)), int(match.group(3))
        error = proc.stderr[-1500:]
    where = "the image" if at is None else f"{at}s"
    raise SystemExit(f"No frame could be decoded at {where}:\n{error}")


def main() -> int:
    safe_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", nargs="?", help="Local media file. Omit when --image is given.")
    parser.add_argument("--at", help="Time of the frame, seconds or [hh:]mm:ss. Required with a media file.")
    parser.add_argument("--image", help="Crop an existing image instead of a media file (no sharper than that image).")
    parser.add_argument("--region", required=True,
                        help="x,y,width,height as 0-1 fractions of the frame, origin top-left. Example: 0.05,0.30,0.50,0.25")
    parser.add_argument("--max-width", type=int, default=1600,
                        help="Scale the crop DOWN to this width if it is wider. Never scales up. 0 = keep as is.")
    parser.add_argument("--out-dir", default="video-assets", help="Output directory (crops/ and crops.json go here).")
    parser.add_argument("--name", help="Output file stem. Default: built from the time and the region.")
    args = parser.parse_args()

    if bool(args.video) == bool(args.image):
        raise SystemExit("Give either a media file with --at, or --image. Not both, not neither.")
    if args.video and args.at is None:
        raise SystemExit("--at is required with a media file.")
    if args.max_width < 0:
        raise SystemExit("--max-width must be 0 or greater.")
    region = parse_region(args.region)
    at = parse_time(args.at) if args.video else None
    source = Path(args.video or args.image).expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"File not found: {source}")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg was not found on PATH.")

    out_dir = Path(args.out_dir).expanduser().resolve()
    crop_dir = out_dir / "crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    staging = crop_dir / "_source_frame.png"
    found, src_w, src_h = decode_frame(ffmpeg, source, at, staging)

    box = pixel_box(region, src_w, src_h)
    scaled = bool(args.max_width) and box["width"] > args.max_width
    chain = f"crop={box['width']}:{box['height']}:{box['left']}:{box['top']}:exact=1"
    if scaled:
        chain += f",scale={args.max_width}:-1:flags=lanczos"
    tag = "-".join(f"{round(v * 1000):04d}" for v in region)
    stem = args.name or (f"crop_t{int(round((found or 0) * 1000)):09d}_{tag}" if at is not None
                         else f"crop_{source.stem}_{tag}")
    if not re.fullmatch(r"[\w.\-]+", stem):
        raise SystemExit("--name may contain only letters, digits, '_', '-' and '.'.")
    output = crop_dir / f"{stem}.png"
    proc = run([ffmpeg, "-y", "-hide_banner", "-nostdin", "-i", str(staging), "-vf", chain,
                "-frames:v", "1", str(output)])
    staging.unlink(missing_ok=True)
    size = png_size(output) if proc.returncode == 0 else None
    if size is None:
        raise SystemExit(f"Cropping failed:\n{proc.stderr[-1500:]}")

    record = {
        "file": output.name,
        "source": str(source),
        "source_kind": "media" if args.video else "image",
        "time_seconds": round(found, 3) if found is not None else None,
        "requested_seconds": at,
        "region": {"x": region[0], "y": region[1], "width": region[2], "height": region[3],
                   "units": "fraction of the frame, origin top-left"},
        "pixel_box": box,
        "source_size": {"width": src_w, "height": src_h},
        "output_size": {"width": size[0], "height": size[1]},
        "scaled_down": scaled,
        "upscaled": False,
        "note": LIMIT_NOTE if args.video else IMAGE_NOTE,
    }
    index_path = out_dir / "crops.json"
    index = {"schema_version": SCHEMA_VERSION, "crops_dir": str(crop_dir), "crops": []}
    if index_path.is_file():
        try:
            loaded = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(loaded.get("crops"), list):
                index["crops"] = [c for c in loaded["crops"] if c.get("file") != output.name]
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    index["crops"].append(record)
    for n, crop in enumerate(index["crops"], start=1):
        crop["index"] = n
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"crop": str(output), "index": record["index"], "time_seconds": record["time_seconds"],
                      "pixel_box": box, "source_size": record["source_size"],
                      "output_size": record["output_size"], "scaled_down": scaled, "crops_json": str(index_path)},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
