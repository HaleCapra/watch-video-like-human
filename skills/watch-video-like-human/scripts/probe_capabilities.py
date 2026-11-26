#!/usr/bin/env python3
"""Probe what this machine can actually do, and report which tiers are reachable.

Run this BEFORE choosing an approach. It answers one question: given the tools and
devices present right now, what is the best evidence this session can honestly produce?

  python probe_capabilities.py            # human-readable report
  python probe_capabilities.py --json     # machine-readable
  python probe_capabilities.py --verbose  # include raw device listings
  python probe_capabilities.py --url URL  # also test Route A against this source

Exit code is always 0 - a missing tool is information, not an error.
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
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

# Loopback/virtual audio devices, per platform. Matching is case-insensitive substring.
LOOPBACK_HINTS = {
    "macos": ["blackhole", "loopback", "soundflower", "existential audio", "ishowu", "aggregate"],
    "windows": [
        "stereo mix", "立体声混音", "ステレオ ミキサー",
        "vb-audio", "cable output", "voicemeeter",
        "virtual-audio-capturer", "what u hear", "wave out mix",
    ],
    "linux": [".monitor"],
}

INSTALL_HINTS = {
    "macos": ("BlackHole 2ch: the signed installer from existential.audio/blackhole, or "
              "`brew install blackhole-2ch` (Homebrew does not install on Intel Macs any more). "
              "Then create a Multi-Output Device (speakers + BlackHole) in Audio MIDI Setup - "
              "steps in references/recording-notes.md, or: python scripts/setup_tools.py --tier recording"),
    "windows": ("Install VB-CABLE (vb-audio.com/Cable) or enable 'Stereo Mix' in Sound > Recording. "
                "The VB-CABLE installer switches the default output to 'CABLE Input' - set the "
                "speakers back as the default afterwards"),
    "linux": ("PulseAudio/PipeWire monitor sources are usually present; check `pactl list short sources`. "
              "If `pactl` is missing, install pulseaudio-utils (Debian/Ubuntu) or pipewire-pulse"),
}


def parse_audio_devices(target: str, output: str) -> list[str]:
    if target == "windows":
        names = re.findall(r'"([^"]+)"\s+\(audio\)', output)
    elif target == "macos":
        audio_section = output.split("AVFoundation audio devices:", 1)
        section = audio_section[1] if len(audio_section) == 2 else ""
        names = re.findall(r"\[\d+\]\s*(.+)", section)
    else:
        names = []
    return list(dict.fromkeys(name.strip() for name in names))


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
            if stream.isatty():
                stream.reconfigure(errors="backslashreplace")
            else:   # a pipe: whoever reads it expects UTF-8, not the console's code page
                stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass


def detect_os() -> str:
    system = platform.system().lower()
    return {"darwin": "macos", "windows": "windows", "linux": "linux"}.get(system, system)


def run(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    """Run a command, returning (returncode, stdout+stderr). Never raises."""
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return proc.returncode, decode_output(proc.stdout) + decode_output(proc.stderr)
    except (OSError, subprocess.SubprocessError):
        return 127, ""


def tool_version(name: str, args: list[str]) -> dict:
    path = shutil.which(name)
    if not path:
        return {"present": False, "path": None, "version": None}
    _, out = run([path] + args, timeout=15)
    first = out.strip().splitlines()[0] if out.strip() else ""
    return {"present": True, "path": path, "version": first[:120] or None}


YTDLP_STALE_DAYS = 120


def ytdlp_age_days(version: str | None) -> int | None:
    """yt-dlp versions are release dates (2026.10.21). Site extractors go stale within months."""
    import datetime
    match = re.match(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", (version or "").strip())
    if not match:
        return None
    try:
        released = datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    return (datetime.date.today() - released).days


def private_python() -> str | None:
    """The interpreter of the private environment setup_tools.py makes, if there is one."""
    home = os.environ.get("WVLH_HOME") or os.path.join(os.path.expanduser("~"), ".watch-video-like-human")
    path = os.path.join(home, "venv", "Scripts", "python.exe") if os.name == "nt" else \
        os.path.join(home, "venv", "bin", "python")
    return path if os.path.isfile(path) else None


def private_module(name: str) -> bool:
    interpreter = private_python()
    if not interpreter:
        return False
    code, _ = run([interpreter, "-I", "-c", "import importlib.util,sys;"
                   f"sys.exit(0 if importlib.util.find_spec('{name}') else 1)"], timeout=30)
    return code == 0


def python_module(name: str) -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def list_audio_devices(target: str, ffmpeg: str | None) -> tuple[list[str], str]:
    """Return (device names, raw listing). Best effort; empty on failure."""
    if target == "linux":
        pactl = shutil.which("pactl")
        if not pactl:
            return [], ""
        _, out = run([pactl, "list", "short", "sources"])
        names = [ln.split("\t")[1] for ln in out.splitlines() if "\t" in ln and len(ln.split("\t")) > 1]
        return names, out

    if not ffmpeg:
        return [], ""

    if target == "macos":
        _, out = run([ffmpeg, "-hide_banner", "-nostdin", "-f", "avfoundation", "-list_devices", "true", "-i", ""])
    elif target == "windows":
        _, out = run([ffmpeg, "-hide_banner", "-nostdin", "-list_devices", "true", "-f", "dshow", "-i", "dummy"])
    else:
        return [], ""

    return parse_audio_devices(target, out), out


def find_loopback(target: str, devices: list[str]) -> list[str]:
    hints = LOOPBACK_HINTS.get(target, [])
    return [d for d in devices if any(h in d.lower() for h in hints)]


# This skill's own folder names. Matching them would report ourselves as the companion
# skill, so they are excluded explicitly.
SELF_NAMES = {"watch-video-like-human", "watch_video_like_human"}
COMPANION_NAMES = {"watch", "claude-video", "watch-video"}


def find_claude_video() -> dict:
    """Look for an installed claude-video / watch skill in the usual places.

    Must not match this skill itself, and must ignore trashed or backup copies -
    a false positive here makes the agent hand Route A to a companion that is not there.
    """
    home = Path.home()
    roots = [
        home / ".claude" / "skills",
        home / ".claude" / "plugins",
        home / ".config" / "claude" / "skills",
        home / ".codex" / "skills",
        home / ".codebuddy" / "skills",
        home / ".workbuddy" / "skills",
        home / ".agents" / "skills",
        home / ".cursor" / "skills",
        Path.cwd() / ".claude" / "skills",
    ]
    skip_parts = {".trash", "trash", ".backup", "backup", "__pycache__", "node_modules"}
    found = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for entry in root.rglob("SKILL.md"):
                parts = {p.lower() for p in entry.parts}
                if parts & skip_parts:
                    continue
                folder = entry.parent.name.lower()
                if folder in SELF_NAMES or folder not in COMPANION_NAMES:
                    continue
                # Confirm it really is a video skill, not something else named "watch".
                try:
                    head = entry.read_text(encoding="utf-8", errors="replace")[:800].lower()
                except OSError:
                    continue
                if "video" not in head:
                    continue
                path = str(entry.parent)
                if path not in found:
                    found.append(path)
                if len(found) >= 5:
                    break
        except (OSError, PermissionError):
            continue
    return {"present": bool(found), "paths": found}


def ytdlp_probe_command() -> list[str] | None:
    path = shutil.which("yt-dlp")
    if path:
        return [path]
    if python_module("yt_dlp"):
        return [sys.executable, *_interpreter_flags(), "-m", "yt_dlp"]
    return None


def check_target_url(url: str, timeout: int = 30) -> dict:
    """Ask yt-dlp to resolve one source without downloading media."""
    command = ytdlp_probe_command()
    host = urlparse(url).hostname or "unknown"
    if not command:
        return {"tested": False, "ok": None, "host": host,
                "note": "yt-dlp is not installed"}
    code, output = run(command + ["--simulate", "--skip-download", "--no-playlist",
                                  "--no-warnings", url], timeout=timeout)
    if code == 0:
        return {"tested": True, "ok": True, "host": host,
                "note": "yt-dlp simulation succeeded"}
    sanitized = output.replace(url, "<target-url>")
    lines = [line.strip() for line in sanitized.splitlines() if line.strip()]
    note = (lines[-1] if lines else f"yt-dlp exited {code}")[:240]
    return {"tested": True, "ok": False, "host": host, "note": note}


# A certificate error is itself an answer from the host: the connection was made and the server
# presented a certificate. Nothing is ever re-requested with verification turned off.
TLS_NOTE = "answered, but this Python could not verify the certificate"
TLS_CAUSES = ("this Python has no CA certificates (python.org builds on macOS until 'Install "
              "Certificates.command' is run)", "a company proxy or security product is re-signing HTTPS",
              "the system clock is wrong")


def check_network(target_url: str | None = None, timeout: float = 8.0) -> dict:
    """Actually try the network. A tool being installed does not mean it can reach anything.

    Sandboxed agent environments routinely allow an allowlist of hosts and refuse the rest,
    so yt-dlp can be present and still fail every time. Report that up front instead of
    letting Route A be planned and then collapse.
    """
    import ssl
    import urllib.error
    import urllib.request

    def probe(url: str) -> tuple[bool, str]:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "capability-probe/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return True, f"HTTP {resp.status}"
        except urllib.error.HTTPError as exc:
            return True, f"HTTP {exc.code}"          # reached the host; status is irrelevant
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(exc.reason):
                return False, TLS_NOTE
            return False, str(exc.reason)[:90]
        except ssl.SSLError:
            return False, TLS_NOTE
        except Exception as exc:                      # noqa: BLE001 - never fail the probe
            return False, f"{type(exc).__name__}: {exc}"[:90]

    general_ok, general_note = probe("https://example.com")
    youtube_ok, youtube_note = probe("https://www.youtube.com")

    if general_ok and youtube_ok:
        verdict = "open"
    elif TLS_NOTE in (general_note, youtube_note) and not (general_ok or youtube_ok):
        # The hosts answered; THIS Python could not check their certificates. That says nothing
        # about yt-dlp or the browser, which bring their own certificate stores.
        verdict = "tls_unverified"
    elif not general_ok and not youtube_ok:
        verdict = "no_egress"
    else:
        verdict = "partial"

    tls_broken = TLS_NOTE in (general_note, youtube_note)
    result = {
        "verdict": verdict,
        "python_tls_trust": "broken" if tls_broken else "ok",
        "general": {"ok": general_ok, "note": general_note, "answered": general_ok or general_note == TLS_NOTE},
        "youtube": {"ok": youtube_ok, "note": youtube_note, "answered": youtube_ok or youtube_note == TLS_NOTE},
    }
    if tls_broken:
        result["tls_possible_causes"] = list(TLS_CAUSES)
        result["note"] = ("The host answered, so the network is there, but this Python could not verify the "
                          "certificate. Possible causes: " + "; ".join(TLS_CAUSES) + ". Test the real source "
                          "with --url (yt-dlp has its own certificates). Do not turn certificate checks off.")
    if target_url:
        result["target"] = check_target_url(target_url)
    return result


def transcription_options() -> dict:
    """Anything that can turn audio into timestamped text."""
    return {
        "openai_whisper_cli": shutil.which("whisper") is not None,
        "whisper_module": python_module("whisper") or private_module("whisper"),
        "faster_whisper": python_module("faster_whisper") or private_module("faster_whisper"),
        "mlx_whisper": python_module("mlx_whisper") or private_module("mlx_whisper"),   # Apple Silicon
        "whisper_cpp": shutil.which("whisper-cli") is not None or shutil.which("main") is not None,
        "groq_api_key": bool(os.environ.get("GROQ_API_KEY")),
        "openai_api_key": bool(os.environ.get("OPENAI_API_KEY")),
    }


def screen_info(target: str) -> dict | None:
    """Whether this process has a screen it can capture. Only Linux can tell from the environment."""
    if target != "linux":
        return None
    env = os.environ
    wayland = env.get("XDG_SESSION_TYPE", "").strip().lower() == "wayland" or bool(env.get("WAYLAND_DISPLAY"))
    return {"display": env.get("DISPLAY") or None, "wayland": wayland}


def evaluate(report: dict) -> dict:
    """Decide which tiers are reachable and why not, if not."""
    ff = report["tools"]["ffmpeg"]["present"]
    ffp = report["tools"]["ffprobe"]["present"]
    ytdlp = report["tools"]["yt-dlp"]["present"] or report["python_modules"]["yt_dlp"]
    loop = bool(report["audio"]["loopback_devices"])
    trans = any(report["transcription"].values())

    tiers = {}

    tiers["tier0_user_file"] = {
        "reachable": ff and ffp,
        "why": "Always available if ffmpeg is present - the user hands over a file."
        if (ff and ffp) else "ffmpeg/ffprobe missing; cannot process a local file.",
    }

    net = report.get("network") or {}
    net_verdict = net.get("verdict")
    target_probe = net.get("target") or {}
    tools_ok = bool(ytdlp and ff)

    if not tools_ok:
        a_reachable = False
        a_why = ("Needs yt-dlp and ffmpeg. See what would be installed, without installing: "
                 "python scripts/setup_tools.py")
    elif target_probe.get("tested") and target_probe.get("ok"):
        a_reachable = True
        a_why = (f"yt-dlp resolved the requested source at {target_probe.get('host')} "
                 "without downloading media.")
    elif target_probe.get("tested") and not target_probe.get("ok"):
        a_reachable = False
        a_why = (f"The requested source at {target_probe.get('host')} failed a yt-dlp simulation: "
                 f"{target_probe.get('note')}")
    elif net_verdict == "no_egress":
        a_reachable = False
        a_why = ("Tools are installed but this environment has NO outbound network. "
                 "Route A cannot work here; it will work unchanged on a normal connection.")
    elif net_verdict == "tls_unverified":
        a_reachable = None
        a_why = ("yt-dlp + ffmpeg are present. This Python could not verify HTTPS certificates, so the "
                 "connectivity test is inconclusive (it is NOT evidence of no network). Test the real "
                 "source with --url.")
    elif net_verdict == "partial":
        a_reachable = None
        a_why = ("yt-dlp + ffmpeg are present, but only partial basic connectivity was observed. "
                 "No target URL was tested, so Route A remains an unverified candidate.")
    elif net_verdict == "open":
        a_reachable = True
        a_why = ("yt-dlp + ffmpeg are present and basic connectivity works. No target URL was "
                 "tested, so source-specific support is still unverified.")
    else:
        a_reachable = True
        a_why = "yt-dlp + ffmpeg present. Network not tested."

    stale = report["tools"]["yt-dlp"].get("stale")
    if stale and tools_ok:
        a_why += (f" WARNING: yt-dlp is {report['tools']['yt-dlp'].get('age_days')} days old; outdated "
                  "extractors fail in misleading ways (bot checks, tiny manifest files, parser errors). "
                  "Offer the user an update: python scripts/setup_tools.py")
    tiers["tierA_download"] = {
        "reachable": a_reachable,
        "why": a_why,
        "note": "Installed tools do not imply reachability: cloud IPs and egress proxies both "
                "block this, and each looks different in the error message.",
    }

    tiers["tierB_browser"] = {
        "reachable": None,
        "why": "Cannot be probed from a script - depends on the agent having browser tools. "
               "Check your own tool list for a JavaScript-evaluation browser tool.",
        "note": "Yields frames + caption TEXT only. Never audio.",
    }

    screen = report.get("screen")
    c_reachable: bool | None = bool(ff and loop)
    if not ff:
        c_why = "ffmpeg missing."
    elif not loop:
        c_why = "No loopback audio device found. " + INSTALL_HINTS.get(report["os"], "")
    elif screen and not screen.get("display") and not screen.get("wayland"):
        c_reachable = False
        c_why = ("ffmpeg and a loopback device are present, but DISPLAY is not set: this process has no "
                 "screen to capture (headless shell, container or SSH session).")
    elif screen and screen.get("wayland"):
        c_reachable = None
        c_why = ("ffmpeg and a loopback device are present, but this is a Wayland session: x11grab "
                 "usually records a BLACK picture here. Use the desktop's own recorder and treat the "
                 "file as Route 0, or record one X11 window with --window-id.")
    else:
        c_why = "ffmpeg + a loopback audio device are present."
    tiers["tierC_record"] = {
        "reachable": c_reachable,
        "why": c_why,
        "note": "Real-time: a 60-minute video takes 60 minutes. Requires a real desktop session - "
                "not a headless container, and not a sandboxed VM that cannot see the screen.",
    }

    best = "none"
    if tiers["tierA_download"]["reachable"] and trans:
        best = "Complete audio + sampled visuals possible (Route A)"
    elif tiers["tierC_record"]["reachable"] and trans:
        best = "Complete audio + sampled visuals possible (Route C)"
    elif tiers["tierA_download"]["reachable"]:
        best = "Transcript + frames (download; captions only, no transcription tool)"
    elif tiers["tier0_user_file"]["reachable"]:
        best = "Transcript + frames if the user supplies a file"
    else:
        best = "Metadata / browser text only"

    # The ladder: the four routes in the order they are tried, each with one status word.
    host_browser = report.get("host_browser")
    if host_browser is True:
        tiers["tierB_browser"].update(reachable=True, why="The host reports a browser tool that can run page scripts.")
    elif host_browser is False:
        tiers["tierB_browser"].update(reachable=False, why="The host has no browser tool, so Route B is unavailable.")
    gives = {"tier0_user_file": "complete media: picture + real audio",
             "tierA_download": "complete media: picture + real audio",
             "tierB_browser": "sampled frames + caption text; never real audio",
             "tierC_record": "real-time recording: picture + loopback audio"}
    names = {"tier0_user_file": "0", "tierA_download": "A", "tierB_browser": "B", "tierC_record": "C"}
    ladder = []
    for key in ("tier0_user_file", "tierA_download", "tierB_browser", "tierC_record"):
        state = tiers[key]["reachable"]
        status = "reachable" if state is True else "unreachable" if state is False else (
            "host-dependent" if key == "tierB_browser" else "unverified")
        entry = {"route": names[key], "status": status, "gives": gives[key], "why": tiers[key]["why"]}
        if key == "tier0_user_file":
            entry["needs"] = "the user to supply a local file"
        if key == "tierC_record":
            entry["needs"] = "the user's go-ahead and a person at the machine; runs in real time"
        ladder.append(entry)
    automatic = [e["route"] for e in ladder if e["route"] in ("A", "B") and e["status"] != "unreachable"]
    return {"tiers": tiers, "best_verdict_possible": best,
            "transcription_available": trans, "ladder": ladder,
            "try_in_order": ["0 (only if the user has a file)"] + automatic
                            + (["C (ask first)"] if ladder[3]["status"] != "unreachable" else []),
            "ladder_rule": "Stop at the first route that is reachable and sufficient. Moving 0 -> A -> B is "
                           "automatic and goes into the Route history; Route C needs the user's yes."}


def build_report(verbose: bool, test_network: bool = True,
                 target_url: str | None = None, host_browser: bool | None = None) -> dict:
    target = detect_os()
    ffmpeg_info = tool_version("ffmpeg", ["-version"])
    devices, raw = list_audio_devices(target, ffmpeg_info["path"])

    ytdlp_info = tool_version("yt-dlp", ["--version"])
    ytdlp_info["age_days"] = ytdlp_age_days(ytdlp_info.get("version"))
    ytdlp_info["stale"] = bool(ytdlp_info["age_days"] is not None and ytdlp_info["age_days"] > YTDLP_STALE_DAYS)
    report = {
        "os": target,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "private_environment": private_python(),
        "tools": {
            "ffmpeg": ffmpeg_info,
            "ffprobe": tool_version("ffprobe", ["-version"]),
            "yt-dlp": ytdlp_info,
        },
        "python_modules": {
            "yt_dlp": python_module("yt_dlp"),
        },
        "transcription": transcription_options(),
        "audio": {
            "devices_found": len(devices),
            "loopback_devices": find_loopback(target, devices),
            "install_hint": INSTALL_HINTS.get(target, ""),
        },
        "screen": screen_info(target),
        "claude_video": find_claude_video(),
        "network": check_network(target_url) if test_network else None,
        "host_browser": host_browser,
    }
    if verbose:
        report["audio"]["all_devices"] = devices
        report["audio"]["raw_listing"] = raw
    report["assessment"] = evaluate(report)
    report["setup"] = setup_advice(report)
    return report


def setup_advice(report: dict) -> dict:
    """What is missing, and the one question to put to the user before anything is installed."""
    missing = [name for name in ("ffmpeg", "ffprobe") if not report["tools"][name]["present"]]
    if not (report["tools"]["yt-dlp"]["present"] or report["python_modules"]["yt_dlp"]):
        missing.append("yt-dlp")
    elif report["tools"]["yt-dlp"].get("stale"):
        missing.append("a current yt-dlp (the installed one is "
                       f"{report['tools']['yt-dlp'].get('age_days')} days old)")
    optional = []
    if not any(report["transcription"].values()):
        optional.append("a local speech recogniser (python scripts/setup_tools.py --tier whisper)")
    if not report["audio"]["loopback_devices"]:
        optional.append("a loopback audio device for Route C (guide: python scripts/setup_tools.py --tier recording)")
    advice = {"missing": missing, "optional": optional,
              "plan_command": "python scripts/setup_tools.py",
              "rule": "Show the plan and ask first. Install only after the user says yes "
                      "(python scripts/setup_tools.py --yes). Never install silently, never use sudo, "
                      "never type a password for the user."}
    if missing:
        advice["ask_user"] = ("This machine is missing " + ", ".join(missing) + ". May I install "
                              + ("it" if len(missing) == 1 else "them")
                              + "? I will show you the exact commands first.")
    return advice


def human(report: dict) -> str:
    a = report["assessment"]
    lines = [
        "=" * 68,
        f"  Capability probe - {report['os']} / python {report['python']}",
        "=" * 68,
        "",
        "TOOLS",
    ]
    lines.append(f"  [OK ] python     {report['python']}  ({report.get('python_executable')})")
    if (report.get("network") or {}).get("python_tls_trust") == "broken":
        lines.append("  [ ! ] python TLS this Python cannot verify HTTPS certificates; the hosts did answer.")
        for cause in report["network"].get("tls_possible_causes", []):
            lines.append(f"        possible cause: {cause}")
    for name, info in report["tools"].items():
        mark = "OK " if info["present"] else "-- "
        if info.get("stale"):
            mark = "!! "
        lines.append(f"  [{mark}] {name:<10} {info['version'] or 'not found'}"
                     + (f"   ({info['age_days']} days old - outdated)" if info.get("stale") else ""))
    if report.get("private_environment"):
        lines.append(f"  [OK ] private    {report['private_environment']}")
    if report["python_modules"]["yt_dlp"]:
        lines.append("  [OK ] yt_dlp     (python module)")

    lines += ["", "TRANSCRIPTION (audio -> text)"]
    any_trans = False
    for name, ok in report["transcription"].items():
        if ok:
            lines.append(f"  [OK ] {name}")
            any_trans = True
    if not any_trans:
        lines.append("  [-- ] none found - audio cannot be turned into text on this machine")
        lines.append("        (looked in the Python running this probe, in the private environment of "
                     "setup_tools.py and on PATH;")
        lines.append("         a recogniser installed in another virtual environment is not seen - run the "
                     "probe with that Python)")
        lines.append("        once one is installed:  python scripts/transcribe_local.py WORK/audio.wav --language LANG")
        lines.append("        see the plan (installs nothing):  python scripts/setup_tools.py --tier whisper")

    lines += ["", "AUDIO LOOPBACK (needed to record what you hear)"]
    if report["audio"]["loopback_devices"]:
        for d in report["audio"]["loopback_devices"]:
            lines.append(f"  [OK ] {d}")
    else:
        lines.append(f"  [-- ] none found among {report['audio']['devices_found']} device(s)")
        if report["audio"]["install_hint"]:
            lines.append(f"        {report['audio']['install_hint']}")

    lines += ["", "COMPANION SKILL"]
    if report["claude_video"]["present"]:
        for p in report["claude_video"]["paths"]:
            lines.append(f"  [OK ] another video skill at {p}")
    else:
        lines.append("  [-- ] no other video skill found (optional: this skill does not need one)")

    net = report.get("network")
    if net:
        lines += ["", "NETWORK (does this machine actually reach the internet?)"]
        marks = {"open": "OK ", "partial": "!! ", "no_egress": "-- ", "tls_unverified": " ? "}
        lines.append(f"  [{marks.get(net['verdict'], ' ? ')}] verdict: {net['verdict']}")
        lines.append(f"         general internet: {'reachable' if net['general']['ok'] else net['general']['note']}")
        lines.append(f"         YouTube homepage: {'reachable' if net['youtube']['ok'] else net['youtube']['note']}")
        if net.get("note"):
            lines.append(f"         {net['note']}")
        target = net.get("target")
        if target:
            state = "reachable by yt-dlp" if target.get("ok") else target.get("note")
            lines.append(f"         target ({target.get('host')}): {state}")

    lines += ["", "TIERS"]
    labels = {
        "tier0_user_file": "0  user-supplied file",
        "tierA_download": "A  download (yt-dlp)",
        "tierB_browser": "B  browser extraction",
        "tierC_record": "C  record + loopback",
    }
    for key, label in labels.items():
        t = a["tiers"][key]
        mark = {True: "OK ", False: "-- ", None: " ? "}[t["reachable"]]
        lines.append(f"  [{mark}] {label}")
        lines.append(f"         {t['why']}")
        if t.get("note"):
            lines.append(f"         note: {t['note']}")

    lines += ["", "LADDER  (stop at the first route that is reachable and sufficient)"]
    for entry in a["ladder"]:
        lines.append(f"  {entry['route']}  {entry['status']:<15} {entry['gives']}")
    lines.append("  try in order: " + " -> ".join(a["try_in_order"]))
    lines.append("  " + a["ladder_rule"])

    setup = report.get("setup") or {}
    if setup.get("missing") or setup.get("optional"):
        lines += ["", "SETUP  (nothing is installed without the user's yes)"]
        for item in setup.get("missing", []):
            lines.append(f"  missing : {item}")
        for item in setup.get("optional", []):
            lines.append(f"  optional: {item}")
        if setup.get("ask_user"):
            lines.append(f"  ask the user: \"{setup['ask_user']}\"")
        lines.append(f"  plan (dry run): {setup['plan_command']}")
    lines += ["", "-" * 68,
              f"  Best honest verdict reachable here: {a['best_verdict_possible']}",
              "-" * 68]
    return "\n".join(lines)


def main() -> int:
    safe_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a report.")
    parser.add_argument("--verbose", action="store_true", help="Include raw device listings.")
    parser.add_argument("--no-network-test", action="store_true",
                        help="Skip the outbound connectivity check (saves a few seconds).")
    parser.add_argument("--url", help="Target video URL for a lightweight yt-dlp simulation.")
    parser.add_argument("--has-browser", choices=["yes", "no"],
                        help="Tell the probe whether the host agent has a browser tool that can run page "
                             "scripts. A script cannot see the agent's tools, so Route B is 'host-dependent' "
                             "until you say.")
    args = parser.parse_args()

    report = build_report(args.verbose, test_network=not args.no_network_test,
                          target_url=args.url,
                          host_browser={"yes": True, "no": False}.get(args.has_browser))
    print(json.dumps(report, indent=2) if args.json else human(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
