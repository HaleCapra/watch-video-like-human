#!/usr/bin/env python3
"""Record authorized browser/desktop playback with ffmpeg.

This is a thin, explicit wrapper around normal OS capture APIs. It does not
bypass DRM, anti-recording controls, or other platform protections.
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
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path


def decode_output(data) -> str:
    """Decode child-process output without trusting the console code page.

    ffmpeg emits UTF-8 even on a Chinese Windows console (cp936 / GBK). Decoding that with the
    locale codec turns device names such as a Chinese-named microphone or Stereo Mix into
    mojibake, which then cannot be matched, passed back to dshow, or printed.
    """
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        import locale
        return data.decode(locale.getpreferredencoding(False) or "utf-8", errors="replace")


def safe_stdio() -> None:
    """Never let a character the console cannot encode crash the script (cp936, cp1252, ...)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass


def require_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg was not found on PATH.")
    return ffmpeg


def resolve_platform(requested: str) -> str:
    if requested != "auto":
        return requested

    current = platform.system().lower()
    if current == "windows":
        return "windows"
    if current == "darwin":
        return "macos"
    if current == "linux":
        return "linux"
    raise SystemExit(f"Unsupported operating system: {platform.system()}")


def listing_exit_code(returncode: int, listing: str) -> int:
    """Exit code for --list-devices.

    ffmpeg was given no real input, so after printing the devices it always ends with an error of
    its own: 1 on older builds, 251 on macOS with newer ones (field test). The printed list is the
    result: when it is there, this is a success. Only a run that printed no list keeps ffmpeg's code.
    """
    listed = re.search(r"AVFoundation (video|audio) devices|DirectShow (video|audio) devices|\((audio|video)\)", listing)
    if returncode in (0, 1) or listed:
        return 0
    return returncode


def list_devices(ffmpeg: str, target: str) -> int:
    if target == "windows":
        print("Windows DirectShow devices (choose an audio device if needed):", file=sys.stderr)
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-list_devices",
            "true",
            "-f",
            "dshow",
            "-i",
            "dummy",
        ]
        proc = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL)
        listing = decode_output(proc.stdout) + decode_output(proc.stderr)
        print(listing, file=sys.stderr)
        return listing_exit_code(proc.returncode, listing)

    if target == "macos":
        print("macOS AVFoundation devices (note the screen and audio indexes):", file=sys.stderr)
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-f",
            "avfoundation",
            "-list_devices",
            "true",
            "-i",
            "",
        ]
        proc = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL)
        listing = decode_output(proc.stdout) + decode_output(proc.stderr)
        print(listing, file=sys.stderr)
        return listing_exit_code(proc.returncode, listing)

    display = os.environ.get("DISPLAY")
    print(f"Linux screen display: {display}" if display else
          "Linux screen display: no DISPLAY is set - this process has no X screen to capture", file=sys.stderr)
    pactl = shutil.which("pactl")
    if pactl:
        print("PulseAudio/PipeWire-compatible audio sources:", file=sys.stderr)
        return subprocess.run([pactl, "list", "short", "sources"], stdin=subprocess.DEVNULL).returncode

    print(
        "pactl was not found. Install PulseAudio utilities or provide a known "
        "source with --audio-device.",
        file=sys.stderr,
    )
    return 0


_INPUT_QUEUE_OK: dict = {}


def input_thread_queue_supported(ffmpeg: str) -> bool:
    """Does this ffmpeg still take -thread_queue_size as an INPUT option?

    ffmpeg 9 made it a muxer (output) option only: given before -i it stops the whole command
    with "cannot be applied to input url" (measured with 9.1, exit 234). Ask the binary once,
    with a parse-only run on a synthetic source, instead of guessing from the version string.
    """
    if ffmpeg not in _INPUT_QUEUE_OK:
        try:
            proc = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-thread_queue_size", "1024",
                                   "-f", "lavfi", "-i", "anullsrc", "-t", "0.05", "-f", "null", "-"],
                                  capture_output=True, timeout=20, stdin=subprocess.DEVNULL)
            _INPUT_QUEUE_OK[ffmpeg] = proc.returncode == 0
        except (OSError, subprocess.SubprocessError):
            _INPUT_QUEUE_OK[ffmpeg] = False
    return _INPUT_QUEUE_OK[ffmpeg]


def add_live_input(cmd: list[str], *parts: str) -> None:
    if cmd and input_thread_queue_supported(cmd[0]):
        cmd += ["-thread_queue_size", "1024"]
    cmd += [*parts]


# ------------------------------------------------------------- macOS AVFoundation devices

def parse_avfoundation(blob: str) -> dict:
    """{"video": [(index, name)], "audio": [(index, name)]} from an AVFoundation device listing."""
    table: dict = {"video": [], "audio": []}
    section = None
    for line in blob.splitlines():
        if "AVFoundation video devices" in line:
            section = "video"
        elif "AVFoundation audio devices" in line:
            section = "audio"
        elif section:
            m = re.search(r"\]\s*\[(\d+)\]\s*(.+)", line)
            if m:
                name = re.sub(r"\s*\[(?:uid|serial):[^\]]*\]", "", m.group(2)).strip()
                table[section].append((int(m.group(1)), name))
    return table


def macos_device_table(ffmpeg: str) -> dict:
    """Current AVFoundation devices as {"video": [(index, name)], "audio": [(index, name)]}.

    Indexes are NOT stable: a Continuity Camera iPhone coming into or out of range, or a newly
    installed virtual device, renumbers the list within minutes (measured: "Capture screen 0"
    moved from 2 to 1 between preflight and recording). Always resolve right before use.
    """
    try:
        proc = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                              capture_output=True, timeout=25, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return {"video": [], "audio": []}
    return parse_avfoundation(decode_output(proc.stdout) + decode_output(proc.stderr))


def resolve_macos_device(table: dict, kind: str, wanted: str | None) -> tuple[int | None, str | None, str]:
    """Turn 'auto', a name (substring, case-insensitive) or an index into (index, name, how)."""
    entries = table.get(kind, [])
    if wanted in (None, "", "auto"):
        if kind == "video":
            hits = [e for e in entries if e[1].lower().startswith("capture screen")]
        else:
            hits = [e for e in entries if any(h in e[1].lower() for h in LOOPBACK_HINTS["macos"])]
        return (hits[0][0], hits[0][1], "auto") if hits else (None, None, "auto")
    wanted = re.sub(r"\s*\[(?:uid|serial):[^\]]*\]", "", str(wanted)).strip()   # names as ffmpeg lists them
    if str(wanted).isdigit():
        index = int(wanted)
        name = next((n for i, n in entries if i == index), None)
        return (index if name else None), name, "index"
    hits = [e for e in entries if str(wanted).lower() in e[1].lower()]
    return (hits[0][0], hits[0][1], "name") if hits else (None, None, "name")


def resolve_macos_args(ffmpeg: str, args: argparse.Namespace, need_screen: bool = True) -> dict:
    """Resolve --screen-device / --audio-device against the device list as it is NOW.

    Rewrites args.screen_device and args.audio_device to current numeric indexes and returns
    what was chosen, so the caller can show it. Raises SystemExit with the current list when
    something cannot be found - never falls through to a wrong device.
    """
    table = macos_device_table(ffmpeg)
    listing = "\n".join([f"  video [{i}] {n}" for i, n in table["video"]]
                        + [f"  audio [{i}] {n}" for i, n in table["audio"]]) or "  (ffmpeg listed no devices)"
    chosen: dict = {"screen": None, "audio": None}
    if need_screen:
        index, name, how = resolve_macos_device(table, "video", args.screen_device)
        if (index is None and getattr(args, "dry_run", False) and not table["video"]
                and str(args.screen_device).isdigit()):
            index, name, how = int(args.screen_device), "(not listed: planning on another machine)", "index"
        if index is None:
            raise SystemExit(f"macOS screen device {args.screen_device or 'auto'!r} not found. Current devices:\n{listing}")
        if "capture screen" not in (name or "").lower():
            print(f"WARNING: video device [{index}] is {name!r}, which is a camera, not a screen.", file=sys.stderr)
        chosen["screen"] = {"index": index, "name": name, "resolved_by": how}
        args.screen_device = str(index)
    if args.audio_device:
        index, name, how = resolve_macos_device(table, "audio", args.audio_device)
        if index is None:
            if args.audio_device == "auto":
                args.audio_device = None
            else:
                raise SystemExit(f"macOS audio device {args.audio_device!r} not found. Current devices:\n{listing}")
        else:
            if not any(h in (name or "").lower() for h in LOOPBACK_HINTS["macos"]):
                print(f"WARNING: audio device [{index}] is {name!r}, not a loopback device: it records "
                      "the room through a microphone, not the video's sound.", file=sys.stderr)
            chosen["audio"] = {"index": index, "name": name, "resolved_by": how}
            args.audio_device = str(index)
    return chosen


def responsible_app_chain() -> list[str]:
    """The .app bundles above this process, nearest first.

    macOS grants Screen Recording to the *responsible* app, which is not always the one in the
    Dock: in a desktop agent app the agent's commands can run under a bundled command-line
    helper that has its own row in System Settings (often the app's name in lower case).
    """
    apps: list[str] = []
    pid = os.getpid()
    for _ in range(12):
        try:
            out = decode_output(subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(pid)],
                                               capture_output=True, timeout=5, stdin=subprocess.DEVNULL).stdout).strip()
        except (OSError, subprocess.SubprocessError):
            break
        if not out:
            break
        parts = out.split(None, 1)
        comm = parts[1] if len(parts) > 1 else ""
        m = re.search(r"([^/]+)\.app/", comm)
        if m and m.group(1) not in apps:
            apps.append(m.group(1))
        try:
            pid = int(parts[0])
        except ValueError:
            break
        if pid <= 1:
            break
    return apps


MACOS_PERMISSION_HELP = """The screen could not be opened within {seconds:g} s. On macOS that almost always means Screen
Recording permission is missing: ffmpeg does not fail, it waits forever.

  System Settings > Privacy & Security > Screen & System Audio Recording
  (系统设置 > 隐私与安全性 > 录屏与系统录音)

Turn on the app that RUNS this command{apps}. Inside a desktop agent app that is the row of its
command-line helper (the same name in lower case), not the app's own row. If macOS offers
"Quit & Reopen", choosing Later is fine: the permission applied without a restart when tested.
Then run this again."""

MACOS_PICKER_NOTE = ("macOS 15+ may now show a dialog: '\"ffmpeg\" is requesting to bypass the system private "
                     "window picker and directly access your screen and audio' (“ffmpeg”正在请求绕过系统"
                     "无痕浏览窗口选择器). Capture does NOT wait for it - click Allow now, before the real "
                     "recording, or the dialog ends up in the middle of the picture.")


def macos_screen_probe(ffmpeg: str, screen_index: str, seconds: float = 12.0) -> dict:
    """Open the screen for a moment, with a timeout, before a real-time recording depends on it."""
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "avfoundation", "-framerate", "15",
           "-i", f"{screen_index}:none", "-frames:v", "2", "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=seconds, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "timeout", "responsible_apps": responsible_app_chain()}
    except OSError as exc:
        return {"ok": False, "reason": str(exc)}
    if proc.returncode != 0:
        return {"ok": False, "reason": (decode_output(proc.stderr).strip().splitlines() or ["ffmpeg failed"])[-1]}
    return {"ok": True}


def macos_output_state() -> dict:
    """Where system sound is going right now, and whether it is muted. Best effort, never raises."""
    state: dict = {"default_output": None, "muted": None, "volume": None}
    try:
        out = decode_output(subprocess.run(["system_profiler", "SPAudioDataType"], capture_output=True,
                                           timeout=20, stdin=subprocess.DEVNULL).stdout)
        name = None
        for line in out.splitlines():
            m = re.match(r"^\s{8}(\S.*):\s*$", line)
            if m:
                name = m.group(1)
            elif "Default Output Device: Yes" in line:
                state["default_output"] = name
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        out = decode_output(subprocess.run(["osascript", "-e", "get volume settings"], capture_output=True,
                                           timeout=10, stdin=subprocess.DEVNULL).stdout)
        m = re.search(r"output muted:(true|false)", out)
        if m:
            state["muted"] = m.group(1) == "true"
        m = re.search(r"output volume:(\d+)", out)
        if m:
            state["volume"] = int(m.group(1))
    except (OSError, subprocess.SubprocessError):
        pass
    return state


def build_windows_input(args: argparse.Namespace, cmd: list[str]) -> tuple[str, str | None]:
    capture = ["-f", "gdigrab", "-framerate", str(args.framerate)]
    if args.hide_cursor:
        capture += ["-draw_mouse", "0"]
    if args.offset_x is not None:
        capture += ["-offset_x", str(args.offset_x)]
    if args.offset_y is not None:
        capture += ["-offset_y", str(args.offset_y)]
    if args.video_size:
        capture += ["-video_size", args.video_size]
    add_live_input(cmd, *capture, "-i", "desktop")

    if not args.audio_device:
        return "0:v:0", None

    add_live_input(cmd, "-f", "dshow", "-i", f"audio={args.audio_device}")
    return "0:v:0", "1:a:0"


def build_macos_input(args: argparse.Namespace, cmd: list[str]) -> tuple[str, str | None]:
    if args.offset_x is not None or args.offset_y is not None:
        raise SystemExit("macOS AVFoundation capture does not support --offset-x/--offset-y here.")
    if args.screen_device is None or not str(args.screen_device).isdigit():
        raise SystemExit("macOS screen device was not resolved; pass --screen-device auto, a name or an index.")

    capture = ["-f", "avfoundation", "-framerate", str(args.framerate)]
    if args.video_size:
        capture += ["-video_size", args.video_size]
    capture += ["-capture_cursor", "0" if args.hide_cursor else "1"]

    audio_device = args.audio_device or "none"
    add_live_input(cmd, *capture, "-i", f"{args.screen_device}:{audio_device}")
    return "0:v:0", "0:a:0" if args.audio_device else None


WAYLAND_WARNING = """This is a Wayland session (XDG_SESSION_TYPE=wayland or WAYLAND_DISPLAY is set).
x11grab reads the X root window, and under Wayland / rootless XWayland that window is empty:
the recording comes out COMPLETELY BLACK while ffmpeg reports success.

Use one of these instead:
  * The desktop's own recorder (GNOME: Ctrl+Shift+Alt+R; KDE: Spectacle; wlroots: wf-recorder or
    wl-screenrec), then process the resulting file as Route 0.
  * --window-id 0x... to grab ONE X11 client window (find it with `xwininfo`). This works under
    XWayland for X11 apps only; a Wayland-native browser window cannot be grabbed this way.
  * --force-x11 if you know a real X server is serving this display (for example Xvfb or Xorg).
The post-recording check will still fail the run if the picture is black."""


def linux_session() -> dict:
    """What kind of display this Linux process can see. Pure environment reads."""
    env = os.environ
    wayland = env.get("XDG_SESSION_TYPE", "").strip().lower() == "wayland" or bool(env.get("WAYLAND_DISPLAY"))
    return {"display": env.get("DISPLAY") or None, "wayland": wayland}


def detect_x11_size(display: str) -> str | None:
    """Screen size as WIDTHxHEIGHT from xdpyinfo or xrandr, or None when neither can tell."""
    probes = (("xdpyinfo", ["-display", display], r"dimensions:\s*(\d+)x(\d+)"),
              ("xrandr", ["--display", display, "--current"], r"current\s+(\d+)\s*x\s*(\d+)"))
    for tool, extra, pattern in probes:
        binary = shutil.which(tool)
        if not binary:
            continue
        try:
            proc = subprocess.run([binary, *extra], capture_output=True, timeout=10, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            continue
        match = re.search(pattern, decode_output(proc.stdout))
        if match:
            return f"{match.group(1)}x{match.group(2)}"
    return None


def build_linux_input(args: argparse.Namespace, cmd: list[str]) -> tuple[str, str | None]:
    session = linux_session()
    display = args.display or session["display"]
    if not display:
        raise SystemExit(
            "No X display: DISPLAY is not set and --display was not given, so there is no screen "
            "this process can capture.\n"
            + ("This looks like a Wayland-only session.\n\n" + WAYLAND_WARNING if session["wayland"] else
               "A headless shell, container or SSH session cannot run Route C. Run it inside the "
               "desktop session that is showing the video, or pass --display explicitly.")
        )
    window_id = getattr(args, "window_id", None)
    if session["wayland"] and not window_id and not getattr(args, "force_x11", False):
        if not args.dry_run:
            raise SystemExit(WAYLAND_WARNING)
        print("WARNING: " + WAYLAND_WARNING + "\n", file=sys.stderr)

    video_size = args.video_size
    if not video_size and not window_id:
        video_size = detect_x11_size(display)
        if not video_size:
            raise SystemExit("Linux x11grab capture needs --video-size, for example 1920x1080 "
                             "(xdpyinfo / xrandr were not available to detect it).")
        print(f"Detected screen size {video_size} on {display}.", file=sys.stderr)

    offset_x = args.offset_x or 0
    offset_y = args.offset_y or 0
    capture = ["-f", "x11grab", "-framerate", str(args.framerate)]
    if video_size:
        capture += ["-video_size", video_size]
    if window_id:
        capture += ["-window_id", str(window_id)]
    if args.hide_cursor:
        capture += ["-draw_mouse", "0"]
    add_live_input(cmd, *capture, "-i", f"{display}+{offset_x},{offset_y}")

    if not args.audio_device:
        return "0:v:0", None

    add_live_input(cmd, "-f", "pulse", "-i", args.audio_device)
    return "0:v:0", "1:a:0"


def build_command(args: argparse.Namespace, ffmpeg: str, target: str) -> list[str]:
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    cmd = [ffmpeg, "-y", "-hide_banner"]

    if target == "windows":
        video_stream, audio_stream = build_windows_input(args, cmd)
    elif target == "macos":
        video_stream, audio_stream = build_macos_input(args, cmd)
    else:
        video_stream, audio_stream = build_linux_input(args, cmd)

    if args.duration:
        cmd += ["-t", str(args.duration)]

    cmd += ["-map", video_stream]
    if audio_stream:
        cmd += ["-map", audio_stream, "-c:a", "aac", "-b:a", args.audio_bitrate]
    scale = effective_scale(args, target)
    if scale:
        # Only ever scale DOWN: a 3360x2100 Retina capture costs 4x the encode and decode work
        # of 1920 wide and the frames are reduced to 512-1024 px afterwards anyway.
        cmd += ["-vf", f"scale='min({scale},iw)':-2"]

    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        args.preset,
        "-crf",
        str(args.crf),
        "-pix_fmt",
        "yuv420p",
        str(output),
    ]
    return cmd


def effective_scale(args: argparse.Namespace, target: str) -> int:
    """--scale as given; otherwise 1920 wide on macOS (Retina) and the native size elsewhere."""
    wanted = getattr(args, "scale", None)
    if wanted is not None:
        return max(int(wanted), 0)
    return 1920 if target == "macos" else 0


def format_command(cmd: list[str], target: str) -> str:
    if target == "windows":
        return subprocess.list2cmdline(cmd)
    return shlex.join(cmd)


# --------------------------------------------------------------- loopback audio

LOOPBACK_HINTS = {
    "macos": ["blackhole", "loopback", "soundflower", "existential audio", "aggregate"],
    "windows": ["stereo mix", "立体声混音", "vb-audio", "cable output", "voicemeeter",
                "virtual-audio-capturer", "what u hear", "wave out mix"],
    "linux": [".monitor"],
}

INSTALL_HINTS = {
    "macos": ("Install BlackHole:  brew install blackhole-2ch\n"
              "  Then open Audio MIDI Setup and create a Multi-Output Device containing both\n"
              "  BlackHole and your speakers, so you can still hear the video while it records."),
    "windows": ("Install VB-CABLE from vb-audio.com/Cable (preferred), or enable 'Stereo Mix' in\n"
                "  Sound settings > Recording > (right-click) Show Disabled Devices.\n"
                "  WARNING: the VB-CABLE installer makes 'CABLE Input' the system default output, so\n"
                "  the speakers go silent. Right after installing, set the speakers back as the\n"
                "  default in Settings > System > Sound, then route only the browser to\n"
                "  'CABLE Input' in Volume mixer."),
    "linux": ("PulseAudio/PipeWire monitor sources (names ending in .monitor) are normally present;\n"
              "  list them with `pactl list short sources`. If `pactl` itself is missing, install\n"
              "  pulseaudio-utils (Debian/Ubuntu) or the pipewire-pulse package of your distribution.\n"
              "  Do not use `default`: the default SOURCE is the microphone, not what you hear."),
}
NOT_A_MONITOR = ("WARNING: {device!r} is not a .monitor source. On PulseAudio/PipeWire a non-monitor source "
                 "is an input such as the microphone, so this would record the room, not the video - and "
                 "still read as 'signal present'. Use --audio-device auto or a name ending in .monitor.")


def is_linux_non_monitor(target: str, device: str | None) -> bool:
    return bool(target == "linux" and device and device != "auto" and not device.endswith(".monitor"))


def parse_audio_devices(target: str, blob: str) -> list[str]:
    if target == "windows":
        devices = re.findall(r'"([^"]+)"\s+\(audio\)', blob)
    elif target == "macos":
        audio_section = blob.split("AVFoundation audio devices:", 1)
        section = audio_section[1] if len(audio_section) == 2 else ""
        devices = re.findall(r"\[\d+\]\s*(.+)", section)
    else:
        devices = []
    return list(dict.fromkeys(device.strip() for device in devices))


def probe_audio_devices(ffmpeg: str, target: str) -> list[str]:
    """Best-effort device listing, parsed into names. Empty list on any failure."""
    try:
        if target == "linux":
            pactl = shutil.which("pactl")
            if not pactl:
                return []
            out = decode_output(subprocess.run([pactl, "list", "short", "sources"],
                                               capture_output=True, timeout=15, stdin=subprocess.DEVNULL).stdout)
            names = [ln.split("\t")[1] for ln in out.splitlines()
                     if "\t" in ln and len(ln.split("\t")) > 1]
            # With several sinks (HDMI, Bluetooth, ...) the monitor that matters is the one of
            # the DEFAULT sink - that is where the browser is playing. Put it first.
            try:
                default_sink = decode_output(subprocess.run([pactl, "get-default-sink"], capture_output=True,
                                                            timeout=10, stdin=subprocess.DEVNULL).stdout).strip()
            except (OSError, subprocess.SubprocessError):
                default_sink = ""
            preferred = f"{default_sink}.monitor"
            if default_sink and preferred in names:
                names.remove(preferred)
                names.insert(0, preferred)
            return names

        if target == "macos":
            cmd = [ffmpeg, "-hide_banner", "-nostdin", "-f", "avfoundation", "-list_devices", "true", "-i", ""]
        else:
            cmd = [ffmpeg, "-hide_banner", "-nostdin", "-list_devices", "true", "-f", "dshow", "-i", "dummy"]
        proc = subprocess.run(cmd, capture_output=True, timeout=25, stdin=subprocess.DEVNULL)
        blob = decode_output(proc.stdout) + decode_output(proc.stderr)
        return parse_audio_devices(target, blob)
    except (OSError, subprocess.SubprocessError):
        return []


def find_loopback(target: str, devices: list[str]) -> list[str]:
    hints = LOOPBACK_HINTS.get(target, [])
    return [d for d in devices if any(h in d.lower() for h in hints)]


def check_audio(ffmpeg: str, target: str) -> int:
    devices = probe_audio_devices(ffmpeg, target)
    loop = find_loopback(target, devices)
    print(f"Platform: {target}   devices detected: {len(devices)}", file=sys.stderr)
    if loop:
        print("\nLoopback device(s) found - Tier C can capture what you HEAR:", file=sys.stderr)
        for d in loop:
            print(f"  * {d}", file=sys.stderr)
        print("\nPass one with --audio-device, or use --audio-device auto.", file=sys.stderr)
        # ASCII-only JSON: names survive as \uXXXX escapes whatever the console code page is.
        print(json.dumps({"loopback": loop, "all": devices}))
        return 0

    print("\nNo loopback device found. A recording made now would be SILENT VIDEO ONLY,", file=sys.stderr)
    print("which caps the honest verdict at 'Frames only' - no audio evidence at all.\n", file=sys.stderr)
    print(INSTALL_HINTS.get(target, ""), file=sys.stderr)
    print(json.dumps({"loopback": [], "all": devices}))
    return 1


SILENT_CHECKLIST = """Nothing is reaching the loopback device. Check these, in this order:

  1. Is the video actually playing right now? Run this test WHILE audio is playing.
  2. Is the player muted, or its volume at zero? Player volume is applied before the
     audio ever leaves the tab.
  3. Is the browser tab muted? (Chrome: right-click the tab > Unmute site)
     Telltale sign on Windows: the browser is MISSING from Settings > System > Sound >
     Volume mixer while the video plays. A muted tab opens no audio session at all, so
     there is nothing to route. Page scripts cannot see tab mute (video.muted stays false).
  4. Is system output actually routed into the loopback device?
       Windows : Settings > System > Sound > Volume mixer > set the browser's output
                 device to "CABLE Input". Routing the browser alone - rather than the
                 whole system - lets you drop your speaker volume without silencing
                 the recording.
       macOS   : select the Multi-Output Device (BlackHole + speakers) as the output.
       Linux   : is the player on the sink whose monitor you record? Check with
                 `pactl list short sink-inputs` and `pactl get-default-sink`. On PulseAudio the
                 sink's volume and mute DO reach the monitor: a muted sink records silence and
                 a sink at 20% records about 40 dB lower. Unmute it and raise it to 100%.
  5. Windows + Stereo Mix only: Stereo Mix taps the post-volume output mix on most
     drivers, so the master volume slider DOES silence the recording. VB-CABLE does not
     have this problem - prefer it (measured: master volume 80 vs 0 moved the VB-CABLE
     reading by less than 1 dB)."""


def parse_volume(blob: str) -> dict:
    out = {}
    for key in ("mean_volume", "max_volume"):
        m = re.search(rf"{key}:\s*(-?(?:[\d.]+|inf)) dB", blob, flags=re.I)
        if m:
            out[key] = float(m.group(1))
    return out


def audio_input_args(target: str, device: str) -> list[str]:
    if target == "windows":
        return ["-f", "dshow", "-i", f"audio={device}"]
    if target == "macos":
        return ["-f", "avfoundation", "-i", f":{device}"]
    return ["-f", "pulse", "-i", device]


def test_audio(ffmpeg: str, target: str, device: str | None, seconds: float) -> int:
    """Record a few seconds and measure the level.

    Device presence is not signal presence. Without this you discover a muted player
    only after recording the whole video in real time - the one failure whose cost is
    measured in minutes.
    """
    if not device or device == "auto":
        found = find_loopback(target, probe_audio_devices(ffmpeg, target))
        if not found:
            print("No loopback device found.\n\n" + INSTALL_HINTS.get(target, ""), file=sys.stderr)
            print(json.dumps({"ok": False, "reason": "no_loopback_device"}))
            return 1
        device = found[0]
    if target == "macos":
        index, name, _how = resolve_macos_device(macos_device_table(ffmpeg), "audio", device)
        if index is None:
            print(f"macOS audio device {device!r} not found. Run --list-devices.", file=sys.stderr)
            print(json.dumps({"ok": False, "reason": "device_not_found", "device": device}))
            return 1
        print(f"macOS audio device [{index}] {name}", file=sys.stderr)
        device = str(index)

    not_monitor = is_linux_non_monitor(target, device)
    if not_monitor:
        print(NOT_A_MONITOR.format(device=device) + "\n", file=sys.stderr)
    print(f"Recording {seconds:g}s from {device!r} to measure the level.", file=sys.stderr)
    print("Make sure the video is PLAYING right now.\n", file=sys.stderr)

    cmd = [ffmpeg, "-hide_banner", "-nostdin", *audio_input_args(target, device),
           "-t", str(seconds), "-af", "volumedetect", "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=seconds + 30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Could not open the device: {exc}", file=sys.stderr)
        print(json.dumps({"ok": False, "reason": "device_open_failed", "device": device}))
        return 1

    blob = decode_output(proc.stdout) + decode_output(proc.stderr)
    levels = parse_volume(blob)
    if not levels:
        print("ffmpeg produced no level reading. Raw tail:\n" + blob[-600:], file=sys.stderr)
        print(json.dumps({"ok": False, "reason": "no_level_reading", "device": device}))
        return 1

    mean = levels.get("mean_volume", -91.0)
    peak = levels.get("max_volume", -91.0)
    digital_silence = peak <= -90.0
    too_quiet = not digital_silence and mean <= -60.0
    live = not digital_silence

    print(f"  mean_volume: {mean:.1f} dB", file=sys.stderr)
    print(f"  max_volume:  {peak:.1f} dB", file=sys.stderr)
    if live and not too_quiet:
        print("\nSIGNAL PRESENT - this device is capturing audio. Route C can reach "
              "'transcribed' audio evidence.", file=sys.stderr)
    elif too_quiet:
        print("\nSIGNAL PRESENT BUT VERY QUIET - audio is flowing, but transcription may be "
              "unreliable until the source level is raised or the recording is amplified.",
              file=sys.stderr)
    else:
        print("\nSILENT (a true digital silence reads about -91 dB).\n", file=sys.stderr)
        print(SILENT_CHECKLIST, file=sys.stderr)

    result = {"ok": live, "device": device, "mean_db": mean, "max_db": peak,
              "seconds": seconds,
              "status": "digital_silence" if digital_silence else
                        "too_quiet" if too_quiet else "signal_present",
              "transcription_ready": live and not too_quiet}
    if not_monitor:
        # Signal is present, but it is the microphone's: callers that only read the exit code or
        # "ok" must not take this for a working loopback.
        result["warning"] = "not_a_monitor_source"
        result["transcription_ready"] = False
        result["ok"] = False
        result["signal_present"] = live
    print(json.dumps(result))
    return 0 if (live and not not_monitor) else 1


# --------------------------------------------------------------- post-recording self-check

CHECK_FRACTIONS = (0.1, 0.35, 0.65, 0.9)   # spread out: a window that covers the player later is seen too
BRIGHT_UI_LUMA = 180.0                     # video is rarely this bright on average; an app window often is
BLACK_YMAX = 40.0   # limited-range black is 16; anything this dark everywhere is a black frame
BLACK_YAVG = 24.0
# YMAX is the single brightest pixel: a mouse pointer on an otherwise black capture reads 186 and
# the frame used to pass as "has picture" (field test on Linux; gdigrab draws the pointer too).
# YHIGH is the 90th-percentile luma, which a pointer, a clock or a small dialog cannot move.
BLACK_YHIGH = 40.0


def is_black_frame(stats: dict) -> bool:
    bright = stats["YHIGH"] if "YHIGH" in stats else stats.get("YMAX", 0.0)
    return stats["YAVG"] <= BLACK_YAVG and bright <= (BLACK_YHIGH if "YHIGH" in stats else BLACK_YMAX)


def parse_signalstats(blob: str) -> list[dict]:
    frames: list[dict] = []
    for line in blob.splitlines():
        for key in ("YAVG", "YHIGH", "YMAX"):
            match = re.search(rf"lavfi\.signalstats\.{key}=([\d.]+)", line)
            if match:
                if key == "YAVG" or not frames:
                    frames.append({})
                frames[-1][key] = float(match.group(1))
    return [f for f in frames if "YAVG" in f]


def media_duration(output: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        proc = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                               "-of", "default=noprint_wrappers=1:nokey=1", str(output)],
                              capture_output=True, timeout=30, stdin=subprocess.DEVNULL)
        return float(decode_output(proc.stdout).strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def post_record_check(ffmpeg: str, output: Path, expect_audio: bool, samples: int = 8) -> dict:
    """Look at what was actually recorded before anyone trusts it.

    A recording can succeed and still be useless: a black picture (DRM, Wayland, a protected
    surface), a silent audio track, or - worst because nothing can detect it automatically -
    a perfectly good picture of the WRONG WINDOW. This samples frames for black, measures the
    audio level, and writes check frames that the agent must open and look at.
    """
    duration = media_duration(output)
    step = max((duration or 40.0) / samples, 0.5)
    graph = (f"select='isnan(prev_selected_t)+gte(t-prev_selected_t,{step:.3f})',"
             "signalstats,metadata=mode=print")
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-i", str(output), "-vf", graph, "-an", "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=600, stdin=subprocess.DEVNULL)
        stats = parse_signalstats(decode_output(proc.stdout) + decode_output(proc.stderr))
    except (OSError, subprocess.SubprocessError):
        stats = []
    black = [f for f in stats if is_black_frame(f)]
    if not stats:
        video = "no_frames"
    elif len(black) == len(stats):
        video = "black"
    elif black:
        video = "partly_black"
    else:
        video = "has_picture"

    audio = "none"
    levels: dict = {}
    if expect_audio:
        try:
            proc = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", str(output), "-vn",
                                   "-af", "volumedetect", "-f", "null", "-"], capture_output=True, timeout=600,
                                   stdin=subprocess.DEVNULL)
            levels = parse_volume(decode_output(proc.stdout) + decode_output(proc.stderr))
        except (OSError, subprocess.SubprocessError):
            levels = {}
        if not levels:
            audio = "no_audio_track"
        elif levels.get("max_volume", -91.0) <= -90.0:
            audio = "digital_silence"
        elif levels.get("mean_volume", -91.0) <= -60.0:
            audio = "too_quiet"
        else:
            audio = "signal_present"

    check_frames = []
    if video not in ("no_frames",) and duration:
        for n, fraction in enumerate(CHECK_FRACTIONS, start=1):
            target_path = output.with_name(f"{output.stem}.check-{n}.jpg")
            try:
                subprocess.run([ffmpeg, "-y", "-hide_banner", "-nostdin", "-ss", f"{duration * fraction:.3f}",
                                "-i", str(output), "-frames:v", "1", "-vf", "scale=960:-2", "-q:v", "3",
                                str(target_path)], capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                continue
            if target_path.is_file():
                check_frames.append(str(target_path))

    ok = video in ("has_picture", "partly_black") and audio not in ("digital_silence", "no_audio_track")
    report = {"output": str(output), "duration_seconds": duration, "ok": ok, "video": video,
              "frames_sampled": len(stats), "black_frames": len(black),
              "mean_luma": round(sum(f["YAVG"] for f in stats) / len(stats), 2) if stats else None,
              "audio": audio, "mean_db": levels.get("mean_volume"), "max_db": levels.get("max_volume"),
              "check_frames": check_frames,
              "check_frame_times": [round(duration * f, 1) for f in CHECK_FRACTIONS] if duration and check_frames else [],
              "next": ("OPEN EVERY check frame and confirm each shows the VIDEO, not another window, a "
                       "dialog or the desktop, before extracting anything. A black-frame test cannot "
                       "tell the right picture from the wrong one. If only some of them show the video, "
                       "only that stretch of the recording is evidence.")}
    if report["mean_luma"] is not None and report["mean_luma"] >= BRIGHT_UI_LUMA:
        report["hint"] = (f"mean brightness {report['mean_luma']} is unusually high for video and typical of "
                          "an application window (a chat app, a settings page, a white web page). "
                          "This is a hint, not a verdict: look at the check frames.")
    return report


def save_post_check(report: dict, output: Path) -> None:
    """Keep the check beside the recording so it can be registered in the evidence manifest."""
    target_path = output.with_name(output.stem + ".postcheck.json")
    try:
        target_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        report["report_file"] = str(target_path)
    except OSError:
        pass


HUMAN_CHECKLIST = [
    "The player is full screen and stays in front for the whole recording.",
    "A person is at the machine to put it there; nobody uses the computer until it ends.",
    "Exactly one player is playing (list every video/audio element before and after).",
    "The seconds between starting the recording and the video starting to play are noted.",
    "The agent's own app window is minimised or on another screen, and the agent does not end its "
    "turn, post a message or open a dialog until the recording is over: the app coming to the front "
    "covers the player even when nobody touches the computer. Notifications are silenced (Do Not "
    "Disturb / Focus): a minimised app still puts its toasts on the screen.",
    "macOS: the app running this command has Screen Recording permission, any 'bypass the window "
    "picker' dialog has been answered, and the sound output is an UNMUTED Multi-Output Device.",
]


def windows_screen() -> dict:
    """Physical size of the primary screen and its scaling, through user32. Empty on failure."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        logical = (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
        user32.SetProcessDPIAware()
        physical = (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
        scale = round(physical[0] / logical[0] * 100) if logical[0] else None
        return {"size": f"{physical[0]}x{physical[1]}", "scale_percent": scale,
                "note": "gdigrab records the whole primary desktop at this size"}
    except Exception:  # noqa: BLE001 - information only
        return {}


OPENING_SILENCE_SLACK = 0.5   # a silence that begins within half a second counts as "silent from the start"
SILENCE_RE = re.compile(r"silence_(start|end):\s*(-?[\d.]+)")


OPENING_SILENCE_SLACK = 0.5   # a silence that begins within half a second counts as "silent from the start"
SILENCE_RE = re.compile(r"silence_(start|end):\s*(-?[\d.]+)")


def preflight(ffmpeg: str, target: str, args: argparse.Namespace) -> dict:
    """Everything that can be known before a real-time recording is started. Records nothing."""
    blockers: list[str] = []
    warnings: list[str] = []
    screen: dict = {}
    if target == "linux":
        session = linux_session()
        display = args.display or session.get("display")
        screen = {"display": display, "wayland": session.get("wayland"),
                  "size": args.video_size or (detect_x11_size(display) if display else None)}
        if not display:
            blockers.append("DISPLAY is not set: this process has no screen to capture.")
        elif session.get("wayland") and not (args.window_id or args.force_x11):
            blockers.append("Wayland session: capturing the root window records a black picture. "
                            "Use --window-id, the desktop's own recorder (then Route 0), or --force-x11 "
                            "when a real X server owns the display.")
    elif target == "macos":
        table = macos_device_table(ffmpeg)
        index, name, how = resolve_macos_device(table, "video", args.screen_device)
        screen = {"index": index, "name": name, "resolved_by": how,
                  "video_devices": [f"[{i}] {n}" for i, n in table["video"]]}
        if index is None:
            blockers.append(f"Screen device {args.screen_device or 'auto'!r} not found among the AVFoundation devices.")
        elif not getattr(args, "skip_screen_probe", False):
            probe = macos_screen_probe(ffmpeg, str(index))
            screen["open_test"] = probe
            if not probe["ok"] and probe.get("reason") == "timeout":
                apps = probe.get("responsible_apps") or []
                blockers.append("The screen could not be opened: Screen Recording permission is probably missing"
                                + (f" for {apps[0]!r}" if apps else "") + ". See System Settings > Privacy & "
                                "Security > Screen & System Audio Recording; inside a desktop agent app enable "
                                "the row of its command-line helper (the same name in lower case). Without "
                                "the permission ffmpeg waits forever instead of failing.")
            elif not probe["ok"]:
                blockers.append(f"The screen could not be opened: {probe.get('reason')}")
        warnings.append("Device indexes change when a Continuity Camera or virtual device appears or leaves; "
                        "pass names or 'auto' rather than numbers, and they are resolved again at record time.")
        warnings.append(MACOS_PICKER_NOTE)
        out_state = macos_output_state()
        screen["system_output"] = out_state
        default_out = (out_state.get("default_output") or "")
        if default_out and not any(h in default_out.lower() for h in ("blackhole", "multi", "多输出", "多重输出", "loopback", "aggregate")):
            warnings.append(f"System sound output is {default_out!r}. Nothing reaches BlackHole until the output "
                            "is a Multi-Output Device that contains it (Audio MIDI Setup); --test-audio will "
                            "read digital_silence.")
        if out_state.get("muted"):
            warnings.append("The current output is MUTED. Unmute it before switching to a Multi-Output Device: "
                            "the volume keys are disabled there, so the loopback records sound nobody can hear.")
        if effective_scale(args, target):
            warnings.append(f"The recording is scaled down to {effective_scale(args, target)} px wide "
                            "(never enlarged). Pass --scale 0 for the full Retina resolution.")
    elif target == "windows":
        screen = windows_screen()
    devices = probe_audio_devices(ffmpeg, target)
    loopback = find_loopback(target, devices)
    selected = args.audio_device if args.audio_device not in (None, "auto") else (loopback[0] if loopback else None)
    if target == "macos" and selected:
        a_index, a_name, _how = resolve_macos_device(macos_device_table(ffmpeg), "audio", selected)
        if a_index is None:
            blockers.append(f"Audio device {selected!r} not found among the AVFoundation devices.")
        else:
            selected = f"[{a_index}] {a_name}"
    if not loopback and not args.audio_device:
        warnings.append("No loopback audio device: only a picture-only recording is possible "
                        "(--allow-silent). The audio channel will be 'none'.")
    if is_linux_non_monitor(target, selected):
        warnings.append(f"{selected!r} is not a .monitor source: it records the microphone, not the video.")
    if target == "windows" and any("cable" in d.lower() for d in loopback):
        warnings.append("VB-CABLE: sound reaches the recording only if the browser plays into 'CABLE "
                        "Input' - either routed alone in Volume mixer, or by making 'CABLE Input' the default "
                        "output for the length of the recording and restoring the previous default (by "
                        "device id) right after. Outside a recording the speakers must be the default. "
                        "Check that the browser tab is not muted.")
    return {"route": "C", "platform": target, "ready": not blockers, "blockers": blockers,
            "warnings": warnings, "screen": screen,
            "audio": {"devices_found": len(devices), "loopback_devices": loopback, "selected": selected,
                      "audio_possible": bool(selected)},
            "person_required": True, "human_checklist": HUMAN_CHECKLIST,
            "cannot_be_checked_here": ["whether the player will be in front", "whether the tab is muted",
                                       "whether playback is DRM-protected (shows only as a black recording)"],
            "next": ["play the video, then run --test-audio to confirm signal is flowing",
                     "record with --duration N --output FILE --early-check 15 (open the early-check frame "
                     "while it records; stop the recording if it is not the video)",
                     "open every check frame the recorder writes before extracting anything"]}


def detect_offset(ffmpeg: str, recorded: Path, noise_db: float = -50.0) -> dict:
    """Where sound first begins in a recording - a starting point for --recording-offset."""
    proc = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", str(recorded), "-vn", "-af",
                           f"silencedetect=noise={noise_db}dB:d=0.3", "-f", "null", "-"],
                          capture_output=True, timeout=900, stdin=subprocess.DEVNULL)
    blob = decode_output(proc.stdout) + decode_output(proc.stderr)
    if "Audio:" not in blob:
        return {"recording": str(recorded), "sound_begins_at": None, "sound_onset": None,
                "reason": "the file has no audio track; measure the offset by eye from the frames"}
    events = [(kind, float(value)) for kind, value in SILENCE_RE.findall(blob)]
    duration = media_duration(recorded)
    begins: float | None
    # silencedetect reports the opening silence a little after zero (measured: silence_start
    # 0.0518542 on a real recording, which the old 0.05 limit missed and reported 0.0).
    if events and events[0][0] == "start" and events[0][1] <= OPENING_SILENCE_SLACK:
        ends = [value for kind, value in events if kind == "end"]
        begins = ends[0] if ends else None       # silent from the start and never broken: no sound at all
        if begins is not None and duration and begins >= duration - 0.05:
            begins = None                        # the "end" of the silence is the end of the file
    else:
        begins = 0.0
    return {"recording": str(recorded), "duration_seconds": duration, "noise_floor_db": noise_db,
            "sound_begins_at": None if begins is None else round(begins, 3),
            "sound_onset": None if begins is None else round(begins, 3),
            "caveat": "This is where SOUND begins, NOT the recording offset, and it errs in both directions: "
                      "a video that opens with silence makes it LATER than where the video begins (measured "
                      "+1.8 s), and a click, a page sound or the player's own start-up noise before playback "
                      "makes it EARLIER (measured -1.3 s).",
            "calibrate": "Take one sentence whose time in the video is known (from captions, or from the "
                         "page), find it in the recording's transcript, and subtract: offset = time in "
                         "recording - time in video. Use sound_onset only as the place to start looking.",
            "use": "align_transcript_frames.py ... --recording-offset SECONDS"}


def explain_post_check(report: dict, target: str) -> None:
    if report["video"] == "black":
        print("\nPOST-RECORDING CHECK FAILED: every sampled frame is BLACK. Nothing was seen.", file=sys.stderr)
        print("Likely causes: DRM / protected playback; "
              + ("a Wayland or rootless XWayland session (see --window-id); " if target == "linux" else "")
              + "hardware-accelerated video on a protected surface; the display was off or locked.\n"
              "Report Route C as blocked for the picture. Do not extract frames from this file.",
              file=sys.stderr)
    elif report["video"] == "no_frames":
        print("\nPOST-RECORDING CHECK FAILED: the file has no readable video frames.", file=sys.stderr)
    elif report["video"] == "partly_black":
        print(f"\nPOST-RECORDING CHECK: {report['black_frames']} of {report['frames_sampled']} sampled "
              "frames are black. Look at the check frames before trusting this recording.", file=sys.stderr)
    if report["audio"] in ("digital_silence", "no_audio_track"):
        print("\nPOST-RECORDING CHECK FAILED: an audio device was given but the recording is silent. "
              "This file supports no audio claim.\n", file=sys.stderr)
        print(SILENT_CHECKLIST, file=sys.stderr)
    elif report["audio"] == "too_quiet":
        print("\nPOST-RECORDING CHECK: audio is present but very quiet; transcription may be unreliable.",
              file=sys.stderr)
    if report["check_frames"]:
        print("\nCheck frames (open them and confirm they show the video):", file=sys.stderr)
        for frame in report["check_frames"]:
            print(f"  {frame}", file=sys.stderr)


def early_check_command(args: argparse.Namespace, ffmpeg: str, target: str, shot: Path) -> list[str]:
    """One still of the same screen area, taken by a second short-lived ffmpeg while the first records."""
    cmd = [ffmpeg, "-y", "-hide_banner", "-nostdin", "-loglevel", "error"]
    if target == "windows":
        cmd += ["-f", "gdigrab"]
        if args.offset_x is not None:
            cmd += ["-offset_x", str(args.offset_x)]
        if args.offset_y is not None:
            cmd += ["-offset_y", str(args.offset_y)]
        if args.video_size:
            cmd += ["-video_size", args.video_size]
        cmd += ["-i", "desktop"]
    elif target == "macos":
        cmd += ["-f", "avfoundation", "-framerate", "15", "-i", f"{args.screen_device}:none"]
    else:
        display = args.display or os.environ.get("DISPLAY")
        if not display:
            raise ValueError("no DISPLAY: nothing to take an early check from")
        cmd += ["-f", "x11grab"]
        if args.video_size:
            cmd += ["-video_size", args.video_size]
        if args.window_id:
            cmd += ["-window_id", str(args.window_id)]
        cmd += ["-i", f"{display}+{args.offset_x or 0},{args.offset_y or 0}"]
    return cmd + ["-frames:v", "1", "-vf", "scale=960:-2", "-q:v", "3", str(shot)]


EARLY_CHILDREN: list = []      # running --early-check captures; they end with the recording
STOP_EXIT_CODES = {"SIGINT": 130, "SIGBREAK": 130, "SIGTERM": 143, "SIGHUP": 129}


STOP_SEEN: list = []            # the first stop request of this run, once there was one
_HANDLERS_BEFORE: dict = {}     # what the stop signals did before a stop request took them over
_JOBS: list = []


def _still_stopping(_number=None, _frame=None) -> None:
    """A further Ctrl+C / Ctrl+Break / SIGTERM / SIGHUP after the first: noted, nothing else."""
    try:
        sys.stderr.write("\nAlready stopping - the file is being finished and checked. Please wait.\n")
        sys.stderr.flush()
    except Exception:      # never let a message break the clean end
        pass


def restore_stop_handlers() -> None:
    """Give the stop signals back what they did before run_recording() kept them (used at the very end)."""
    import signal
    for number, handler in list(_HANDLERS_BEFORE.items()):
        try:
            signal.signal(number, handler if handler is not None else signal.SIG_DFL)
        except (ValueError, OSError):
            pass
    _HANDLERS_BEFORE.clear()
    del STOP_SEEN[:]


def tie_to_this_process(child):
    """Windows: make the system end ffmpeg whenever THIS process ends - however it ends.

    ffmpeg is started outside this console so that keys pressed here cannot reach it. Without this
    tie, closing the console window or killing this process would leave it recording the screen. A job
    object with "kill on close" does it: the job's only handle lives in this process.
    Returns the handle, or None where it could not be done (the caller says so).
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_ulonglong * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        job = kernel.CreateJobObjectW(None, None)
        if not job:
            return None
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000      # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) or \
                not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(int(child._handle))):
            kernel.CloseHandle(job)
            return None
        return job
    except Exception:
        return None


def run_recording(cmd: list[str], grace: float = 20.0) -> tuple[int, str | None]:
    """Run the recording ffmpeg; return (its exit code, the signal that asked for a stop or None).

    A recording must stop when this process is told to stop, and the file must be finished properly
    however often it is told. So this process alone hears the stop signals; ffmpeg is asked once, with
    "q" on a pipe, and never sees a signal or a key itself:

      * macOS / Linux: ffmpeg is started with SIGINT, SIGTERM and SIGHUP blocked. A second Ctrl+C in a
        terminal goes to the whole foreground group, and ffmpeg 8 abandons the end of the file when it
        gets one while finishing (field test: 0 of 5 files playable). It stays in this process group, so
        a SIGKILL to the group still ends it.
      * Windows: ffmpeg runs outside this console (keys pressed here reach every program in a console;
        two within 0.1 s spoiled 12 of 12 files) and is tied to this process, see tie_to_this_process().

    When ffmpeg has not finished `grace` seconds after being asked, it is killed. After a stop request
    every further stop signal is only noted, until restore_stop_handlers() - the exit code stays that of
    the first.
    """
    import signal
    asked: list[str] = []
    previous = {}
    for name in STOP_EXIT_CODES:
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            if signal.getsignal(number) is signal.SIG_IGN:      # nohup, or a background job: leave it ignored
                continue
            previous[number] = signal.signal(number, lambda _n, _f, name=name: asked.append(name))
        except (ValueError, OSError):                            # not the main thread
            continue
    child = job = None
    try:
        held = None
        if hasattr(signal, "pthread_sigmask"):      # what is blocked here is blocked in the program started here
            held = signal.pthread_sigmask(signal.SIG_BLOCK, [getattr(signal, n) for n in ("SIGINT", "SIGTERM", "SIGHUP")])
        try:
            # The pipe also keeps ffmpeg away from the terminal: it would change the terminal's settings, and
            # in a background job (`&`, `timeout`) the system suspends the whole job for that.
            child = subprocess.Popen(cmd, stdin=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        finally:
            if held is not None:
                signal.pthread_sigmask(signal.SIG_SETMASK, held)
        if os.name == "nt":
            job = tie_to_this_process(child)
            if job is None:
                print("Note: ffmpeg could not be tied to this process. If this process is killed, end ffmpeg too "
                      "(taskkill /T /F /PID <this process>), or it records until --duration is over.", file=sys.stderr)
            else:
                _JOBS.append(job)
        deadline, asked_at, noted = None, 0.0, 1
        while True:
            try:
                return child.wait(timeout=0.2), (asked[0] if asked else None)
            except subprocess.TimeoutExpired:
                pass
            if not asked:
                continue
            if deadline is None:
                asked_at = time.monotonic()
                deadline = asked_at + grace
                try:
                    child.stdin.write(b"q")
                    child.stdin.flush()
                except (OSError, ValueError):      # it has already closed its side
                    pass
                print(f"\nStop requested ({asked[0]}): ffmpeg is finishing the file ...", file=sys.stderr, flush=True)
            elif len(asked) > noted:
                noted = len(asked)
                _still_stopping()
            if time.monotonic() > deadline:
                print(f"ffmpeg did not finish in the {time.monotonic() - asked_at:.0f} s since the stop request and "
                      "was killed; the file may not play.", file=sys.stderr, flush=True)
                child.kill()
                deadline = time.monotonic() + grace
    finally:
        if child is not None:
            if child.poll() is None:
                child.kill()
                child.wait()
            if child.stdin:
                try:
                    child.stdin.close()
                except OSError:
                    pass
        if job is not None:
            try:
                import ctypes
                ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(job))
                _JOBS.remove(job)
            except Exception:
                pass
        for number, handler in previous.items():
            if asked:      # stopping: whatever else arrives must not cut the check or the exit code short
                _HANDLERS_BEFORE.setdefault(number, handler)
                signal.signal(number, _still_stopping)
            else:
                signal.signal(number, handler if handler is not None else signal.SIG_DFL)
        if asked and not STOP_SEEN:
            STOP_SEEN.append(asked[0])


def start_early_checks(args: argparse.Namespace, ffmpeg: str, target: str, output: Path) -> list:
    """Schedule the --early-check screenshots. They never touch the recording itself."""
    import threading
    try:
        moments = sorted({float(part) for part in (args.early_check or "").split(",") if part.strip()})
    except ValueError:
        raise SystemExit("--early-check takes seconds, for example 15 or 15,60.")
    timers = []
    for n, moment in enumerate(moments, start=1):
        shot = output.with_name(f"{output.stem}.early-{n}.jpg")

        def grab(shot=shot, moment=moment) -> None:
            try:
                child = subprocess.Popen(early_check_command(args, ffmpeg, target, shot), stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, ValueError, subprocess.SubprocessError):
                return
            EARLY_CHILDREN.append(child)
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                child.kill()
                return
            if shot.is_file():
                print(f"\nEARLY CHECK at {moment:g}s: {shot}\n  Open it NOW. If it does not show the video, "
                      "stop the recording: the rest would be wasted.", file=sys.stderr, flush=True)

        timer = threading.Timer(moment, grab)
        timer.daemon = True
        timer.start()
        timers.append(timer)
    return timers


def resolve_auto_audio(ffmpeg: str, target: str) -> str | None:
    loop = find_loopback(target, probe_audio_devices(ffmpeg, target))
    if not loop:
        return None
    return loop[0]   # on macOS the name is turned into the current index by resolve_macos_args()


def main() -> int:
    safe_stdio()
    # A SIGTERM / SIGHUP at any moment (a probe, a level test, the check afterwards) takes the child along.
    import signal
    previous = {}

    def stop(number, _frame):
        # SystemExit, not a silent end: subprocess.run() kills what it started before passing this on
        raise SystemExit(128 + number)
    if os.name != "nt":
        for name in ("SIGTERM", "SIGHUP"):
            number = getattr(signal, name)
            try:
                if signal.getsignal(number) is signal.SIG_DFL:
                    previous[number] = signal.signal(number, stop)
            except (ValueError, OSError):      # not the main thread
                pass
    elif hasattr(signal, "SIGBREAK"):      # Ctrl+Break would end the process on the spot (0xC000013A): treat it like Ctrl+C
        try:
            if signal.getsignal(signal.SIGBREAK) is signal.SIG_DFL:
                previous[signal.SIGBREAK] = signal.signal(signal.SIGBREAK, signal.default_int_handler)
        except (ValueError, OSError):
            pass
    try:
        return run_main()
    except KeyboardInterrupt:
        print("Stopped (Ctrl+C).", file=sys.stderr)
        return STOP_EXIT_CODES["SIGINT"]
    finally:
        restore_stop_handlers()
        for number, handler in previous.items():
            signal.signal(number, handler)


def run_main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platform",
        choices=("auto", "windows", "macos", "linux"),
        default="auto",
        help="Capture backend. The default detects the current operating system.",
    )
    parser.add_argument("--list-devices", action="store_true", help="List platform capture devices and exit.")
    parser.add_argument("--output", default="browser-capture.mp4", help="Output .mp4 path.")
    parser.add_argument("--duration", type=float, help="Maximum recording duration in seconds.")
    parser.add_argument("--framerate", type=int, default=15, help="Screen capture framerate.")
    parser.add_argument("--video-size", help="Capture size, for example 1920x1080.")
    parser.add_argument("--offset-x", type=int, help="Capture region x offset.")
    parser.add_argument("--offset-y", type=int, help="Capture region y offset.")
    parser.add_argument("--screen-device", default="auto",
                        help="macOS: 'auto' (default, the first 'Capture screen'), a device name, or an "
                             "AVFoundation index. Names are safer: indexes change when devices come and go.")
    parser.add_argument("--scale", type=int, default=None, metavar="WIDTH",
                        help="Scale the recording down to this width (never up). Default: 1920 on macOS, "
                             "where Retina screens capture at 3360 px or more; 0 keeps the native size.")
    parser.add_argument("--skip-screen-probe", action="store_true",
                        help="macOS: skip the short timed screen-open test that runs before a recording.")
    parser.add_argument("--early-check", metavar="SECONDS",
                        help="While recording, grab one separate screenshot at each of these times (for "
                             "example 15 or 15,60) and save it as NAME.early-N.jpg, so the picture can be "
                             "checked without waiting for the end.")
    parser.add_argument("--display", help="Linux X11 display, for example :0.0.")
    parser.add_argument("--window-id", help="Linux: grab one X11 window (x11grab -window_id), e.g. 0x600009 "
                                            "from `xwininfo`. Works under XWayland for X11 apps.")
    parser.add_argument("--force-x11", action="store_true",
                        help="Linux: record with x11grab even though this looks like a Wayland session.")
    parser.add_argument("--skip-post-check", action="store_true",
                        help="Do not run the black-frame / silence check after recording.")
    parser.add_argument("--post-check", metavar="FILE",
                        help="Only run the post-recording check on an existing recording, then exit.")
    parser.add_argument(
        "--audio-device",
        help="'auto', a Windows dshow name, a macOS device name or index, or a Linux Pulse source.",
    )
    parser.add_argument("--audio-bitrate", default="128k")
    parser.add_argument("--preset", default="veryfast")
    parser.add_argument("--crf", type=int, default=23)
    parser.add_argument("--hide-cursor", action="store_true", help="Do not include the pointer in the recording.")
    parser.add_argument("--preflight", action="store_true",
                        help="Report everything that can be known before recording (screen, session, loopback "
                             "device, blockers, the human checklist) as JSON. Records nothing. Exit 2 if blocked.")
    parser.add_argument("--detect-offset", metavar="FILE",
                        help="Find where sound first begins in a recording, as a starting value for "
                             "align_transcript_frames.py --recording-offset.")
    parser.add_argument("--check-audio", action="store_true",
                        help="Report whether a loopback device exists, then exit. Run this FIRST.")
    parser.add_argument("--test-audio", action="store_true",
                        help="Record a few seconds and MEASURE the level, to prove signal is "
                             "actually flowing. Run with the video playing. Catches a muted "
                             "player in seconds instead of after a real-time recording.")
    parser.add_argument("--test-seconds", type=float, default=3.0,
                        help="Length of the --test-audio probe (default 3).")
    parser.add_argument("--allow-silent", action="store_true",
                        help="Proceed with a video-only recording even though no audio device was given.")
    parser.add_argument("--dry-run", action="store_true", help="Print command without running it.")
    args = parser.parse_args()

    ffmpeg = require_ffmpeg()
    target = resolve_platform(args.platform)

    if args.post_check:
        recorded = Path(args.post_check).expanduser().resolve()
        if not recorded.is_file():
            raise SystemExit(f"Recording not found: {recorded}")
        report = post_record_check(ffmpeg, recorded, expect_audio=not args.allow_silent)
        save_post_check(report, recorded)
        explain_post_check(report, target)
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 3
    if args.detect_offset:
        recorded = Path(args.detect_offset).expanduser().resolve()
        if not recorded.is_file():
            raise SystemExit(f"Recording not found: {recorded}")
        print(json.dumps(detect_offset(ffmpeg, recorded), indent=2))
        return 0
    if args.preflight:
        report = preflight(ffmpeg, target, args)
        print(json.dumps(report, indent=2))
        return 0 if report["ready"] else 2
    if args.check_audio:
        return check_audio(ffmpeg, target)
    if args.test_audio:
        return test_audio(ffmpeg, target, args.audio_device, args.test_seconds)
    if args.list_devices:
        return list_devices(ffmpeg, target)

    if args.audio_device == "auto":
        resolved = resolve_auto_audio(ffmpeg, target)
        if not resolved:
            raise SystemExit(
                "--audio-device auto found no loopback device.\n\n"
                + INSTALL_HINTS.get(target, "")
                + "\n\nTo record video only anyway, drop --audio-device and pass --allow-silent."
            )
        print(f"Auto-selected audio device: {resolved}", file=sys.stderr)
        args.audio_device = resolved
    if is_linux_non_monitor(target, args.audio_device):
        print(NOT_A_MONITOR.format(device=args.audio_device) + "\n", file=sys.stderr)

    # Refuse to silently produce silent video: that is exactly the failure that leads to
    # overclaiming later ("I recorded the video" - with no audio in it).
    if not args.audio_device and not args.allow_silent and not args.dry_run:
        loop = find_loopback(target, probe_audio_devices(ffmpeg, target))
        msg = ["No --audio-device given: this recording would capture PICTURE ONLY.",
               "The resulting evidence caps out at 'Frames only' - you will not have heard anything."]
        if loop:
            msg.append("")
            msg.append("Loopback device(s) are available on this machine:")
            msg += [f"  * {d}" for d in loop]
            msg.append("")
            msg.append("Re-run with --audio-device auto (or pass one explicitly).")
        else:
            msg += ["", INSTALL_HINTS.get(target, "")]
        msg += ["", "To record picture only on purpose, pass --allow-silent."]
        raise SystemExit("\n".join(msg))

    if target == "macos":
        chosen = resolve_macos_args(ffmpeg, args)
        for kind in ("screen", "audio"):
            if chosen.get(kind):
                print(f"macOS {kind} device: [{chosen[kind]['index']}] {chosen[kind]['name']} "
                      f"(resolved by {chosen[kind]['resolved_by']})", file=sys.stderr)
        if not args.dry_run and not args.skip_screen_probe:
            probe = macos_screen_probe(ffmpeg, args.screen_device)
            if not probe["ok"] and probe.get("reason") == "timeout":
                apps = probe.get("responsible_apps") or []
                print(MACOS_PERMISSION_HELP.format(seconds=12.0, apps=(" - here: " + " <- ".join(apps)) if apps else ""),
                      file=sys.stderr)
                print(json.dumps({"ok": False, "reason": "screen_open_timeout", "responsible_apps": apps}))
                return 4
            if not probe["ok"]:
                print(f"The screen could not be opened: {probe.get('reason')}", file=sys.stderr)
                return 4
            print(MACOS_PICKER_NOTE + "\n", file=sys.stderr)

    cmd = build_command(args, ffmpeg, target)
    if args.dry_run:
        print(format_command(cmd, target))
        return 0

    audio_note = f"with audio from '{args.audio_device}'" if args.audio_device else "PICTURE ONLY (no audio)"
    print(
        f"Recording authorized visible playback ({target} backend) {audio_note}.\n"
        "This runs in real time - a 12-minute video takes 12 minutes. Press Ctrl+C to stop.\n\n"
        "This records the SCREEN, not the video: whatever is on top gets recorded.\n"
        "  * The player must be full screen and stay in front for the whole recording.\n"
        "  * A person must be at the machine to put it there; nobody may use the computer meanwhile.\n"
        "  * Exactly one player may be playing: a second tab or a re-opened player doubles the audio.\n"
        "  * Note how many seconds pass between starting this recording and the video starting to\n"
        "    play: that offset is needed to map recording time back to video time.\n"
        "  * The agent's own app must stay out of the way: minimise it, and do not end the turn, post a\n"
        "    message or open a dialog until the recording is over.",
        file=sys.stderr,
    )
    output = Path(args.output).expanduser().resolve()
    timers = start_early_checks(args, ffmpeg, target, output)
    stopped = None
    try:
        code, stopped = run_recording(cmd)
    finally:
        for timer in timers:
            timer.cancel()
        for child in EARLY_CHILDREN:
            if child.poll() is None:
                child.kill()
    if stopped:
        code = STOP_EXIT_CODES[stopped]
        kept = f"What was recorded is in {output}." if output.is_file() and output.stat().st_size else "No file was written."
        print(f"Recording stopped early ({stopped}). {kept}", file=sys.stderr, flush=True)
        if stopped in ("SIGTERM", "SIGHUP"):      # whoever sent this wants the process gone: no long checks now
            return code
        if not output.is_file() or output.stat().st_size == 0:
            return code
    if args.skip_post_check or not output.is_file() or output.stat().st_size == 0:
        if code != 0 and target == "linux" and getattr(args, "window_id", None):
            print(f"ffmpeg failed. --window-id {args.window_id} may not be a window of this display any more: "
                  "window ids change whenever the player window is re-created. Look it up again with "
                  "`xwininfo` (or `xwininfo -root -tree`) and pass the new id.", file=sys.stderr)
        elif code != 0 and target == "linux":
            print("ffmpeg failed. 'Cannot open display' means there is no X server at that display "
                  "(Wayland-only session, wrong --display, or a headless shell).", file=sys.stderr)
        return code
    report = post_record_check(ffmpeg, output, expect_audio=bool(args.audio_device))
    save_post_check(report, output)
    explain_post_check(report, target)
    print(json.dumps(report, indent=2))
    if not report["ok"] and not stopped:
        return 3
    if not report["ok"]:
        print(f"The recording was stopped early AND what was written did not pass the check above: do not use "
              f"{output} as evidence.", file=sys.stderr, flush=True)
    return code      # stopped early: always the code of the stop; the report above says whether the check passed


if __name__ == "__main__":
    raise SystemExit(main())
