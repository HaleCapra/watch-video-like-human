#!/usr/bin/env python3
"""Put a set of extracted frames on one picture: a contact sheet with a label under every tile (v5.6).

Use it to look over many frames in one go before deciding which ones to open at full size:

  python contact_sheet.py --frames WORK/frames.json                     # every frame, 4 x 3 per sheet
  python contact_sheet.py --frames WORK/frames.json --only 1,5-12 --columns 3 --tile-width 640
  python contact_sheet.py --frames WORK/frames.json --start 01:30 --end 04:00

Each tile is one frame, scaled down to fit and never enlarged. The label under it is
``#INDEX TIME``: the frame's index in frames.json and its real time in the media. The sheets are
made with ffmpeg alone (scale, pad, concat, tile, blend); the labels are drawn by this script as
dots, so no font and no extra package is needed.

``OUT_DIR/sheets.json`` lists every sheet and, for each, the frames on it and the cell each one
sits in. Register it so the manifest knows which frames a sheet is made of:

  python evidence_manifest.py add -m WORK/evidence_manifest.json --kind contact-sheets --path WORK/sheets.json

A sheet you opened counts as its frames SEEN AS TILES - enough to say what kind of picture is
where, not enough for small text or fine detail. For those, open the frame itself (or a crop) and
list that id too. A sheet nobody opened counts for nothing. See references/disclosure.md.
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

SCHEMA_VERSION = "5.6"
SEEN_NOTE = ("A tile is a frame at reduced size. Opening a sheet counts as having seen its frames as tiles, "
             "not at full size: small text and fine detail still need the frame itself or a crop.")

# 5x7 dot patterns for the characters a label can hold. Drawn by this script, so no font is needed
# (ffmpeg's drawtext wants a font file or fontconfig, and neither is a given in a static build).
GLYPHS = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    ":": ("00000", "00100", "00100", "00000", "00100", "00100", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "00110", "00110"),
    "#": ("01010", "01010", "11111", "01010", "11111", "01010", "01010"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    " ": ("00000",) * 7,
}


def safe_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass


def clock(seconds: float) -> str:
    """mm:ss.t, or h:mm:ss.t from one hour on - only characters the label can draw."""
    tenths = int(round(max(0.0, float(seconds)) * 10))
    whole, tenth = divmod(tenths, 10)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    body = f"{minutes:02d}:{secs:02d}.{tenth}"
    return f"{hours}:{body}" if hours else body


def parse_time(value: str, label: str) -> float:
    seconds = 0.0
    try:
        for piece in value.strip().split(":"):
            seconds = seconds * 60 + float(piece)
    except ValueError:
        raise SystemExit(f"{label} must be seconds or [hh:]mm:ss, got: {value}")
    if seconds < 0:
        raise SystemExit(f"{label} must not be negative.")
    return seconds


def parse_only(value: str) -> list[int]:
    """'1,3-8,12' -> frame indexes, in the order given, each once."""
    wanted: list[int] = []
    for part in value.replace(" ", "").split(","):
        if not part:
            continue
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not match:
            raise SystemExit(f"--only takes frame indexes such as 1,3-8,12. Got: {part}")
        first, last = int(match.group(1)), int(match.group(2) or match.group(1))
        if last < first:
            raise SystemExit(f"--only range is not valid: {part}")
        wanted += [n for n in range(first, last + 1) if n not in wanted]
    return wanted


def image_size(path: Path) -> tuple[int, int] | None:
    """Width and height of a JPEG or PNG, read from its header."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:2] != b"\xff\xd8":
        return None
    pos = 2
    while pos + 9 < len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
            pos += 2 if marker != 0xFF else 1
            continue
        length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[pos + 5:pos + 9])
            return width, height
        pos += 2 + length
    return None


def label_layer(width: int, height: int, labels: list[tuple[int, int, str]], dot: int) -> bytes:
    """A black picture of the whole sheet with the labels in white, as a binary PPM."""
    rows = [bytearray(width * 3) for _ in range(height)]
    for left, top, text in labels:
        x = left
        for char in text:
            glyph = GLYPHS.get(char, GLYPHS["-"])
            for gy, line in enumerate(glyph):
                for gx, bit in enumerate(line):
                    if bit != "1":
                        continue
                    for dy in range(dot):
                        y = top + gy * dot + dy
                        if not 0 <= y < height:
                            continue
                        start = (x + gx * dot) * 3
                        end = min(start + dot * 3, width * 3)
                        if start < end:
                            rows[y][start:end] = b"\xff" * (end - start)
            x += 6 * dot
    return b"P6\n%d %d\n255\n" % (width, height) + b"".join(bytes(row) for row in rows)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          stdin=subprocess.DEVNULL)


def build_sheet(ffmpeg: str, tiles: list[dict], columns: int, tile_w: int, tile_h: int, output: Path,
                quality: int) -> dict:
    """One sheet: every picture scaled into its cell, the cells tiled, the labels laid over the label bands."""
    dot = max(2, tile_w // 160)
    band = 7 * dot + 2 * dot                       # the label band under each tile
    band += band % 2
    rows = math.ceil(len(tiles) / columns)
    width, height = columns * tile_w, rows * (tile_h + band)
    labels = []
    for n, tile in enumerate(tiles):
        row, col = divmod(n, columns)
        tile["cell"] = {"row": row + 1, "column": col + 1, "left": col * tile_w, "top": row * (tile_h + band),
                        "width": tile_w, "height": tile_h}
        labels.append((col * tile_w + dot * 2, row * (tile_h + band) + tile_h + dot, tile["label"]))
    layer = output.with_name("_labels_" + output.stem + ".ppm")
    layer.write_bytes(label_layer(width, height, labels, dot))
    cmd = [ffmpeg, "-y", "-hide_banner", "-nostdin", "-loglevel", "error"]
    for tile in tiles:
        cmd += ["-i", tile["path"]]
    cmd += ["-i", str(layer)]
    chain = []
    for n in range(len(tiles)):
        chain.append(f"[{n}:v]scale={tile_w}:{tile_h}:force_original_aspect_ratio=decrease:flags=lanczos,"
                     f"pad={tile_w}:{tile_h + band}:(ow-iw)/2:({tile_h}-ih)/2:black,setsar=1,format=gbrp[t{n}]")
    chain.append("".join(f"[t{n}]" for n in range(len(tiles)))
                 + f"concat=n={len(tiles)}:v=1:a=0,tile={columns}x{rows}[grid]")
    chain.append(f"[{len(tiles)}:v]format=gbrp[labels]")
    chain.append("[grid][labels]blend=all_mode=lighten,format=yuvj420p[sheet]")
    cmd += ["-filter_complex", ";".join(chain), "-map", "[sheet]", "-frames:v", "1", "-q:v", str(quality), str(output)]
    proc = run(cmd)
    layer.unlink(missing_ok=True)
    if proc.returncode != 0 or not output.is_file() or output.stat().st_size < 200:
        raise SystemExit(f"The sheet could not be made:\n{proc.stderr[-2000:]}")
    return {"width": width, "height": height, "columns": columns, "rows": rows, "tile_width": tile_w,
            "tile_height": tile_h, "label_band": band}


def main() -> int:
    safe_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frames", required=True, help="frames.json from extract_media_assets.py.")
    parser.add_argument("--out-dir", help="Where sheets/ and sheets.json go. Default: the folder of frames.json.")
    parser.add_argument("--only", help="Frame indexes to put on the sheets, e.g. 1,3-8,12. Default: every frame.")
    parser.add_argument("--start", help="Only frames from this time on (seconds or [hh:]mm:ss).")
    parser.add_argument("--end", help="Only frames up to this time.")
    parser.add_argument("--columns", type=int, default=4, help="Tiles per row (1-8, default 4).")
    parser.add_argument("--rows", type=int, default=3, help="Rows per sheet (1-8, default 3). More frames = more sheets.")
    parser.add_argument("--tile-width", type=int, default=480,
                        help="Width of one tile in pixels (160-1280, default 480). Frames are never enlarged past their own size.")
    parser.add_argument("--quality", type=int, default=3, help="JPEG quality, 2 (best) to 12 (default 3).")
    args = parser.parse_args()

    if not 1 <= args.columns <= 8 or not 1 <= args.rows <= 8:
        raise SystemExit("--columns and --rows must be between 1 and 8.")
    if not 160 <= args.tile_width <= 1280:
        raise SystemExit("--tile-width must be between 160 and 1280.")
    if not 2 <= args.quality <= 12:
        raise SystemExit("--quality must be between 2 and 12.")
    index_path = Path(args.frames).expanduser().resolve()
    if not index_path.is_file():
        raise SystemExit(f"File not found: {index_path}")
    try:
        meta = json.loads(index_path.read_text(encoding="utf-8"))
        listed = list(meta["frames"])
    except (ValueError, KeyError, TypeError):
        raise SystemExit(f"{index_path} is not a frames.json from extract_media_assets.py.")
    frames_dir = Path(meta.get("frames_dir") or index_path.parent / "frames")
    if not frames_dir.is_dir():
        frames_dir = index_path.parent / "frames"

    chosen = listed
    if args.only:
        by_index = {int(f.get("index") or 0): f for f in listed}
        wanted = parse_only(args.only)
        missing = [n for n in wanted if n not in by_index]
        if missing:
            raise SystemExit(f"--only names frames that frames.json does not list: {missing}")
        chosen = [by_index[n] for n in wanted]
    start = parse_time(args.start, "--start") if args.start else None
    end = parse_time(args.end, "--end") if args.end else None
    if start is not None and end is not None and end < start:
        raise SystemExit("--end must be later than --start.")
    chosen = [f for f in chosen if (start is None or f["time_seconds"] >= start)
              and (end is None or f["time_seconds"] <= end)]
    if not chosen:
        raise SystemExit("No frame is left to put on a sheet (check --only, --start and --end).")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg was not found on PATH.")

    tiles = []
    for frame in chosen:
        path = frames_dir / frame["file"]
        if not path.is_file():
            raise SystemExit(f"frames.json lists a frame that does not exist: {path}")
        tiles.append({"index": int(frame.get("index") or 0), "file": frame["file"], "path": str(path),
                      "time_seconds": frame["time_seconds"],
                      "label": f"#{int(frame.get('index') or 0):03d} {clock(frame['time_seconds'])}"})
    size = image_size(Path(tiles[0]["path"]))
    if not size:
        raise SystemExit(f"Could not read the size of {tiles[0]['path']} (JPEG or PNG expected).")
    tile_w = min(args.tile_width, size[0])
    tile_w -= tile_w % 2
    tile_h = max(2, int(round(tile_w * size[1] / size[0])))
    tile_h += tile_h % 2

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else index_path.parent
    sheet_dir = out_dir / "sheets"
    sheet_dir.mkdir(parents=True, exist_ok=True)
    for old in sheet_dir.glob("sheet_*.jpg"):          # sheets of an earlier run of this script, same folder
        old.unlink()
    per_sheet = args.columns * args.rows
    sheets = []
    for n, first in enumerate(range(0, len(tiles), per_sheet), start=1):
        group = tiles[first:first + per_sheet]
        output = sheet_dir / f"sheet_{n:03d}.jpg"
        layout = build_sheet(ffmpeg, group, min(args.columns, len(group)) if len(tiles) <= args.columns else args.columns,
                             tile_w, tile_h, output, args.quality)
        sheets.append({"index": n, "file": output.name, **layout,
                       "frames": [{"index": t["index"], "file": t["file"], "time_seconds": t["time_seconds"],
                                   "label": t["label"], "cell": t["cell"]} for t in group]})
    record = {"schema_version": SCHEMA_VERSION, "frames_json": str(index_path), "frames_dir": str(frames_dir),
              "frame_set_id": meta.get("frame_set_id"), "sheets_dir": str(sheet_dir),
              "label_format": "#INDEX TIME - the frame's index in frames.json and its time in the media",
              "note": SEEN_NOTE, "sheets": sheets}
    sheets_json = out_dir / "sheets.json"
    sheets_json.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"sheets_json": str(sheets_json), "sheets": [str(sheet_dir / s["file"]) for s in sheets],
                      "frames_on_sheets": len(tiles), "tile": {"width": tile_w, "height": tile_h},
                      "note": SEEN_NOTE}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
