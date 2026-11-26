#!/usr/bin/env python3
"""Tier A: get captions, metadata, audio, or video for a URL, via yt-dlp.

Defaults to the least invasive option that answers the question. Order of preference:

  --info          metadata + chapters only, nothing downloaded   (cheapest)
  --captions      subtitle files only, media skipped             (default)
  --audio         audio track only, for transcription
  --video         the video file, for frame extraction

Scope note: captions and metadata are text the platform serves for normal viewing.
Downloading the media stream itself is a heavier action with its own terms-of-service
implications on some platforms - which is why it is opt-in here rather than the default.
Use this only for content the user is authorized to access, and never to get around DRM,
a paywall, or an access control.

Examples
--------
  python fetch_media.py URL --info
  python fetch_media.py URL --captions --lang en --out-dir work
  python fetch_media.py URL --audio --out-dir work
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
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Distinct failure modes, checked in order. The proxy case is first because sandboxed
# agent environments hit it constantly and it looks nothing like a platform block.
PROXY_MARKERS = (
    "unable to connect to proxy", "tunnel connection failed", "proxyerror",
    "connection refused", "name or service not known", "temporary failure in name resolution",
)
IPBLOCK_MARKERS = (
    "sign in to confirm", "not a bot", "http error 429", "too many requests",
    "your ip", "blocked",
)
AUTH_MARKERS = ("private video", "members-only", "login required", "requires authentication",
                "join this channel", "age-restricted")
UNSUPPORTED_MARKERS = ("unsupported url", "no video formats", "is not a valid url")
# yt-dlp's own site extractor crashed. Seen on a real machine with a two-year-old yt-dlp:
# TED, archive.org and Vimeo all failed this way while the sites themselves were reachable.
EXTRACTOR_MARKERS = ("an extractor error has occurred", "please report this issue",
                     "list index out of range", "the json object must be str",
                     "keyerror(", "unable to extract")
BOT_CHECK_MARKERS = ("sign in to confirm", "not a bot")
PRECONDITION_MARKERS = ("http error 412", "precondition failed")
MANIFEST_MARKER = "ERROR: manifest instead of media"
MANIFEST_SUFFIXES = (".mpd", ".m3u8", ".f4m", ".ism")
YTDLP_STALE_DAYS = 120
# Browsers yt-dlp can read a login from. Named explicitly every time; never detected, never a default.
LOGIN_BROWSERS = ("firefox", "chrome", "edge", "brave", "chromium", "opera", "vivaldi", "safari", "whale")
COOKIE_ACCESS_MARKERS = ("could not copy chrome cookie database", "failed to decrypt with dpapi",
                         "could not find chrome cookies database", "could not find firefox cookies database",
                         "app-bound", "app bound encryption", "cookie database is locked",
                         "permission denied: ", "unable to open database file",
                         "failed to load cookies", "cannot decrypt v20 cookies")
LOGIN_STATE: dict = {"args": [], "browser": None}
PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/(?:Users|home)/)[^\s'\"]+")
LOGIN_WARNING = ("USING THE USER'S BROWSER LOGIN ({browser}). Login cookies are credentials: they are read by "
                 "yt-dlp in memory for this command only and are never written to a file, a log or the "
                 "evidence manifest. Automated downloading may be against a site's rules and can get an "
                 "account limited. Only for videos this account can already watch normally; it does not "
                 "solve captchas or get past DRM, paywalls or other restrictions.")


def login_args(browser: str | None, profile: str | None) -> list[str]:
    """yt-dlp arguments for an explicitly requested browser login, or nothing."""
    if not browser:
        if profile:
            raise SystemExit("--browser-profile only makes sense together with --cookies-from-browser.")
        return []
    name = browser.strip().lower()
    if name not in LOGIN_BROWSERS:
        raise SystemExit(f"--cookies-from-browser takes one browser name ({', '.join(LOGIN_BROWSERS)}), not "
                         f"{browser!r}. A cookie file, a keyring or a container is not accepted here.")
    if profile is not None and (not profile.strip() or any(ch in profile for ch in ":\n\r")):
        raise SystemExit("--browser-profile is a profile name or folder name without ':'.")
    return ["--cookies-from-browser", name + (f":{profile.strip()}" if profile else "")]


def scrub_login(text: str) -> str:
    """Never echo the profile (it can be a path or an account name) or anything shaped like a cookie."""
    for i, part in enumerate(LOGIN_STATE["args"]):
        if i == 1 and ":" in part:
            text = text.replace(part, part.split(":", 1)[0] + ":<profile>")
    if LOGIN_STATE["browser"]:      # browser data paths carry the user's account name
        text = PATH_RE.sub("<path>", text)
    text = re.sub(r"(?i)(cookie:\s*)[^\r\n]+", r"\1<removed>", text)
    return re.sub(r"(?i)\b(sessdata|sapisid|sid|session[_-]?id|auth[_-]?token)=[^;\s]+", r"\1=<removed>", text)
RATE_LIMIT_MARKERS = ("http error 429", "too many requests")


def raw_error(output: str) -> str:
    """The last ERROR line yt-dlp printed, verbatim, so the real cause is never hidden."""
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    errors = [ln for ln in lines if ln.upper().startswith("ERROR")]
    picked = errors[-1] if errors else (lines[-1] if lines else "")
    return picked[:500]


def require_ytdlp() -> list[str]:
    path = shutil.which("yt-dlp")
    if path:
        return [path]
    if _module_available("yt_dlp"):
        return [sys.executable, *_interpreter_flags(), "-m", "yt_dlp"]
    raise SystemExit(
        "yt-dlp not found.\n"
        "See what would be installed (nothing is, without a yes):  python scripts/setup_tools.py\n"
        "Ask the user before installing anything."
    )


def _module_available(name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(name) is not None


def safe_media_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned or "media"


_VERSION_NOTE: dict = {}


def ytdlp_age_note(ytdlp: list[str] | None = None) -> str:
    """One line about how old this yt-dlp is, when that is old enough to explain a failure."""
    import datetime
    command = ytdlp or _VERSION_NOTE.get("command")
    if not command:
        return ""
    _VERSION_NOTE["command"] = command
    if "note" not in _VERSION_NOTE:
        note = ""
        try:
            out = decode_output(subprocess.run(command + ["--version"], capture_output=True, timeout=20,
                                               stdin=subprocess.DEVNULL).stdout)
            match = re.match(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", out.strip())
            if match:
                age = (datetime.date.today() - datetime.date(*(int(g) for g in match.groups()))).days
                if age > YTDLP_STALE_DAYS:
                    note = (f"NOTE: this yt-dlp is version {out.strip().split()[0]}, {age} days old. Site "
                            "extractors go stale within months, and an old one fails in misleading ways. "
                            "Ask the user before updating: python scripts/setup_tools.py shows the plan.")
        except (OSError, ValueError, subprocess.SubprocessError):
            note = ""
        _VERSION_NOTE["note"] = note
    return _VERSION_NOTE["note"]


def explain_failure(output: str) -> str:
    """Name the failure mode and always append yt-dlp's own error line."""
    raw = raw_error(output)
    age = ytdlp_age_note()
    return (_diagnose(output) + (f"\n\n{age}" if age else "")
            + (f"\n\nRaw yt-dlp error: {raw}" if raw else ""))


def _diagnose(output: str) -> str:
    """Name the actual failure mode. Each one has a different correct next move."""
    low = output.lower()

    if TIMEOUT_MARKER.lower() in low or "timed out" in low or "network is unreachable" in low:
        return (
            "THE SITE DID NOT ANSWER IN TIME - this machine probably has no working route to it\n"
            "(no connectivity, a proxy this shell cannot use, or the site is unreachable from here).\n"
            "  -> Do not retry in a loop. Check with probe_capabilities.py --url URL.\n"
            "  -> Fall back to Tier B / Tier C, or run Tier A where the site is reachable."
        )

    if any(m in low for m in PROXY_MARKERS):
        return (
            "NETWORK BLOCKED BY THIS ENVIRONMENT (not by the platform).\n"
            "The request never reached the site - an egress proxy or network policy refused it.\n"
            "Sandboxed agent environments commonly allow only an allowlist of hosts.\n"
            "  -> Tier A is unavailable *here*, but will likely work unchanged on the user's own\n"
            "     machine. This is an environment limit, not a property of the video.\n"
            "  -> In this session, use Tier B (browser extraction) instead - the browser tooling\n"
            "     reaches the page through a different path than this shell does.\n"
            "Do not retry with different flags; nothing about the command is wrong."
        )

    if MANIFEST_MARKER.lower() in low:
        return (
            "yt-dlp SAVED A STREAMING MANIFEST INSTEAD OF THE VIDEO and reported success.\n"
            "The file it wrote is a few kilobytes of playlist text (.mpd / .m3u8), not media. This is\n"
            "what an outdated yt-dlp does on sites whose player has changed since; it is not an\n"
            "access block and nothing about the command is wrong.\n"
            "  -> Tell the user their yt-dlp is probably too old. Do not update it without being asked.\n"
            "  -> Meanwhile fall back to Tier B (browser extraction) or Tier C."
        )

    if LOGIN_STATE["browser"] and any(m in low for m in COOKIE_ACCESS_MARKERS):
        return (
            "THE BROWSER'S LOGIN DATA COULD NOT BE READ (--cookies-from-browser).\n"
            "On Windows, Chrome and Edge keep it encrypted and bound to the browser itself, and lock\n"
            "the database while they run; yt-dlp is then refused. This is the browser protecting the\n"
            "user's logins, and it stays that way: do not try to get around the encryption, do not\n"
            "run anything as administrator, do not close the user's browser for them, and do not\n"
            "suggest an extension that exports cookies.\n"
            "  -> Ask the user whether Firefox holds the same login, and if so name Firefox instead.\n"
            "  -> Otherwise use Tier B: the video plays in the user's own logged-in browser."
        )

    if any(m in low for m in PRECONDITION_MARKERS):
        return (
            "THE SITE REFUSED THE REQUEST (HTTP 412 Precondition Failed).\n"
            "Seen on Bilibili. The cause is not established: it may be the site's risk control, the\n"
            "network or region this request came from, or a yt-dlp too old for the site. The same\n"
            "video has worked from another connection. Do not retry in a loop and do not disguise\n"
            "the client.\n"
            "  -> If this shell sends its traffic through a proxy (HTTPS_PROXY / ALL_PROXY is set), that\n"
            "     was the cause in a field test: the site refused the proxy's foreign exit address and\n"
            "     the same command worked at once without the proxy. Tell the user; trying it without\n"
            "     the proxy is their decision.\n"
            "  -> Fall back to Tier B (the user's own browser session) or Tier C, or ask for the file.\n"
            "  -> The user may update yt-dlp and retry; that is their choice."
        )

    if any(m in low for m in BOT_CHECK_MARKERS):
        return (
            "THE PLATFORM DEMANDED A SIGN-IN / BOT CHECK before serving this video.\n"
            "This happens on cloud IP ranges, but also on ordinary home connections, especially\n"
            "with an outdated yt-dlp. It is an access control: never type credentials, never solve\n"
            "a captcha, never disguise the client.\n"
            "  -> Fall back to Tier B (the user's own browser session) or Tier C.\n"
            "  -> The user may update yt-dlp and retry; that is their choice, not an evasion.\n"
            "  -> Only if the USER says yes when asked: their own browser login can be used for a\n"
            "     video their account can already watch (--cookies-from-browser BROWSER). Never add\n"
            "     that option on your own, and never as an automatic retry."
        )

    if any(m in low for m in RATE_LIMIT_MARKERS):
        return (
            "THE SITE RATE-LIMITED OR REFUSED THIS CLIENT (HTTP 429).\n"
            "Some hosts refuse automated download clients outright. Do not retry in a loop and\n"
            "do not disguise the client.\n"
            "  -> Fall back to Tier B / Tier C, or ask the user for the file (Route 0)."
        )

    if any(m in low for m in IPBLOCK_MARKERS):
        return (
            "THE PLATFORM REFUSED THE REQUEST, most likely because of the IP address.\n"
            "YouTube blocks most cloud provider ranges (AWS / GCP / Azure), so this fails from a\n"
            "hosted container but works from a normal home connection.\n"
            "  -> Retry from the user's own machine, or fall back to Tier B / Tier C.\n"
            "Do not attempt to evade the block."
        )

    if any(m in low for m in EXTRACTOR_MARKERS):
        return (
            "yt-dlp's OWN EXTRACTOR FAILED on this site - the site was reached, the parser broke.\n"
            "The usual cause is an outdated yt-dlp (check `yt-dlp --version`; site extractors go\n"
            "stale within months). This is not an access block.\n"
            "  -> Tell the user their yt-dlp may need updating; do not install or update it\n"
            "     without being asked.\n"
            "  -> Meanwhile fall back to Tier B (browser extraction) or Tier C."
        )

    if any(m in low for m in AUTH_MARKERS):
        return (
            "THE CONTENT REQUIRES AN ACCOUNT.\n"
            "Do not attempt to authenticate from here. If the user is authorized to watch it,\n"
            "the right path is Tier B or Tier C inside their own already-logged-in browser."
        )

    if any(m in low for m in UNSUPPORTED_MARKERS):
        return ("yt-dlp does not support this site. Fall back to Tier B (browser extraction) "
                "or Tier C (record + loopback).")

    return ("Cause not recognised. Fall back to Tier B (browser extraction) or "
            "Tier C (record + loopback), and report the raw error to the user.")


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


# Without these a dead route (no path to the site) leaves yt-dlp hanging for minutes.
NETWORK_ARGS = ["--socket-timeout", "20", "--retries", "2", "--extractor-retries", "1"]
TIMEOUT_MARKER = "ERROR: timed out: yt-dlp did not finish in time"


def run_ytdlp(ytdlp: list[str], args: list[str], timeout: int = 300) -> tuple[int, str]:
    cmd = ytdlp + NETWORK_ARGS + LOGIN_STATE["args"] + args
    print("$ " + scrub_login(" ".join(cmd)), file=sys.stderr)
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return 124, f"{TIMEOUT_MARKER} ({timeout}s)"
    return proc.returncode, scrub_login(decode_output(proc.stdout) + decode_output(proc.stderr))


def fetch_info(ytdlp: list[str], url: str) -> dict:
    code, out = run_ytdlp(ytdlp, ["--dump-single-json", "--no-warnings", "--skip-download", url],
                          timeout=120)
    if code != 0:
        raise SystemExit(f"Could not read metadata.\n\n{explain_failure(out)}")
    try:
        data = json.loads(out[out.index("{"):out.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        raise SystemExit("yt-dlp returned unparseable metadata.\n\n" + explain_failure(out))

    subs = sorted((data.get("subtitles") or {}).keys())
    autos = sorted((data.get("automatic_captions") or {}).keys())
    return {
        "id": data.get("id"),
        "title": data.get("title"),
        "uploader": data.get("uploader") or data.get("channel"),
        "upload_date": data.get("upload_date"),
        "duration_seconds": data.get("duration"),
        "webpage_url": data.get("webpage_url"),
        "description": (data.get("description") or "")[:4000],
        "chapters": [
            {"start": c.get("start_time"), "end": c.get("end_time"), "title": c.get("title")}
            for c in (data.get("chapters") or [])
        ],
        "subtitle_languages": subs,
        "automatic_caption_languages": autos[:40],
        "has_human_subtitles": bool(subs),
    }


def fetch_captions(
    ytdlp: list[str], url: str, out_dir: Path, media_id: str, lang: str, auto_ok: bool
) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".captions-", dir=out_dir) as temp_name:
        temp_dir = Path(temp_name)
        args = [
            "--skip-download", "--write-subs",
            "--sub-langs", lang, "--sub-format", "vtt/srt/best",
            "--no-warnings",
            "-o", str(temp_dir / f"{media_id}.%(ext)s"),   # yt-dlp adds the language itself: ID.en.vtt
        ]
        if auto_ok:
            args.insert(2, "--write-auto-subs")
        code, out = run_ytdlp(ytdlp, args + [url])
        if code != 0:
            raise SystemExit(f"Caption retrieval failed (exit {code}).\n\n{explain_failure(out)}")
        fresh = sorted(temp_dir.glob(f"{media_id}*.vtt"))
        fresh += sorted(temp_dir.glob(f"{media_id}*.srt"))
        if not fresh:
            raise SystemExit(
                f"No caption files were written (yt-dlp exit {code}).\n\n{explain_failure(out)}"
            )
        files = []
        for source in fresh:
            destination = out_dir / source.name
            source.replace(destination)
            files.append(str(destination))
        return files


def fetch_media(
    ytdlp: list[str], url: str, out_dir: Path, media_id: str, audio_only: bool
) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".media-", dir=out_dir) as temp_name:
        temp_dir = Path(temp_name)
        if audio_only:
            args = ["-f", "bestaudio/best", "-x", "--audio-format", "wav",
                    "--postprocessor-args", "-ac 1 -ar 16000"]
        else:
            args = ["-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                    "--merge-output-format", "mp4"]
        args += ["--no-warnings", "-o", str(temp_dir / f"{media_id}.%(ext)s"), url]
        code, out = run_ytdlp(ytdlp, args, timeout=1800)
        if code != 0:
            raise SystemExit(f"Download failed (exit {code}).\n\n{explain_failure(out)}")
        exts = ("*.wav",) if audio_only else ("*.mp4", "*.mkv", "*.webm")
        files = [p for ext in exts for p in temp_dir.glob(f"{media_id}{ext[1:]}")]
        if not files:
            leftovers = [p for p in temp_dir.iterdir() if p.is_file()]
            manifest = [p for p in leftovers if p.suffix.lower() in MANIFEST_SUFFIXES]
            if manifest:
                out += (f"\n{MANIFEST_MARKER}: {manifest[0].name} ({manifest[0].stat().st_size} bytes) "
                        "was written and reported as the download")
            raise SystemExit("Download reported success but produced no media file.\n\n" + explain_failure(out))
        source = max(files, key=lambda p: p.stat().st_mtime)
        destination = out_dir / source.name
        source.replace(destination)
        return str(destination)


def main() -> int:
    safe_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url")
    parser.add_argument("--out-dir", default="video-work")
    parser.add_argument("--lang", default="en", help="Subtitle language(s), e.g. en or 'en.*,zh-Hans'.")
    parser.add_argument("--info", action="store_true", help="Metadata and chapters only.")
    parser.add_argument("--captions", action="store_true", help="Subtitle files only (default).")
    parser.add_argument("--audio", action="store_true", help="Audio track only, 16k mono wav.")
    parser.add_argument("--video", action="store_true", help="Video file, for frame extraction.")
    parser.add_argument("--no-auto-subs", action="store_true", help="Human-written subtitles only.")
    parser.add_argument("--cookies-from-browser", metavar="BROWSER",
                        help="OFF unless given. Let yt-dlp use the login of this browser ("
                             + ", ".join(LOGIN_BROWSERS) + ") for a video the user's account can already "
                             "watch. The agent must have the user's explicit yes before adding it, every time. "
                             "Never detected, never a default, never an automatic retry.")
    parser.add_argument("--browser-profile", metavar="PROFILE",
                        help="With --cookies-from-browser: the browser profile to read, when not the default.")
    parser.add_argument("--detail", choices=["transcript", "efficient", "balanced", "full"],
                        help="Choose what to fetch by detail level instead of the flags above. transcript = "
                             "captions only and NO media download when captions exist (audio only when they "
                             "do not); efficient / balanced / full = captions plus the video file.")
    args = parser.parse_args()
    if args.detail:
        if args.info or args.captions or args.audio or args.video:
            raise SystemExit("--detail replaces --info/--captions/--audio/--video; give one or the other.")
        args.captions = True
        args.video = args.detail != "transcript"

    LOGIN_STATE["args"] = login_args(args.cookies_from_browser, args.browser_profile)
    LOGIN_STATE["browser"] = args.cookies_from_browser.strip().lower() if args.cookies_from_browser else None
    if LOGIN_STATE["browser"]:
        print(LOGIN_WARNING.format(browser=LOGIN_STATE["browser"]) + "\n", file=sys.stderr)
    ytdlp = require_ytdlp()
    ytdlp_age_note(ytdlp)          # remembered, and shown with any failure below
    base_out_dir = Path(args.out_dir).expanduser().resolve()
    info = fetch_info(ytdlp, args.url)
    media_id = safe_media_id(str(info.get("id") or "media"))
    out_dir = base_out_dir / media_id
    result: dict = {"url": args.url, "out_dir": str(out_dir)}
    # What goes on record is THAT a browser login was used and which browser - nothing about the account.
    result["login_identity"] = ({"used": True, "browser": LOGIN_STATE["browser"],
                                 "manifest_hint": "evidence_manifest.py route ... --browser-login "
                                                  + LOGIN_STATE["browser"]}
                                if LOGIN_STATE["browser"] else {"used": False})
    result["info"] = info

    if not args.info:
        want_captions = args.captions or not (args.audio or args.video)
        human_subs = info.get("subtitle_languages") or []
        auto_subs = info.get("automatic_caption_languages") or []
        if want_captions and not human_subs and (args.no_auto_subs or not auto_subs):
            # Not an error: the metadata already says there is nothing to fetch.
            result["captions"] = []
            result["captions_available"] = False
            result["captions_note"] = (
                "This video has no human-written caption track"
                + (" (automatic captions exist but --no-auto-subs was given)." if auto_subs else
                   " and no automatic captions. Captions are not obtainable through Route A; "
                   "transcribe the audio (--audio) instead."))
            print("\nNO CAPTIONS: " + result["captions_note"], file=sys.stderr)
        elif want_captions:
            result["captions"] = fetch_captions(ytdlp, args.url, out_dir, media_id, args.lang,
                                                auto_ok=not args.no_auto_subs)
            result["captions_available"] = True
        if args.detail == "transcript":
            got = bool(result.get("captions"))
            result["detail"] = "transcript"
            if got:
                result["media_downloaded"] = False
                result["detail_note"] = ("Captions were obtained, so no audio or video was downloaded. "
                                         "This is captions-only evidence: nothing was seen or heard.")
            else:
                args.audio = True
                result["media_downloaded"] = "audio"
                result["detail_note"] = ("No captions could be obtained, so the audio track was downloaded "
                                         "for transcription. No video was downloaded: visual evidence is none.")
            print("\nDETAIL transcript: " + result["detail_note"], file=sys.stderr)
        elif args.detail:
            result["detail"] = args.detail
        if args.audio:
            result["audio"] = fetch_media(ytdlp, args.url, out_dir, media_id, audio_only=True)
        if args.video:
            result["video"] = fetch_media(ytdlp, args.url, out_dir, media_id, audio_only=False)

    dur = info.get("duration_seconds")
    dur = f"{dur:g}s" if isinstance(dur, (int, float)) else "duration unknown"
    print(f"\n{info.get('title')}  [{dur}]  chapters={len(info['chapters'])}  "
          f"human_subs={info['has_human_subtitles']}", file=sys.stderr)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
