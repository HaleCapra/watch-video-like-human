#!/usr/bin/env python3
"""Optional cloud speech recognition - OFF by default (v5.3).

The normal path needs no key and uploads nothing: captions first, then a local Whisper. This
script exists for the case where neither is available and the user has chosen to send the audio
to a transcription service they have an account with (Groq, OpenAI, or any OpenAI-compatible
`/audio/transcriptions` endpoint).

It never runs by accident. All three of these must be true:
  1. a backend is named        --backend groq|openai|custom   or   WVLH_ASR_BACKEND
  2. the key is in the environment (never on the command line, never printed):
         WVLH_ASR_API_KEY   - or GROQ_API_KEY / OPENAI_API_KEY for that same provider
  3. the upload is confirmed   --confirm-upload
Without 1 it prints how to enable it and exits 0. Without 3 it prints exactly what would be
uploaded, and to which host, and exits 0. A key alone does nothing, and one provider's key is
never sent to another provider.

  WVLH_ASR_BASE_URL   endpoint base for `custom` (e.g. https://host/v1); optional override otherwise
  WVLH_ASR_MODEL      model name (defaults: groq whisper-large-v3, openai whisper-1)

What it does: extracts mono 16 kHz MP3 with ffmpeg; if that is larger than 24,000,000 bytes it is
cut into chunks, each chunk is uploaded on its own and its timestamps are shifted back to the
source clock. A chunk that fails is not retried on another provider and is not papered over: it
is written to `failed_chunks` with its time range, the transcript is marked incomplete, and the
exit code is 2. Uses only the standard library.

  python transcribe_cloud.py WORK/audio.wav --out WORK/transcript --backend groq --confirm-upload

Outputs OUT.json ({"segments": [...], "failed_chunks": [...], "complete": true|false, ...}) and
OUT.srt. Register it as `--kind transcript --transcript-source cloud-asr`: the audio rating is
still `transcribed`, and the disclosure names the service that did it.

The temporary audio lives in a folder this run creates and removes; nothing else is deleted.
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
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlparse

MAX_UPLOAD_BYTES = 24_000_000
MULTIPART_MARGIN = 64_000
BACKENDS = {
    "groq": {"base": "https://api.groq.com/openai/v1", "model": "whisper-large-v3", "key": "GROQ_API_KEY"},
    "openai": {"base": "https://api.openai.com/v1", "model": "whisper-1", "key": "OPENAI_API_KEY"},
    "custom": {"base": None, "model": None, "key": None},
}
HOW_TO_ENABLE = (
    "Cloud transcription is off (the default). Nothing was uploaded.\n"
    "Prefer captions or a local Whisper. To use a cloud service you have an account with:\n"
    "  1. put the key in the environment as WVLH_ASR_API_KEY (never on the command line)\n"
    "  2. choose it: --backend groq|openai|custom  (custom also needs WVLH_ASR_BASE_URL and WVLH_ASR_MODEL)\n"
    "  3. confirm: --confirm-upload   (the audio leaves this machine)\n")


def safe_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass


def scrub(text: str, key: str | None) -> str:
    """Remove the key from anything that is about to be printed or stored."""
    text = str(text)
    return text.replace(key, "[key removed]") if key else text


def resolve_backend(name: str | None, env: dict) -> dict | None:
    """Return the endpoint, model and key for the chosen backend, or None when none is chosen."""
    name = (name or env.get("WVLH_ASR_BACKEND") or "").strip().lower()
    if not name or name == "none":
        return None
    if name not in BACKENDS:
        raise SystemExit(f"Unknown backend '{name}'. Choose groq, openai or custom.")
    spec = BACKENDS[name]
    base = (env.get("WVLH_ASR_BASE_URL") or spec["base"] or "").rstrip("/")
    model = env.get("WVLH_ASR_MODEL") or spec["model"]
    # The provider's own variable is used only for that provider. WVLH_ASR_API_KEY is the explicit one.
    key = env.get("WVLH_ASR_API_KEY") or (env.get(spec["key"]) if spec["key"] else None)
    missing = [label for label, value in (("WVLH_ASR_BASE_URL", base), ("WVLH_ASR_MODEL", model),
                                          ("WVLH_ASR_API_KEY", key)) if not value]
    parsed = urlparse(base) if base else None
    if parsed and (parsed.scheme not in ("https", "http") or not parsed.hostname):
        raise SystemExit("WVLH_ASR_BASE_URL must be an http(s) URL.")
    if parsed and parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("WVLH_ASR_BASE_URL must use https (plain http is accepted only for localhost).")
    return {"name": name, "base": base, "model": model, "key": key, "missing": missing,
            "host": parsed.hostname if parsed else None}


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          stdin=subprocess.DEVNULL)


def media_duration(ffprobe: str, path: Path) -> float:
    proc = run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    try:
        return float(proc.stdout.strip())
    except ValueError:
        raise SystemExit(f"Could not read the duration of {path}: {proc.stderr.strip()[-300:]}")


def plan_chunks(total_seconds: float, total_bytes: int, max_bytes: int) -> list[tuple[float, float]]:
    """Contiguous (offset, duration) pieces, each expected to stay under max_bytes."""
    if total_seconds <= 0 or max_bytes <= 0:
        raise SystemExit("Invalid audio duration or upload budget.")
    count = max(1, math.ceil(total_bytes / max_bytes))
    if count > 1:
        count += 1  # headroom: a constant bitrate is not perfectly constant
    size = total_seconds / count
    plan = []
    for i in range(count):
        offset = i * size
        plan.append((round(offset, 3), round(total_seconds - offset if i == count - 1 else size, 3)))
    return plan


def encode_audio(ffmpeg: str, source: Path, target: Path, offset: float | None = None,
                 duration: float | None = None) -> None:
    cmd = [ffmpeg, "-y", "-hide_banner", "-nostdin"]
    if offset is not None:
        cmd += ["-ss", f"{offset:.3f}", "-t", f"{duration:.3f}"]
    cmd += ["-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", "-f", "mp3", str(target)]
    proc = run(cmd)
    if proc.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        raise SystemExit(f"ffmpeg could not extract audio from {source}:\n{proc.stderr[-800:]}")


def multipart(fields: dict[str, str], file_path: Path) -> tuple[bytes, str]:
    boundary = "----wvlh" + uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
                  "Content-Type: audio/mpeg\r\n\r\n").encode("utf-8"))
    parts.append(file_path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def post_audio(backend: dict, audio: Path, language: str | None, timeout: float, retries: int = 1) -> list[dict]:
    """Upload one file. Returns its segments (times relative to this file). Raises RuntimeError."""
    fields = {"model": backend["model"], "response_format": "verbose_json"}
    if language:
        fields["language"] = language
    body, content_type = multipart(fields, audio)
    url = backend["base"] + "/audio/transcriptions"
    last = "unknown error"
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": "Bearer " + backend["key"], "Content-Type": content_type,
            "User-Agent": "watch-video-like-human/5.3"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8", "replace"))
            segments = data.get("segments")
            if not isinstance(segments, list):
                text = str(data.get("text", "")).strip()
                # No timestamps came back: one block for the whole file, honestly chunk-level.
                return [{"start": 0.0, "end": None, "text": text}] if text else []
            return [{"start": float(s.get("start", 0)), "end": float(s.get("end", s.get("start", 0))),
                     "text": " ".join(str(s.get("text", "")).split())}
                    for s in segments if str(s.get("text", "")).strip()]
        except urllib.error.HTTPError as exc:
            detail = exc.read(600).decode("utf-8", "replace") if exc.fp else ""
            last = f"HTTP {exc.code} {scrub(detail, backend['key']).strip()[:300]}"
            if exc.code not in (429, 500, 502, 503, 504) or attempt == retries:
                break
            time.sleep(min(5.0, 1.5 * (attempt + 1)))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as exc:
            last = scrub(f"{type(exc).__name__}: {exc}", backend["key"])[:300]
            if attempt == retries:
                break
            time.sleep(1.0)
    raise RuntimeError(last)


def srt_time(value: float) -> str:
    millis = int(round(max(0.0, value) * 1000))
    return f"{millis // 3600000:02d}:{millis % 3600000 // 60000:02d}:{millis % 60000 // 1000:02d},{millis % 1000:03d}"


def main() -> int:
    safe_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("media", help="Local audio or video file.")
    parser.add_argument("--out", required=True, help="Output path without extension (OUT.json and OUT.srt).")
    parser.add_argument("--backend", choices=sorted(BACKENDS) + ["none"],
                        help="Which service to use. Without it (and without WVLH_ASR_BACKEND) nothing runs.")
    parser.add_argument("--confirm-upload", action="store_true",
                        help="Required to actually upload. Without it the plan is printed and nothing leaves the machine.")
    parser.add_argument("--language", help="Spoken language hint, e.g. zh or en.")
    parser.add_argument("--timeout", type=float, default=300.0, help="Seconds per upload.")
    parser.add_argument("--max-upload-bytes", type=int, default=MAX_UPLOAD_BYTES,
                        help="Lower the per-file upload budget (it cannot be raised above 24,000,000).")
    args = parser.parse_args()

    backend = resolve_backend(args.backend, dict(os.environ))
    if backend is None:
        print(HOW_TO_ENABLE, file=sys.stderr)
        print(json.dumps({"ran": False, "reason": "no backend selected", "uploaded": False}))
        return 0
    if backend["missing"]:
        print(f"Backend '{backend['name']}' was selected but is not ready. Missing: "
              f"{', '.join(backend['missing'])}. Nothing was uploaded. The key is read from the "
              "environment only; do not pass it as an argument or paste it into a command.", file=sys.stderr)
        print(json.dumps({"ran": False, "reason": "backend not configured", "missing": backend["missing"],
                          "uploaded": False}))
        return 0

    source = Path(args.media).expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"File not found: {source}")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise SystemExit("ffmpeg and ffprobe are needed to prepare the audio.")
    cap = max(1, min(args.max_upload_bytes, MAX_UPLOAD_BYTES))
    budget = cap - min(MULTIPART_MARGIN, cap // 10)   # room for the multipart framing
    if budget <= 0:
        raise SystemExit("--max-upload-bytes is too small.")
    out_base = Path(args.out).expanduser().resolve()
    out_base.parent.mkdir(parents=True, exist_ok=True)

    work = Path(tempfile.mkdtemp(prefix="wvlh-cloud-asr-"))   # this run's own folder; removed at the end
    try:
        full = work / "audio.mp3"
        encode_audio(ffmpeg, source, full)
        duration = media_duration(ffprobe, full)
        size = full.stat().st_size
        plan = [(0.0, duration)] if size <= budget else plan_chunks(duration, size, budget)
        summary = {"backend": backend["name"], "endpoint_host": backend["host"], "model": backend["model"],
                   "audio_seconds": round(duration, 3), "audio_bytes": size, "chunks": len(plan)}
        if not args.confirm_upload:
            print(f"Would upload {size} bytes of audio ({duration:.0f} s, {len(plan)} chunk(s)) to "
                  f"{backend['host']} for transcription. Nothing was uploaded. Ask the user, then re-run "
                  "with --confirm-upload.", file=sys.stderr)
            print(json.dumps({"ran": False, "reason": "upload not confirmed", "uploaded": False, **summary}))
            return 0

        pieces: list[tuple[Path, float, float]] = []
        if len(plan) == 1:
            pieces.append((full, 0.0, duration))
        else:
            for index, (offset, length) in enumerate(plan):
                piece = work / f"chunk_{index:03d}.mp3"
                encode_audio(ffmpeg, full, piece, offset, length)
                if piece.stat().st_size > MAX_UPLOAD_BYTES:
                    raise SystemExit("A chunk is still over the upload budget; nothing was uploaded.")
                pieces.append((piece, offset, length))

        segments: list[dict] = []
        failed: list[dict] = []
        for index, (piece, offset, length) in enumerate(pieces):
            try:
                found = post_audio(backend, piece, args.language, args.timeout)
            except RuntimeError as exc:
                failed.append({"chunk": index + 1, "start": round(offset, 3), "end": round(offset + length, 3),
                               "error": str(exc)})
                print(f"chunk {index + 1}/{len(pieces)} FAILED ({offset:.0f}-{offset + length:.0f} s): {exc}",
                      file=sys.stderr)
                continue
            for seg in found:
                end = seg["end"] if seg["end"] is not None else length
                segments.append({"start": round(seg["start"] + offset, 3), "end": round(end + offset, 3),
                                 "text": seg["text"]})
            print(f"chunk {index + 1}/{len(pieces)} ok: {len(found)} segments", file=sys.stderr)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if failed and len(failed) == len(pieces):
        print("Every upload failed. No transcript was written. Report this and ask the user how to "
              "proceed; do not switch to another service on your own.", file=sys.stderr)
        print(json.dumps({"ran": True, "uploaded": True, "complete": False, "segments": 0,
                          "failed_chunks": failed, **summary}))
        return 1

    segments.sort(key=lambda s: s["start"])
    result = {"source": str(source), "transcript_source": "cloud-asr", "segments": segments,
              "failed_chunks": failed, "complete": not failed, **summary,
              "note": "Speech recognised by a third-party cloud service from the real audio track."
                      + (" INCOMPLETE: the ranges in failed_chunks have no transcript." if failed else "")}
    json_path, srt_path = out_base.with_suffix(".json"), out_base.with_suffix(".srt")
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    srt_path.write_text("".join(f"{n}\n{srt_time(s['start'])} --> {srt_time(max(s['end'], s['start'] + 0.2))}\n"
                                f"{s['text']}\n\n" for n, s in enumerate(segments, start=1)), encoding="utf-8")
    if failed:
        print("Some chunks failed. The transcript is INCOMPLETE; say which ranges are missing. Do not "
              "fill them from another service without asking.", file=sys.stderr)
    print(json.dumps({"ran": True, "uploaded": True, "complete": not failed, "segments": len(segments),
                      "failed_chunks": failed, "json": str(json_path), "srt": str(srt_path), **summary}))
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
