#!/usr/bin/env python3
"""Turn real audio into a timestamped SRT with whichever LOCAL Whisper is installed.

Nothing leaves the machine. One command for every backend, so the agent never has to write
transcription code by hand:

  python transcribe_local.py WORK/audio.wav --language en                # -> WORK/audio.srt (+ .json)
  python transcribe_local.py capture.mp4 --language zh --model small     # any media file
  python transcribe_local.py --self-test                                  # does a backend really run?
  python transcribe_local.py --list                                       # which backends are importable

Backends, tried in this order with --backend auto:
  faster-whisper   (pip install faster-whisper)   CPU int8 by default; fast on Intel and AMD
  mlx-whisper      (pip install mlx-whisper)      Apple Silicon only
  openai-whisper   (pip install openai-whisper)   the reference implementation

The backend must be importable from the Python that runs this script, or live in the private
environment that setup_tools.py creates (~/.watch-video-like-human/venv): when nothing is
importable here and that environment has a backend, the script restarts itself under that
interpreter and says so. `pipx install faster-whisper` does not work: the package ships no
command, and an isolated pipx environment is not importable from here anyway.

Word timestamps are always on: without them Whisper stretches the first segment back to 00:00
across a silent or music-only opening, which corrupts every alignment that follows.

The audio is decoded here (ffmpeg -> 16 kHz mono PCM, read with the standard library) and handed
to the backend as samples. That is deliberate: faster-whisper 1.2.x opens files through PyAV and
breaks with PyAV 19 (`open() got an unexpected keyword argument 'metadata_errors'`).

Two guards against invented text: a segment that lies entirely over digital silence is dropped
(Whisper prints "you" or "Thank you." there), and --max-end drops segments that begin after the
real content ends. Both are counted in the output.

`auto` names the backend it used. If one backend fails and another then succeeds, the output
lists the failure - an engine is never swapped without saying so.

Exit codes: 0 ok, 1 no usable backend or it failed, 2 bad input.
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
import importlib.util
import json
import shutil
import subprocess
import tempfile
import time
import wave
from pathlib import Path

BACKENDS = ["faster-whisper", "mlx-whisper", "openai-whisper"]
MODULES = {"faster-whisper": "faster_whisper", "mlx-whisper": "mlx_whisper", "openai-whisper": "whisper"}
INSTALL = ("No local Whisper backend is importable from this Python ({python}),\n"
           "and none was found in the private environment of setup_tools.py.\n"
           "See what would be installed - nothing is, without the user's yes:\n"
           "  python scripts/setup_tools.py --tier whisper\n"
           "or install one INTO THIS interpreter yourself:  {python} -m pip install faster-whisper\n"
           "(not pipx: faster-whisper has no command line of its own). Otherwise use captions, or ask\n"
           "the user about cloud transcription (scripts/transcribe_cloud.py, off by default).")


def safe_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def private_python() -> str | None:
    home = os.environ.get("WVLH_HOME") or os.path.join(os.path.expanduser("~"), ".watch-video-like-human")
    path = os.path.join(home, "venv", "Scripts", "python.exe") if os.name == "nt" else \
        os.path.join(home, "venv", "bin", "python")
    return path if os.path.isfile(path) else None


def private_home() -> str:
    return os.environ.get("WVLH_HOME") or os.path.join(os.path.expanduser("~"), ".watch-video-like-human")


def running_in_private() -> bool:
    """Is THIS interpreter the private environment's?

    Decided by sys.prefix, not by the executable's path: on Linux and macOS `venv/bin/python` is
    a symbolic link to the system Python, so resolving both paths makes them look identical while
    their site-packages are not (field test: the installed backend was never found).
    """
    venv = os.path.normcase(os.path.abspath(os.path.join(private_home(), "venv")))
    return os.path.normcase(os.path.abspath(sys.prefix)) == venv


MODEL_FETCH_MARKERS = ("modelhostunreachable", "did not answer within", "localentrynotfounderror", "connecterror", "network is unreachable", "connection refused",
                       "name or service not known", "temporary failure in name resolution", "max retries exceeded",
                       "couldn't connect", "could not connect", "timed out", "huggingface.co", "getaddrinfo failed",
                       "urlerror", "an error happened while trying to locate the file on the hub")


NUMPY_MISMATCH_MARKERS = ("numpy is not available", "compiled using numpy 1", "_array_api not found",
                          "numpy.core.multiarray failed to import")
INSTALL_PROBLEM_MARKERS = ("modulenotfounderror", "importerror", "no module named", "dll load failed",
                           "library not loaded", "symbol not found", "undefined symbol")


def failure_advice(errors: dict) -> str:
    """Name the likely cause of a total failure from the error text, instead of one fixed guess."""
    text = " ".join(errors.values()).lower()
    if any(marker in text for marker in MODEL_FETCH_MARKERS):
        return ("The model could not be downloaded: the model host did not answer from this network. "
                "faster-whisper fetches from huggingface.co - set HF_ENDPOINT to a mirror YOU trust, or put the "
                "model on this machine first and pass its folder as --model. openai-whisper fetches from "
                "openaipublic.azureedge.net. No mirror is chosen for you. Nothing was transcribed: do not "
                "report audio evidence.")
    if any(marker in text for marker in NUMPY_MISMATCH_MARKERS):
        return ("Nothing was transcribed: do not report audio evidence. This is an installation mismatch, not the "
                "GPU and not memory: the installed torch was built for NumPy 1.x and NumPy 2 is installed (seen on "
                "Intel Macs, whose last torch build is 2.2). Put NumPy 1.x into the same environment:\n"
                f'  uv pip install --python "{sys.executable}" "numpy<2"      (or: "{sys.executable}" -m pip install "numpy<2")\n'
                "or use the other engine: --backend faster-whisper.")
    if any(marker in text for marker in INSTALL_PROBLEM_MARKERS):
        return ("Nothing was transcribed: do not report audio evidence. The engine is installed but does not load "
                "(the error above names the missing or mismatched part). This is an installation problem, not the "
                "GPU and not memory: reinstall it (scripts/setup_tools.py --tier whisper shows how) or use another "
                "--backend.")
    return ("Nothing was transcribed: do not report audio evidence. A GPU error or a crash while the model "
            "loads usually means a GPU in a bad state or too little free memory - retry with --device cpu "
            "or a smaller --model.")


MODEL_PROBE_SECONDS = 8.0


def model_source(backend: str, model: str) -> dict:
    """Where this backend would get its model from, and whether it is already on this machine.

    Pure look-up: the cache folders the libraries use by default, and the host they download from.
    """
    home = os.path.expanduser("~")
    if os.path.isdir(model) or os.path.isfile(model):
        return {"cached": True, "where": model, "host": None}
    if backend == "openai-whisper":
        cache = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache"), "whisper")
        hit = os.path.isfile(os.path.join(cache, model + ".pt"))
        return {"cached": hit, "where": cache, "host": "https://openaipublic.azureedge.net"}
    hub = (os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
           or os.path.join(os.environ.get("HF_HOME") or os.path.join(os.environ.get("XDG_CACHE_HOME")
                                                                      or os.path.join(home, ".cache"), "huggingface"), "hub"))
    if "/" in model:
        repo = model
    elif backend == "mlx-whisper":
        repo = f"mlx-community/whisper-{model}-mlx"
    else:
        repo = f"Systran/faster-whisper-{model}"
    folder = os.path.join(hub, "models--" + repo.replace("/", "--"), "snapshots")
    hit = os.path.isdir(folder) and any(os.scandir(folder))
    return {"cached": bool(hit), "where": os.path.dirname(folder), "repo": repo,
            "host": (os.environ.get("HF_ENDPOINT") or "https://huggingface.co").rstrip("/"),
            "mirror": bool(os.environ.get("HF_ENDPOINT"))}


def host_answers(url: str, seconds: float = MODEL_PROBE_SECONDS) -> tuple[bool, str]:
    """One short, certificate-checked request. Any HTTP status means the host is there."""
    import urllib.error
    import urllib.request
    try:
        request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "watch-video-like-human"})
        with urllib.request.urlopen(request, timeout=seconds) as response:
            return True, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return True, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}"[:160]


def check_model(backend: str, model: str, skip: bool = False) -> None:
    """Fail in seconds, not minutes, when the model is not here and its host does not answer.

    Without this the download library retries for more than two minutes before giving up
    (measured: 135-138 s). No mirror is ever chosen for the user.
    """
    source = model_source(backend, model)
    if source["cached"] and not skip and source.get("repo") and "HF_HUB_OFFLINE" not in os.environ:
        # The model is on disk. Without this the hub library still goes online to look for updates and,
        # where its host does not answer, retries for minutes (measured: 146 s instead of 18 s).
        os.environ["HF_HUB_OFFLINE"] = "1"
        print(f"The {model!r} model is already on this machine ({source['where']}); using it without "
              "going online (HF_HUB_OFFLINE=1 for this run; --skip-model-check turns this off).",
              file=sys.stderr, flush=True)
    if source["cached"] or skip or not source.get("host"):
        return
    print(f"The {model!r} model is not on this machine yet; {backend} will download it from "
          f"{source['host']} (once). Checking that the host answers ...", file=sys.stderr, flush=True)
    ok, detail = host_answers(source["host"])
    if not ok:
        raise ModelHostUnreachable(
            f"model host {source['host']} did not answer within {MODEL_PROBE_SECONDS:g} s ({detail}); "
            f"the model is not in {source['where']}")
    print("The host answers. Downloading the model now - this can take several minutes and prints "
          "little; later runs use the copy on disk.", file=sys.stderr, flush=True)


class ModelHostUnreachable(RuntimeError):
    """The model would have to be downloaded and its host cannot be reached."""


def available() -> list[str]:
    found = []
    for name in BACKENDS:
        try:
            if importlib.util.find_spec(MODULES[name]) is not None:
                found.append(name)
        except (ImportError, ValueError):
            pass
    return found


def available_in(interpreter: str) -> list[str]:
    """Backends importable from another interpreter (the private environment)."""
    code = ("import importlib.util, json; print(json.dumps([n for n, m in %r.items() "
            "if importlib.util.find_spec(m) is not None]))" % MODULES)
    try:
        # -I: only what is installed in that environment counts, not PYTHONPATH or the current folder
        proc = subprocess.run([interpreter, "-I", "-c", code], capture_output=True, timeout=60,
                              stdin=subprocess.DEVNULL)
        return [n for n in BACKENDS if n in json.loads(proc.stdout.decode("utf-8", "replace") or "[]")]
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def timestamp(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def is_pcm16_mono_16k(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2
    except (wave.Error, EOFError, OSError):
        return False


def to_wav(source: Path, workdir: Path) -> Path:
    """Decode any media file to 16 kHz mono PCM16. A file already in that shape is used as is."""
    if is_pcm16_mono_16k(source):
        return source
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is needed to decode this file; it is not on PATH.")
    target = workdir / "audio16k.wav"
    proc = subprocess.run([ffmpeg, "-y", "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(source),
                           "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    if proc.returncode != 0 or not target.is_file():
        tail = (proc.stderr or "").strip().splitlines()[-1:] or ["ffmpeg failed"]
        raise SystemExit(f"Could not decode audio from {source.name}: {tail[0]}")
    return target


def load_samples(wav_path: Path):
    import numpy as np
    with wave.open(str(wav_path), "rb") as w:
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def run_faster_whisper(samples, model: str, language: str | None, device: str, compute_type: str):
    from faster_whisper import WhisperModel
    engine = WhisperModel(model, device=device, compute_type=compute_type)
    segments, info = engine.transcribe(samples, language=language, word_timestamps=True)
    return [(seg.start, seg.end, seg.text.strip()) for seg in segments], getattr(info, "language", language)


OPENAI_BEAM_SIZE = 5       # as in `python -m whisper`
OPENAI_BEST_OF = 5
SILENCE_PEAK = 10 ** (-66 / 20)   # about -66 dBFS: below this a span holds no sound at all


def drop_silent_segments(segments: list, samples) -> tuple[list, int]:
    """Whisper invents short lines ("you", "Thank you.") over digital silence.

    A segment whose whole span is silent in the samples cannot be speech, whatever the model
    printed. This checks the audio itself, not the model's confidence, so quiet real speech stays.
    """
    import numpy as np
    kept, dropped = [], 0
    for start, end, text in segments:
        a, b = max(0, int(start * 16000)), min(len(samples), int(end * 16000) + 1)
        peak = float(np.max(np.abs(samples[a:b]))) if b > a else 0.0
        if peak < SILENCE_PEAK:
            dropped += 1
        else:
            kept.append((start, end, text))
    return kept, dropped


FILLER_WORDS = {"oh", "ooh", "ah", "uh", "mm", "hm", "la", "na", "yeah", "you", "thank", "thanks", "music"}


def looks_like_noise(segments: list, audio_seconds: float | None = None) -> dict | None:
    """The text a recogniser prints over music with little or no voice: a few words or lines, repeated,
    scattered thinly over the track. A warning to settle, never a verdict (a real chorus looks the same)."""
    import re
    words = [w for _a, _b, text in segments for w in re.findall(r"[^\W_]+", text.lower())]
    if len(segments) < 2 or len(words) < 4:
        return None
    unique = len(set(words)) / len(words)
    filler = sum(1 for w in words if re.fullmatch(r"o+h+|a+h+|u+h+|m+|h+m+|(?:la)+|(?:na)+", w) or w in FILLER_WORDS) / len(words)
    tokens = [re.findall(r"[^\W_]+", text.lower()) for _a, _b, text in segments]
    keys = [" ".join(tok) for tok in tokens]

    def echo(tok: list) -> bool:
        half = len(tok) // 2
        return len(tok) >= 4 and len(tok) % 2 == 0 and tok[:half] == tok[half:]
    repeated = sum(1 for i, tok in enumerate(tokens)
                   if (keys[i] and keys.count(keys[i]) > 1) or echo(tok)
                   or (tok and all(re.fullmatch(r"o+h+|a+h+|u+h+|m+|h+m+|(?:la)+|(?:na)+", w) or w in FILLER_WORDS for w in tok))
                   ) / len(segments)
    spoken = sum(max(0.0, b - a) for a, b, _t in segments)
    share = spoken / audio_seconds if audio_seconds else None
    thin = bool(audio_seconds and audio_seconds >= 60 and share < 0.25)
    if unique < 0.2 or filler >= 0.6 or repeated >= 0.6 or (thin and repeated >= 0.4):
        return {"unique_word_ratio": round(unique, 2), "filler_word_share": round(filler, 2),
                "repeated_or_filler_segment_share": round(repeated, 2),
                "speech_share_of_audio": round(share, 2) if share is not None else None, "words": len(words)}
    return None


def run_mlx_whisper(samples, model: str, language: str | None):
    import mlx_whisper
    repo = model if "/" in model else f"mlx-community/whisper-{model}-mlx"
    result = mlx_whisper.transcribe(samples, path_or_hf_repo=repo, language=language, word_timestamps=True)
    return ([(seg["start"], seg["end"], seg["text"].strip()) for seg in result.get("segments", [])],
            result.get("language", language))


def run_openai_whisper(samples, model: str, language: str | None, device: str):
    import whisper
    # The default device here is the CPU, like faster-whisper's: a GPU in a bad state fails late
    # and obscurely (seen: "CUDA error: unknown error" after the model had loaded). --device cuda opts in.
    engine = whisper.load_model(model, device=None if device == "auto" else device)
    # beam_size / best_of are the `whisper` command's own defaults. The library function defaults to
    # greedy decoding, which is not the same recogniser: on a real recording it lost the first four
    # sentences (117 segments from 11.7 s, where the command gave 140 from 5.0 s).
    result = engine.transcribe(samples, language=language, word_timestamps=True, fp16=False,
                               beam_size=OPENAI_BEAM_SIZE, best_of=OPENAI_BEST_OF)
    return ([(seg["start"], seg["end"], seg["text"].strip()) for seg in result.get("segments", [])],
            result.get("language", language))


def transcribe(backend: str, samples, args: argparse.Namespace):
    if backend == "faster-whisper":
        return run_faster_whisper(samples, args.model, args.language, args.device, args.compute_type)
    if backend == "mlx-whisper":
        return run_mlx_whisper(samples, args.model, args.language)
    return run_openai_whisper(samples, args.model, args.language, args.device)


def self_test(args: argparse.Namespace, candidates: list[str]) -> int:
    """Importable is not runnable: transcribe one second of silence with each backend."""
    import numpy as np
    silence = np.zeros(16000, dtype=np.float32)
    args.model = args.model if args.model_given else "tiny"
    results = {}
    for backend in candidates:
        started = time.time()
        try:
            check_model(backend, args.model, args.skip_model_check)
            transcribe(backend, silence, args)
            results[backend] = {"ok": True, "seconds": round(time.time() - started, 1)}
        except Exception as exc:   # report the reason, whatever it is
            results[backend] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    usable = [name for name, r in results.items() if r["ok"]]
    print(json.dumps({"python": sys.executable, "model": args.model, "backends": results,
                      "usable": usable}, indent=2, ensure_ascii=False))
    if not usable:
        print(failure_advice({k: v.get("error", "") for k, v in results.items()}), file=sys.stderr)
    return 0 if usable else 1


def main() -> int:
    safe_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("media", nargs="?", help="audio.wav from extract_media_assets.py, or any media file")
    parser.add_argument("--output", "-o", help="SRT path (default: next to the input, same stem). A name without "
                                               ".srt gets it added; the JSON sidecar is written beside it.")
    parser.add_argument("--language", help="Spoken language code, e.g. en, zh, ja. Set it: auto-detection "
                                           "can pick the wrong language from a musical opening.")
    parser.add_argument("--model", default=None, help="Whisper model (default small)")
    parser.add_argument("--backend", default="auto", choices=["auto", *BACKENDS])
    parser.add_argument("--device", default="cpu", help="cpu (default), cuda, or auto")
    parser.add_argument("--compute-type", default="int8", help="faster-whisper compute type (default int8)")
    parser.add_argument("--max-end", type=float,
                        help="Where the real content ends, in seconds of this file. Segments that START after "
                             "it are dropped and counted (a recording that runs on after the video ended).")
    parser.add_argument("--skip-model-check", action="store_true",
                        help="Do not test in advance whether the model's download host answers (the check "
                             "only runs when the model is not on this machine yet, and takes at most 8 s).")
    parser.add_argument("--list", action="store_true", help="List importable backends and exit")
    parser.add_argument("--self-test", action="store_true",
                        help="Run each backend on one second of silence (downloads the tiny model once)")
    args = parser.parse_args()
    args.model_given = args.model is not None
    args.model = args.model or "small"

    found = available()
    private = private_python()
    same = running_in_private()
    wanted_here = found if args.backend == "auto" else [b for b in found if b == args.backend]
    if not wanted_here and private and not same and not os.environ.get("WVLH_NO_REEXEC"):
        elsewhere = available_in(private)
        if elsewhere and (args.backend == "auto" or args.backend in elsewhere):
            print(f"No requested backend in this Python; {', '.join(elsewhere)} found in the private "
                  f"environment. Re-running under {private}", file=sys.stderr)
            return _continue_under(private, "WVLH_NO_REEXEC")
    if args.list:
        print(json.dumps({"python": sys.executable, "importable": found,
                          "private_environment": private}, indent=2))
        return 0 if found else 1
    candidates = wanted_here
    if not candidates:
        if args.backend != "auto" and found:
            print(f"--backend {args.backend} is not installed in this Python. Installed: {', '.join(found)}. "
                  "Not switching backend on my own: name one of those, or use --backend auto.", file=sys.stderr)
            print(json.dumps({"ok": False, "reason": "requested_backend_missing", "importable": found}))
            return 1
        print(INSTALL.format(python=sys.executable), file=sys.stderr)
        print(json.dumps({"ok": False, "reason": "no_local_backend", "importable": found}))
        return 1
    if args.self_test:
        return self_test(args, candidates)
    if not args.media:
        parser.error("media file is required")
    source = Path(args.media).expanduser().resolve()
    if not source.is_file():
        print(f"File not found: {source}", file=sys.stderr)
        return 2
    output = Path(args.output).expanduser().resolve() if args.output else source.with_suffix(".srt")
    if output.suffix.lower() != ".srt":
        output = output.with_name(output.name + ".srt")     # --output WORK/audio means WORK/audio.srt
    if not args.language:
        print("NOTE: --language not given; the backend will guess from the first seconds.", file=sys.stderr)

    with tempfile.TemporaryDirectory(prefix="wvlh-asr-") as tmp:
        wav_path = to_wav(source, Path(tmp))
        samples = load_samples(wav_path)
    duration = len(samples) / 16000.0
    if duration <= 0:
        print("The file has no audio samples.", file=sys.stderr)
        return 2

    errors = {}
    for backend in candidates:
        started = time.time()
        print(f"Backend: {backend}, model {args.model}, device {args.device}. Local only; nothing is uploaded.",
              file=sys.stderr)
        try:
            check_model(backend, args.model, args.skip_model_check)
            segments, language = transcribe(backend, samples, args)
        except Exception as exc:
            errors[backend] = f"{type(exc).__name__}: {exc}"[:300]
            print(f"{backend} FAILED: {errors[backend]}", file=sys.stderr)
            continue
        segments = [seg for seg in segments if seg[2]]
        segments, silent_dropped = drop_silent_segments(segments, samples)
        late = []
        if args.max_end is not None:
            late = [seg for seg in segments if seg[0] > args.max_end]
            segments = [seg for seg in segments if seg[0] <= args.max_end]
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as handle:
            for number, (start, end, text) in enumerate(segments, 1):
                handle.write(f"{number}\n{timestamp(start)} --> {timestamp(end)}\n{text}\n\n")
        sidecar = output.with_suffix(".json")
        sidecar.write_text(json.dumps({
            "backend": backend, "model": args.model, "language": language, "source": source.name,
            "audio_seconds": round(duration, 2), "word_timestamps": True,
            "segments": [{"start": round(float(a), 3), "end": round(float(b), 3), "text": t} for a, b, t in segments],
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        elapsed = time.time() - started
        print(json.dumps({
            "ok": True, "output": str(output), "json": str(sidecar), "backend": backend, "model": args.model,
            "python": sys.executable, "language": language, "segments": len(segments),
            "audio_seconds": round(duration, 2), "elapsed_seconds": round(elapsed, 1),
            "speed": f"{duration / elapsed:.1f}x real time" if elapsed > 0 else None,
            "word_timestamps": True, "uploaded": False,
            "segments_dropped_over_silence": silent_dropped,
            "first_segment_start": round(float(segments[0][0]), 2) if segments else None,
            "decoding": ("beam 5 / best of 5, as the whisper command" if backend == "openai-whisper"
                         else "the backend's defaults"),
            "speech_doubt": looks_like_noise(segments, duration),
            "segments_dropped_after_max_end": [{"start": round(float(a), 2), "text": t} for a, _b, t in late],
            "backends_that_failed_first": errors,
            "manifest_hint": "evidence_manifest.py add --kind transcript --path OUTPUT --transcript-source asr",
            "note": "Speech recognised from the real audio track by a local model. Rate audio "
                    "'transcribed'; it was not listened to as sound."
                    + (" Another backend failed before this one - say so." if errors else ""),
        }, indent=2, ensure_ascii=False))
        if not segments:
            print("No speech was recognised (music, silence, or the wrong --language).", file=sys.stderr)
        elif looks_like_noise(segments, duration):
            print("WARNING: the text is mostly repeated lines or filler, thinly spread - what a recogniser prints "
                  "over music with little or no voice (run it again and it may print something else). Check that "
                  "somebody really speaks before rating audio 'transcribed'.", file=sys.stderr)
        return 0
    print(json.dumps({"ok": False, "reason": "all_backends_failed", "errors": errors,
                      "model_download_failed": "could not be downloaded" in failure_advice(errors)},
                     ensure_ascii=False))
    print(failure_advice(errors), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
