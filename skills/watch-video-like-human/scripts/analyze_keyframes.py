#!/usr/bin/env python3
"""Optional, pluggable per-keyframe analysis by an EXTERNAL OCR engine or vision model.

OFF BY DEFAULT. The default path of this skill is the model looking at the frames itself.
This script does nothing unless the user explicitly selects a backend, and it adds no
dependency: it only shells out to a tool the user already installed, or makes one HTTPS call
with the standard library to an endpoint and key the user supplied.

Everything it produces is SECOND-HAND evidence: an external engine's reading or an external
model's description of a frame, not something the answering model saw. It can never raise an
evidence rating above what the model's own inspection of the frames supports.

Backends (choose with --backend or the WVLH_KEYFRAME_BACKEND environment variable)
-------------------------------------------------------------------------------
  none        default. Prints how to enable a backend and exits 0.
  tesseract   local OCR. Needs the `tesseract` binary on PATH. Frames stay on this machine.
              Optional: WVLH_TESSERACT_LANG (e.g. "chi_sim+eng").
  vlm         an OpenAI-compatible chat-completions endpoint. Needs WVLH_VLM_API_KEY,
              WVLH_VLM_BASE_URL and WVLH_VLM_MODEL. FRAMES ARE UPLOADED to that service.
  command     any program. WVLH_KEYFRAME_COMMAND is a command line containing {image};
              it must print the result (plain text, or JSON with "text"/"description").

Examples
--------
  python analyze_keyframes.py --frames WORK/frames.json                  # no backend: explains, exits 0
  WVLH_KEYFRAME_BACKEND=tesseract python analyze_keyframes.py --frames WORK/frames.json
  python analyze_keyframes.py --frames WORK/frames.json --backend vlm --only 3,7,12
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
import base64
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

SECOND_HAND_LABELS = {
    "ocr": "external OCR text (second-hand)",
    "description": "external model description (second-hand)",
}
DEFAULT_PROMPT = ("Describe this video frame factually in under 80 words: the scene, any visible text "
                  "verbatim, and any chart, code or interface shown. Do not guess what is not visible.")
HOW_TO_ENABLE = """analyze_keyframes.py: no backend configured, so nothing was analysed. This is the normal case.

The default path of this skill is for the model to look at the extracted frames itself.
External OCR / vision analysis is optional, off by default, and always second-hand evidence.

To enable one explicitly:
  tesseract : install Tesseract yourself, then  --backend tesseract   (frames stay local)
  vlm       : set WVLH_VLM_API_KEY, WVLH_VLM_BASE_URL, WVLH_VLM_MODEL, then  --backend vlm
              (frames are uploaded to that service)
  command   : set WVLH_KEYFRAME_COMMAND="your-tool {image}", then  --backend command
Or set WVLH_KEYFRAME_BACKEND to one of those names."""


class BackendUnavailable(Exception):
    """The selected backend is missing something the user must provide."""


def safe_stdio() -> None:
    """Never let a character the console cannot encode crash the script (cp936, cp1252, ...)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass


def decode_output(data) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        import locale
        return data.decode(locale.getpreferredencoding(False) or "utf-8", errors="replace")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------- backends

def backend_tesseract(env: dict) -> dict:
    binary = shutil.which("tesseract")
    if not binary:
        raise BackendUnavailable("backend 'tesseract' was selected but the `tesseract` binary is not on PATH. "
                                 "This skill does not install it.")
    lang = env.get("WVLH_TESSERACT_LANG", "")

    def analyse(image: Path) -> dict:
        cmd = [binary, str(image), "stdout"] + (["-l", lang] if lang else [])
        proc = subprocess.run(cmd, capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
        if proc.returncode != 0:
            raise RuntimeError(decode_output(proc.stderr).strip()[-300:] or f"tesseract exit {proc.returncode}")
        return {"kind": "ocr", "text": decode_output(proc.stdout).strip()}

    return {"name": "tesseract", "engine": f"tesseract{' -l ' + lang if lang else ''}",
            "frames_leave_machine": False, "analyse": analyse}


def backend_vlm(env: dict, prompt: str) -> dict:
    missing = [k for k in ("WVLH_VLM_API_KEY", "WVLH_VLM_BASE_URL", "WVLH_VLM_MODEL") if not env.get(k)]
    if missing:
        raise BackendUnavailable("backend 'vlm' was selected but these environment variables are not set: "
                                 + ", ".join(missing) + ". The user must supply their own endpoint and key.")
    url = env["WVLH_VLM_BASE_URL"].rstrip("/") + "/chat/completions"
    model = env["WVLH_VLM_MODEL"]
    key = env["WVLH_VLM_API_KEY"]

    def analyse(image: Path) -> dict:
        data_url = "data:image/jpeg;base64," + base64.b64encode(image.read_bytes()).decode("ascii")
        body = json.dumps({"model": model, "max_tokens": 400, "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_url}}]}]}).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code} from the vision endpoint") from None
        except urllib.error.URLError as exc:
            raise RuntimeError(f"could not reach the vision endpoint: {exc.reason}") from None
        content = payload["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
        return {"kind": "description", "text": str(content).strip()}

    return {"name": "vlm", "engine": model, "frames_leave_machine": True, "analyse": analyse}


def backend_command(env: dict) -> dict:
    template = env.get("WVLH_KEYFRAME_COMMAND", "")
    if "{image}" not in template:
        raise BackendUnavailable("backend 'command' was selected but WVLH_KEYFRAME_COMMAND is not set to a "
                                 "command line containing {image}.")
    kind = env.get("WVLH_KEYFRAME_COMMAND_KIND", "description")
    if kind not in SECOND_HAND_LABELS:
        raise BackendUnavailable("WVLH_KEYFRAME_COMMAND_KIND must be 'ocr' or 'description'.")

    def analyse(image: Path) -> dict:
        parts = [part.replace("{image}", str(image)) for part in shlex.split(template, posix=(os.name != "nt"))]
        parts = [p[1:-1] if len(p) > 1 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]
        proc = subprocess.run(parts, capture_output=True, timeout=180, stdin=subprocess.DEVNULL)
        out = decode_output(proc.stdout).strip()
        if proc.returncode != 0:
            raise RuntimeError(decode_output(proc.stderr).strip()[-300:] or f"command exit {proc.returncode}")
        try:
            parsed = json.loads(out)
            if isinstance(parsed, dict):
                out = str(parsed.get("text") or parsed.get("description") or "").strip()
        except json.JSONDecodeError:
            pass
        return {"kind": kind, "text": out}

    return {"name": "command", "engine": template.split()[0], "frames_leave_machine": None, "analyse": analyse}


def select_backend(name: str, env: dict, prompt: str) -> dict | None:
    if name in ("", "none"):
        return None
    if name == "tesseract":
        return backend_tesseract(env)
    if name == "vlm":
        return backend_vlm(env, prompt)
    if name == "command":
        return backend_command(env)
    raise BackendUnavailable(f"unknown backend {name!r}; choose none, tesseract, vlm or command.")


# ---------------------------------------------------------------- main

def pick_frames(frames: list[dict], only: str | None, max_frames: int) -> list[dict]:
    if only:
        wanted = {int(x) for x in only.split(",") if x.strip()}
        frames = [f for f in frames if int(f.get("index", 0)) in wanted]
    if max_frames > 0 and len(frames) > max_frames:
        step = (len(frames) - 1) / (max_frames - 1) if max_frames > 1 else 0
        frames = [frames[round(i * step)] for i in range(max_frames)]
    return frames


def analyse_frames(frames_json: Path, backend: dict, only: str | None, max_frames: int) -> dict:
    meta = json.loads(frames_json.read_text(encoding="utf-8"))
    frames_dir = Path(meta.get("frames_dir", frames_json.parent / "frames"))
    if not frames_dir.is_dir():
        frames_dir = frames_json.parent / "frames"
    results = []
    for frame in pick_frames(meta.get("frames", []), only, max_frames):
        image = frames_dir / frame["file"]
        entry = {"index": frame.get("index"), "time_seconds": frame["time_seconds"], "file": str(image)}
        if not image.is_file():
            entry["error"] = "frame file missing"
            results.append(entry)
            continue
        entry["frame_sha256"] = sha256_file(image)
        try:
            found = backend["analyse"](image)
            entry.update({"kind": found["kind"], "text": found["text"],
                          "evidence_label": SECOND_HAND_LABELS[found["kind"]]})
        except Exception as exc:  # noqa: BLE001 - one bad frame must not lose the rest
            entry["error"] = f"{type(exc).__name__}: {exc}"[:300]
        results.append(entry)
    return {
        "schema": "keyframe-analysis/1",
        "second_hand": True,
        "disclosure": ("Produced by an external OCR engine or vision model, not by the answering model "
                       "looking at the frames. Label every use of it as second-hand; it never counts as "
                       "frames inspected and never raises an evidence rating."),
        "backend": backend["name"],
        "engine": backend["engine"],
        "frames_leave_machine": backend["frames_leave_machine"],
        "source_frames_json": str(frames_json),
        "total_frames_available": len(meta.get("frames", [])),
        "analysed": sum(1 for r in results if "error" not in r),
        "failed": sum(1 for r in results if "error" in r),
        "results": results,
    }


def main() -> int:
    safe_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frames", required=True, help="frames.json from extract_media_assets.py.")
    parser.add_argument("--output", help="Result path (default: keyframe_analysis.json next to frames.json).")
    parser.add_argument("--backend", choices=["none", "tesseract", "vlm", "command"],
                        help="Explicit backend. Default: WVLH_KEYFRAME_BACKEND, else none.")
    parser.add_argument("--only", help="Comma-separated frame indexes to analyse, e.g. 3,7,12.")
    parser.add_argument("--max-frames", type=int, default=12,
                        help="Upper bound on frames sent to the backend (default 12; 0 = no bound).")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Prompt for the vlm backend.")
    args = parser.parse_args()

    frames_json = Path(args.frames).expanduser().resolve()
    if not frames_json.is_file():
        raise SystemExit(f"frames.json not found: {frames_json}")
    name = (args.backend or os.environ.get("WVLH_KEYFRAME_BACKEND", "none")).strip().lower()

    try:
        backend = select_backend(name, dict(os.environ), args.prompt)
    except BackendUnavailable as exc:
        # A missing optional backend is not a failure of the analysis: explain and carry on.
        print(f"analyze_keyframes.py: {exc}\nNothing was analysed. The main workflow is unaffected: "
              "look at the frames yourself.", file=sys.stderr)
        print(json.dumps({"ran": False, "backend": name, "reason": str(exc)}))
        return 0
    if backend is None:
        print(HOW_TO_ENABLE, file=sys.stderr)
        print(json.dumps({"ran": False, "backend": "none", "reason": "no backend configured"}))
        return 0

    if backend["frames_leave_machine"]:
        print(f"analyze_keyframes.py: uploading frames to the external service behind WVLH_VLM_BASE_URL "
              f"(model {backend['engine']}).", file=sys.stderr)
    report = analyse_frames(frames_json, backend, args.only, args.max_frames)
    output = Path(args.output).expanduser().resolve() if args.output else frames_json.parent / "keyframe_analysis.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"ran": True, "backend": report["backend"], "output": str(output),
                      "analysed": report["analysed"], "failed": report["failed"],
                      "second_hand": True, "frames_leave_machine": report["frames_leave_machine"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
