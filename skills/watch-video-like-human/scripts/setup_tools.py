#!/usr/bin/env python3
"""Find out what this machine is missing and offer to install it - never without a yes.

  python setup_tools.py                       # print the plan. Installs NOTHING.
  python setup_tools.py --yes                 # run the base tier of the plan that was shown
  python setup_tools.py --tier whisper        # plan for a local speech recogniser
  python setup_tools.py --tier whisper --yes  # install it (confirmed separately: it is large)
  python setup_tools.py --tier recording      # step-by-step guide for Route C; never automatic
  python setup_tools.py --json                # the same plan as data

Three tiers, each confirmed on its own:

  base       ffmpeg + ffprobe, a current yt-dlp, a usable Python
  whisper    a local speech recogniser (hundreds of MB to several GB, plus a model download)
  recording  loopback audio driver and screen-recording permission - a guide only, because
             these need an installer the user runs, an administrator password or a system switch

Rules this script keeps:

  * The default is a dry run. Nothing is installed, downloaded or changed without --yes.
  * It never runs sudo, doas, pkexec or runas, never asks for or types a password, and never
    pipes a download into a shell. A step that needs administrator rights is printed for the
    user to run themselves.
  * Python packages go into a private folder (~/.watch-video-like-human, or $WVLH_HOME), never
    into the system Python. The other scripts look there first.
  * It runs on old Pythons (3.6+) on purpose, so that it can explain what to do about one.

Exit codes: 0 plan printed (without --yes), or with --yes everything in the tier is done; 1 a step
failed; 2 every automatic step is done (or there was none) but manual steps are still left - they
are listed at the end, and running the same command again gives 2 until they are done (always 2 for
the recording tier: it is manual steps only, and this script cannot see whether they were done);
4 a manual step must be done before the rest can continue.
"""

import argparse
import datetime
import json
import os
import platform
import re
import shutil
import subprocess
import sys

MIN_PYTHON = (3, 9)
PRIVATE_PYTHON = "3.12"
YTDLP_STALE_DAYS = 120
FORBIDDEN = ("sudo", "doas", "pkexec", "runas", "su")

# One fixed uv release, fetched only when the plan needs it, from two official places in this order:
#   1. the project's own GitHub release page. SHA-256 values copied on 2026-11-25 from the release's
#      checksum file https://github.com/astral-sh/uv/releases/download/0.13.10/sha256.sum ; they agree
#      with the asset digests the GitHub API reports for the same release.
#   2. the same version of the `uv` project on PyPI (files.pythonhosted.org), tried ONLY when GitHub
#      cannot be reached. URLs, sizes and SHA-256 values copied on 2026-11-25 from PyPI's own JSON API,
#      https://pypi.org/pypi/uv/0.13.10/json . From the wheel only the `uv` executable is read, by its
#      fixed member name; the wheel is never installed and nothing else in it is used.
# A download whose size or hash differs is deleted and nothing is installed - a mismatch is a stop,
# never a reason to try the other source. To move to a newer uv, replace version, sizes and hashes
# together from those two published lists - never from memory.
UV_RELEASE = {
    "version": "0.13.10",
    "base_url": "https://github.com/astral-sh/uv/releases/download/0.13.10/",
    "checksums_from": "https://github.com/astral-sh/uv/releases/download/0.13.10/sha256.sum",
    "assets": {
        ("linux", "x86_64"): ("uv-x86_64-unknown-linux-gnu.tar.gz", 17113138,
                              "bf65ac1a0af10f92c522d91ac096c7c0a39657647b155577e7836c2cbbb4526c"),
        ("linux", "aarch64"): ("uv-aarch64-unknown-linux-gnu.tar.gz", 16275135,
                               "14590f644805a6234ffe071154340669e38137f38e60aa9629690119704107d2"),
        ("macos", "x86_64"): ("uv-x86_64-apple-darwin.tar.gz", 17489953,
                              "153e03197588204c04fc4c81cc4bafbfa4280222a385e4ee36a87aeec0ae63b4"),
        ("macos", "arm64"): ("uv-aarch64-apple-darwin.tar.gz", 14700626,
                             "e419bf07533bdbf48795fc793601c834dd79db57a8c49ce8e25cfe3a8639958d"),
        ("windows", "amd64"): ("uv-x86_64-pc-windows-msvc.zip", 15641577,
                               "297b3881fe1adfb922becc2c1613202abb41dc83ea5ff43d472aa087ca1f8683"),
    },
    "pypi_checksums_from": "https://pypi.org/pypi/uv/0.13.10/json",
    "pypi_assets": {
        ("linux", "x86_64"): (
            "https://files.pythonhosted.org/packages/8b/99/fad906311e48fce22e4db71ee4c3df29bdb17b29eb36878f52b8dcd79237/"
            "uv-0.13.10-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl", 17653768,
            "7cc9c41b43d583e34c781fd3446405b06e9c5fa2db468ce2a534d353db6429e5"),
        ("linux", "aarch64"): (
            "https://files.pythonhosted.org/packages/97/4b/12a9e73be39829da3ece358385c3c019ecdea91a5fc704381d584ad9a387/"
            "uv-0.13.10-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.musllinux_1_1_aarch64.whl", 18137926,
            "e89dd26ea831dde70639ba0a798fa04a4c7c0226fd2b241da86218bfa370e495"),
        ("macos", "x86_64"): (
            "https://files.pythonhosted.org/packages/77/0d/178749e47a7ea76ad7c4a0c736b11615f2b4a1af94a9983c987b724e20c1/"
            "uv-0.13.10-py3-none-macosx_10_12_x86_64.whl", 17658690,
            "19a76fd50a6a2bba38ee088d8336566856569be08196865f98132a08806581fc"),
        ("macos", "arm64"): (
            "https://files.pythonhosted.org/packages/5b/d6/78204b698ed27b425b9660105af4b388a379b0435ea2e77e783feca3f180/"
            "uv-0.13.10-py3-none-macosx_11_0_arm64.whl", 14807398,
            "2a9ff188b442419c7aadebc445fcc1f287b25f99af50fa6d563b90cc0047b7cf"),
        ("windows", "amd64"): (
            "https://files.pythonhosted.org/packages/cf/e4/d0704c116ada58e8450890e2defaaf2f07e8d264cf94669210e0823fbcb2/"
            "uv-0.13.10-py3-none-win_amd64.whl", 15736046,
            "d87b9cf8165f2b3cc596e856b5bf794da9cfad6d1b110ca9d87eed42a15b3684"),
    },
}
# Where a download may be redirected to. GitHub serves release files from its own storage hosts;
# PyPI serves from files.pythonhosted.org and does not redirect. Anything else is refused.
REDIRECT_HOSTS = {"github": ("github.com", ".githubusercontent.com"), "pypi": ("files.pythonhosted.org",)}
# Slow links stall for a minute or more in the middle of a file (measured: 45 KB/s with pauses, where
# a single read timeout used to abandon a download that curl finished). A stalled transfer is resumed
# with a Range request; the SHA-256 is still computed over the whole file.
READ_TIMEOUT = 45          # seconds without a single byte before one connection is given up
MAX_RESUMES = 8            # resumes IN A ROW that bring nothing new before giving up
NO_PROGRESS_LIMIT = 10 * 60   # seconds without a single new byte before giving up
TOTAL_LIMIT = 3 * 60 * 60  # a safety net only: a transfer that keeps advancing is not cut off
# (A fixed 20-minute limit failed at 9.5 KB/s with 11.4 of 17.7 MB done, and the next run started
# from zero - it could never finish. Now the unfinished file is kept and the next run continues it.)
PROGRESS_EVERY = 5         # seconds between progress lines
# uv gives up a request after 30 s without data and retries only a few times; at 28 KB/s the package
# index page of one dependency did not arrive in time and the whole install failed (field test).
# These are passed to uv unless the user has set them already.
UV_ENV = {"UV_HTTP_TIMEOUT": "300", "UV_HTTP_RETRIES": "8"}
HEARTBEAT_EVERY = 60       # seconds between "still running" lines while an install step works
SLOW_NETWORK_HINT = ("The reason is in the output above - read it before trying again.\n"
                     "  * Timeouts, resets, dropped connections: the network. Then just run the same command again; "
                     "packages that were already downloaded are kept in uv's / pip's cache and are not fetched a "
                     "second time.\n"
                     "  * A build or compile error (CMake, a compiler, \"Failed to build\"), or no matching "
                     "version for this machine: NOT the network, and running it again will not help. A package has "
                     "no ready-made build for this system. For a speech recogniser, use the other engine "
                     "(--whisper-engine faster-whisper needs nothing compiled).")
# openai-whisper on an Intel Mac. Field test, 2026-11: llvmlite 0.50.0 has no ready-made build for that
# machine and its source build stops with "llvmlite needs CMake tools to build"; with torch's last Intel
# Mac build (2.2.2) NumPy 2 answers "Numpy is not available". Limited to ready-made builds and NumPy 1.x
# the install works (it resolved to llvmlite 0.45.1, numba 0.62.1, torch 2.2.2, numpy 1.26.4) and
# transcribe_local.py --self-test passed.
INTEL_MAC_OPENAI_WHISPER = ["--only-binary", "llvmlite", "--only-binary", "numba", "--only-binary", "torch",
                            "openai-whisper", "numpy<2"]
ARCH_ALIASES = {"amd64": "x86_64", "x64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64", "x86_64": "x86_64"}
UV_MANUAL = ("Install uv yourself - it needs no administrator rights (https://docs.astral.sh/uv/; it is also "
             "published on PyPI as a plain wheel) - or, on Debian/Ubuntu, install the venv package:  "
             "sudo apt-get install python3-venv   Then run this script again.")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def tool_home():
    return os.environ.get("WVLH_HOME") or os.path.join(os.path.expanduser("~"), ".watch-video-like-human")


def venv_dir():
    return os.path.join(tool_home(), "venv")


def venv_python(target):
    if target == "windows":
        return os.path.join(venv_dir(), "Scripts", "python.exe")
    return os.path.join(venv_dir(), "bin", "python")


def private_python_state(vpy):
    """(version as a list or None, problem as text or None) of the private environment's Python."""
    if not os.path.lexists(vpy):
        return None, None
    code, out = run_quiet([vpy, "-I", "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"], timeout=60)
    match = re.search(r"^(\d+)\.(\d+)\.(\d+)\s*$", out, re.M)
    if code != 0 or not match:
        return None, "it does not start"
    version = [int(n) for n in match.groups()]
    if tuple(version[:2]) < MIN_PYTHON:
        return version, "it is Python %d.%d.%d" % tuple(version)
    return version, None


def rebuild_step(state):
    """The private environment is unusable. Say how to replace it; never delete or move it ourselves."""
    old = venv_dir()
    spare, n = old + "-old", 2
    while os.path.lexists(spare):
        spare, n = "%s-old-%d" % (old, n), n + 1
    if state["platform"] == "windows":
        command = 'Rename-Item -LiteralPath "%s" -NewName "%s"   (PowerShell)' % (old, os.path.basename(spare))
    else:
        command = 'mv "%s" "%s"' % (old, spare)
    return step("rebuild-venv", "Replace the private Python environment", runs="manual", blocking=True,
                why="the private Python in %s cannot run the scripts: %s (they need %d.%d+), and this script "
                    "does not delete or move your files" % ((old, state["private_problem"]) + MIN_PYTHON),
                note="1. Set the old one aside:  %s   2. Run this script again with --yes: it makes a new one "
                     "and installs what it needs.   3. When everything works, you can delete %s yourself. A "
                     "speech recogniser that was in it has to be installed again (--tier whisper)."
                     % (command, spare))


def private_dirs(target):
    return [os.path.join(venv_dir(), "Scripts" if target == "windows" else "bin"),
            os.path.join(tool_home(), "bin")]


def join(cmd):
    out = []
    for part in cmd:
        out.append('"%s"' % part if (" " in part or not part) else part)
    return " ".join(out)


def clean_env(env=None):
    """The environment for anything this script starts.

    macOS: a python.org framework Python leaves __PYVENV_LAUNCHER__ in the environment. A child that
    inherits it takes the wrong interpreter for its own: `uv pip install --python VENV/bin/python`
    answered "externally managed", and the private yt-dlp and the engine check looked into the system
    Python and reported the packages missing right after they were installed (field test, Python 3.7).
    """
    env = dict(os.environ if env is None else env)
    env.pop("__PYVENV_LAUNCHER__", None)
    return env


def run_quiet(cmd, timeout=20):
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
                              env=clean_env(), stdin=subprocess.DEVNULL)
        return proc.returncode, proc.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return 127, ""


def find(name, target):
    """Path of a tool, looking in the private folder first."""
    path = os.pathsep.join(private_dirs(target) + [os.environ.get("PATH", "")])
    return shutil.which(name, path=path)


def detect(target, arch):
    """What is really on this machine. Reads only; changes nothing."""
    present = {}
    for name in ("ffmpeg", "ffprobe", "yt-dlp", "whisper", "uv", "pipx", "winget", "scoop", "brew",
                 "apt-get", "dnf", "pacman", "zypper", "pactl"):
        present[name] = find(name, target)
    ytdlp_version = None
    if present["yt-dlp"]:
        _, out = run_quiet([present["yt-dlp"], "--version"])
        ytdlp_version = (out.strip().splitlines() or [""])[-1].strip() or None
    ffmpeg_version = None
    if present["ffmpeg"]:
        _, out = run_quiet([present["ffmpeg"], "-version"])
        match = re.search(r"ffmpeg version (\S+)", out)
        ffmpeg_version = match.group(1) if match else None
    newer = None
    if sys.version_info[:2] < MIN_PYTHON:
        for minor in range(14, MIN_PYTHON[1] - 1, -1):
            newer = shutil.which("python3.%d" % minor)
            if newer:
                break
    engines = {"whisper_cli": bool(present["whisper"])}
    vpy = venv_python(target)
    private_version, private_problem = private_python_state(vpy)
    for module in ("faster_whisper", "whisper"):
        found = False
        if private_version and not private_problem:
            # -I: only what is installed in that environment counts, not PYTHONPATH or the current folder
            code, _ = run_quiet([vpy, "-I", "-c", "import importlib.util,sys;"
                                 "sys.exit(0 if importlib.util.find_spec('%s') else 1)" % module])
            found = code == 0
        if not found:
            try:
                import importlib.util
                found = importlib.util.find_spec(module) is not None
            except (ImportError, ValueError):
                found = False
        engines[module] = found
    is_root = bool(getattr(os, "geteuid", lambda: 1)() == 0)
    try:        # Debian/Ubuntu ship Python without ensurepip: `python -m venv` then fails
        import importlib.util
        venv_ok = bool(importlib.util.find_spec("venv") and importlib.util.find_spec("ensurepip"))
    except (ImportError, ValueError):
        venv_ok = False
    return {"platform": target, "arch": arch, "python": list(sys.version_info[:3]),
            "python_executable": sys.executable, "newer_python": newer,
            "present": present, "yt_dlp_version": ytdlp_version, "ffmpeg_version": ffmpeg_version,
            "engines": engines, "venv_exists": os.path.isfile(vpy),
            "private_python": private_version, "private_problem": private_problem, "is_root": is_root, "venv_ok": venv_ok,
            "today": datetime.date.today().isoformat()}


def ytdlp_age_days(version, today):
    match = re.match(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", version or "")
    if not match:
        return None
    try:
        released = datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        now = datetime.datetime.strptime(today, "%Y-%m-%d").date()
    except ValueError:
        return None
    return (now - released).days


def uv_key(target, arch):
    arch = ARCH_ALIASES.get((arch or "").lower(), (arch or "").lower())
    return (target, {"macos": {"aarch64": "arm64"}, "windows": {"x86_64": "amd64"}}.get(target, {}).get(arch, arch))


def uv_asset(target, arch):
    """(file name, size, sha256) of the pinned uv build for this machine, or None when there is none."""
    return UV_RELEASE["assets"].get(uv_key(target, arch))


def uv_sources(target, arch):
    """The two pinned places to get uv from, in the order they are tried."""
    key = uv_key(target, arch)
    if key not in UV_RELEASE["assets"]:
        return []
    exe = "uv.exe" if target == "windows" else "uv"
    name, size, digest = UV_RELEASE["assets"][key]
    folder = name[:-len(".tar.gz")] if name.endswith(".tar.gz") else None
    sources = [{"source": "github", "label": "official GitHub release", "url": UV_RELEASE["base_url"] + name,
                "bytes": size, "sha256": digest, "kind": "zip" if name.endswith(".zip") else "tar",
                "member": exe if folder is None else folder + "/" + exe,
                "checksums_from": UV_RELEASE["checksums_from"]}]
    if key in UV_RELEASE["pypi_assets"]:
        url, size, digest = UV_RELEASE["pypi_assets"][key]
        sources.append({"source": "pypi", "label": "official wheel on PyPI (only if GitHub cannot be reached)",
                        "url": url, "bytes": size, "sha256": digest, "kind": "zip",
                        "member": "uv-%s.data/scripts/%s" % (UV_RELEASE["version"], exe),
                        "checksums_from": UV_RELEASE["pypi_checksums_from"]})
    return sources


def private_uv(target):
    return os.path.join(tool_home(), "bin", "uv.exe" if target == "windows" else "uv")


def fetch_uv_step(state):
    """A built-in download step: no shell, no installer script, no PATH change, no administrator rights."""
    sources = uv_sources(state["platform"], state["arch"])
    if not sources:
        return None
    first = sources[0]
    item = step("fetch-uv", "Download uv %s into the private folder" % UV_RELEASE["version"],
                note="From the official release page; if that host cannot be reached, from the same version "
                     "on PyPI. %.1f MB. The download is checked against the SHA-256 published with that "
                     "release (%s...) and against HTTPS certificates; if a check fails the file is deleted, "
                     "nothing is installed and the other source is NOT tried. No installer script is run, "
                     "PATH is not changed, no administrator rights are used. uv then creates the private "
                     "environment and brings its own Python %s."
                     % (first["bytes"] / 1e6, first["sha256"][:16], PRIVATE_PYTHON))
    item["download"] = {"url": first["url"], "version": UV_RELEASE["version"], "bytes": first["bytes"],
                        "sha256": first["sha256"], "checksums_from": first["checksums_from"],
                        "to": private_uv(state["platform"]), "sources": sources}
    item["shown_as"] = "download %s  ->  %s" % (first["url"], item["download"]["to"])
    item["fallback"] = UV_MANUAL
    return item


def step(ident, title, command=None, runs="auto", why=None, note=None, blocking=False, rerun=False):
    return {"id": ident, "title": title, "command": command, "shown_as": join(command) if command else None,
            "runs": runs, "why_manual": why, "note": note, "blocking": blocking, "rerun_after": rerun}


ADMIN = "needs administrator rights; this script never uses sudo and never types a password"


def python_steps(state):
    """How to get an interpreter new enough for the scripts, without touching the system one."""
    target, present = state["platform"], state["present"]
    version = tuple(state["python"][:2])
    if version >= MIN_PYTHON:
        return [], state["python_executable"]
    if present.get("uv"):
        return [], PRIVATE_PYTHON          # uv fetches its own interpreter when the venv is made
    if state.get("newer_python"):
        return [], state["newer_python"]
    old = "Python %d.%d is too old for the scripts (they need %d.%d+)." % (version + MIN_PYTHON)
    if target == "windows" and present.get("winget"):
        return [step("python", "Install Python %s for this user" % PRIVATE_PYTHON,
                     ["winget", "install", "--id", "Python.Python.%s" % PRIVATE_PYTHON, "-e",
                      "--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity"],
                     note=old + " Accepts the winget source and package agreements on your behalf.",
                     rerun=True)], None
    if target == "macos" and present.get("brew"):
        return [step("python", "Install Python %s with Homebrew" % PRIVATE_PYTHON,
                     ["brew", "install", "python@%s" % PRIVATE_PYTHON], note=old, rerun=True)], None
    if uv_asset(target, state["arch"]):
        return [], PRIVATE_PYTHON          # venv_steps() plans the uv download; uv brings the interpreter
    how = {"macos": "Install uv (https://docs.astral.sh/uv/ - its installer needs no administrator "
                    "rights), then run this script again: uv supplies Python %s by itself. Homebrew is "
                    "the alternative where it can be installed; on Intel Macs it may refuse."
                    % PRIVATE_PYTHON,
           "linux": "Install a newer Python with your package manager (for example "
                    "`sudo apt-get install python3.12 python3.12-venv`), or install uv "
                    "(https://docs.astral.sh/uv/), then run this script again.",
           "windows": "Install Python %s from python.org or the Microsoft Store, then run this script "
                      "again in a new terminal." % PRIVATE_PYTHON}
    return [step("python", "Get Python %d.%d or newer" % MIN_PYTHON, runs="manual",
                 why=old, note=how.get(target), blocking=True)], None


def ffmpeg_steps(state):
    target, present, arch = state["platform"], state["present"], state["arch"]
    if present.get("ffmpeg") and present.get("ffprobe"):
        return []
    title = "Install ffmpeg and ffprobe"
    if target == "windows":
        if present.get("winget"):
            return [step("ffmpeg", title, ["winget", "install", "--id", "Gyan.FFmpeg", "-e",
                                           "--accept-source-agreements", "--accept-package-agreements",
                                           "--disable-interactivity"],
                         note="Accepts the winget source and package agreements on your behalf. "
                              "Open a new terminal afterwards so PATH is refreshed.", rerun=True)]
        if present.get("scoop"):
            return [step("ffmpeg", title, ["scoop", "install", "ffmpeg"])]
        return [step("ffmpeg", title, runs="manual", why="no winget or scoop on this machine",
                     note="Download a Windows build linked from https://ffmpeg.org/download.html, unzip it, "
                          "and put ffmpeg.exe and ffprobe.exe in %s (create the folder) or anywhere on PATH."
                          % os.path.join(tool_home(), "bin"))]
    if target == "macos":
        if present.get("brew"):
            return [step("ffmpeg", title, ["brew", "install", "ffmpeg"])]
        intel = arch in ("x86_64", "amd64", "i386")
        return [step("ffmpeg", title, runs="manual",
                     why="Homebrew is not installed" + (" (on Intel Macs it may refuse to install)" if intel else ""),
                     note="Download a signed and notarized static build of ffmpeg AND ffprobe for %s from "
                          "the macOS builds linked at https://ffmpeg.org/download.html, and put both files "
                          "in %s (create the folder; `chmod +x` them). The scripts look there first. "
                          "On Apple Silicon, installing Homebrew yourself and running `brew install ffmpeg` "
                          "is the simpler way." % ("Intel (x86_64)" if intel else "Apple Silicon (arm64)",
                                                   os.path.join(tool_home(), "bin")))]
    managers = (("apt-get", ["apt-get", "install", "-y", "ffmpeg"]), ("dnf", ["dnf", "install", "-y", "ffmpeg"]),
                ("pacman", ["pacman", "-S", "--noconfirm", "ffmpeg"]), ("zypper", ["zypper", "install", "-y", "ffmpeg"]))
    for name, command in managers:
        if present.get(name):
            if state.get("is_root"):
                return [step("ffmpeg", title, command)]
            return [step("ffmpeg", title, runs="manual", why=ADMIN,
                         note="Run this yourself in a terminal:  sudo " + join(command))]
    return [step("ffmpeg", title, runs="manual", why="no known package manager found",
                 note="Install ffmpeg with your distribution's package manager, or put static ffmpeg and "
                      "ffprobe binaries in %s." % os.path.join(tool_home(), "bin"))]


def engine_packages(state, engine):
    """(arguments for the installer, a note or None). Only one combination needs anything special."""
    arch = ARCH_ALIASES.get(state["arch"], state["arch"])
    if engine == "openai-whisper" and state["platform"] == "macos" and arch == "x86_64":
        return list(INTEL_MAC_OPENAI_WHISPER), (
            "Intel Mac: the newest llvmlite, numba and torch have no ready-made builds for this machine and "
            "would have to be compiled (that needs CMake and fails without it). The install is therefore "
            "limited to ready-made builds, with NumPy below 2 - the last torch for Intel Macs does not work "
            "with NumPy 2. faster-whisper needs none of this.")
    return [engine], None


def venv_steps(state, interpreter, packages, label):
    """Create the private environment if needed and install packages into it."""
    target, present = state["platform"], state["present"]
    arguments, packages = packages, [p for i, p in enumerate(packages)
                                     if not p.startswith("-") and (i == 0 or packages[i - 1] != "--only-binary")]
    vpy = venv_python(target)
    if state.get("private_problem"):
        return [rebuild_step(state),
                step(label, "Install %s into the private environment" % ", ".join(packages), runs="manual",
                     why="waits for the step above", note="Run this script again afterwards.")]
    steps = []
    uv = present.get("uv") or None      # the full path as found: the private copy is not on PATH
    system_python = interpreter if interpreter and interpreter != PRIVATE_PYTHON else None
    cannot_venv = not state.get("venv_exists") and not state.get("venv_ok", True)
    if not uv and (system_python is None or cannot_venv) and (interpreter or uv_asset(target, state["arch"])):
        fetch = fetch_uv_step(state) if not (interpreter is None) else None
        if fetch:
            steps.append(fetch)
            uv = fetch["download"]["to"]
    if uv:
        if not state.get("venv_exists"):
            steps.append(step("venv", "Create the private Python environment",
                              [uv, "venv", "--python", system_python or PRIVATE_PYTHON, venv_dir()],
                              note="In %s. uv downloads Python %s itself if this machine has none new "
                                   "enough; the system Python is not touched." % (tool_home(), PRIVATE_PYTHON)))
        steps.append(step(label, "Install %s into the private environment" % ", ".join(packages),
                          [uv, "pip", "install", "--python", vpy, "--upgrade"] + arguments))
        return steps
    if not interpreter or interpreter == PRIVATE_PYTHON:
        return [step(label, "Install %s" % ", ".join(packages), runs="manual",
                     why="waits for the Python step above", note="Run this script again afterwards.")]
    if not state.get("venv_exists") and not state.get("venv_ok", True):
        # Seen on a real Ubuntu: Python 3.14 with no pip and no ensurepip, so `-m venv` cannot work.
        return [step("venv-tools", "Make it possible to create a private Python environment", runs="manual",
                     why="this Python has no venv / ensurepip, uv is not installed, and there is no "
                         "pinned uv build for this kind of machine", blocking=True, note=UV_MANUAL),
                step(label, "Install %s" % ", ".join(packages), runs="manual",
                     why="waits for the step above", note="Run this script again afterwards.")]
    if not state.get("venv_exists"):
        steps.append(step("venv", "Create the private Python environment", [interpreter, "-m", "venv", venv_dir()],
                          note="In %s; the system Python is not touched. On Debian/Ubuntu this needs the "
                               "python3-venv package." % tool_home()))
    steps.append(step(label, "Install %s into the private environment" % ", ".join(packages),
                      [vpy, "-m", "pip", "install", "--upgrade"] + arguments))
    return steps


def base_tier(state):
    steps, interpreter = python_steps(state)
    steps += ffmpeg_steps(state)
    age = ytdlp_age_days(state.get("yt_dlp_version"), state["today"])
    stale = age is not None and age > YTDLP_STALE_DAYS
    notes = []
    # An old system Python cannot run the other scripts. They hand over to the private Python by
    # themselves, so the base tier makes sure there is one - not only the whisper tier (field test:
    # a Mac with Python 3.7, tools all present, got a warning and no step).
    needs_private = tuple(state["python"][:2]) < MIN_PYTHON and not state.get("venv_exists")
    if needs_private and not state.get("private_problem"):
        notes.append("Python %s is too old for the other scripts (they need %d.%d+). The steps above "
                     "create a private Python in %s; the scripts then hand over to it by themselves, "
                     "and the system Python is not touched."
                     % ((".".join(str(n) for n in state["python"][:2]),) + MIN_PYTHON + (venv_dir(),)))
    if state.get("private_problem"):
        needs_private = True
    if not state["present"].get("yt-dlp") or stale or needs_private:
        if stale:
            notes.append("yt-dlp %s is %d days old; site extractors go stale within months. The existing "
                         "copy is left alone - a current one goes into the private folder and is used first."
                         % (state["yt_dlp_version"], age))
        steps += venv_steps(state, interpreter, ["yt-dlp"], "yt-dlp")
    return {"needed": bool(steps), "steps": steps, "notes": notes,
            "covers": "ffmpeg + ffprobe, a current yt-dlp, Python %d.%d+" % MIN_PYTHON}


def pick_engine(state, wanted):
    if wanted and wanted != "auto":
        return wanted
    # faster-whisper everywhere: about 300 MB against 2 GB or more, far less memory while running,
    # it is what transcribe_local.py tries first, and it is the engine both field tests (Intel Mac,
    # Linux) actually ran. openai-whisper stays available with --whisper-engine openai-whisper.
    return "faster-whisper"


def whisper_tier(state, wanted):
    engines = state["engines"]
    have = [name for name, ok in sorted(engines.items()) if ok]
    if have:
        return {"needed": False, "steps": [], "notes": ["Already present: " + ", ".join(have)],
                "covers": "a local speech recogniser"}
    engine = pick_engine(state, wanted)
    py_steps, interpreter = python_steps(state)
    packages, special = engine_packages(state, engine)
    steps = py_steps + venv_steps(state, interpreter, packages, "whisper")
    size = {"faster-whisper": "about 300 MB of packages (no PyTorch)",
            "openai-whisper": "2 GB or more of packages (it brings PyTorch)"}[engine]
    notes = ["Engine: %s - %s. The first transcription also downloads a model (the `small` model is "
             "roughly 500 MB). Default is faster-whisper on every system: smaller, lighter on memory, and "
             "the one transcribe_local.py tries first; --whisper-engine openai-whisper picks the other."
             % (engine, size),
             "Use it with:  python scripts/transcribe_local.py WORK/audio.wav --language LANG   (it finds "
             "the private environment by itself, and `--self-test` proves the engine really runs).",
             "Models come from huggingface.co (faster-whisper) or openaipublic.azureedge.net "
             "(openai-whisper). Where huggingface.co cannot be reached, set HF_ENDPOINT to a mirror you "
             "trust before the first run; this script does not choose one for you."]
    if special:
        notes.append(special)
    if engine == "faster-whisper":
        notes.append("transcribe_local.py decodes audio with ffmpeg rather than PyAV, so the PyAV "
                     "version that comes with faster-whisper does not matter.")
    return {"needed": True, "steps": steps, "notes": notes, "engine": engine,
            "covers": "a local speech recogniser"}


def recording_tier(state):
    """Route C needs things only a person can do. This is a guide; nothing here is ever run."""
    target = state["platform"]
    record = "python " + os.path.join("scripts", "record_browser_playback.py")
    if target == "windows":
        guide = [
            "Loopback audio: install VB-CABLE from its vendor's site (vb-audio.com/Cable). You run the "
            "installer yourself, as administrator; this script will not.",
            "Right after installing, set your speakers back as the default output (Settings > System > "
            "Sound). The installer switches the default to 'CABLE Input' and the speakers go silent.",
            "To record: route the browser to 'CABLE Input' in Volume mixer, or switch the default output "
            "to it for the length of the recording and switch back afterwards.",
        ]
    elif target == "macos":
        guide = [
            "Loopback audio: install BlackHole 2ch from the developer's official .pkg. It asks for your "
            "password - type it yourself. Restart the Mac afterwards; the device does not show up before.",
            "Open Audio MIDI Setup and create a Multi-Output Device containing BlackHole 2ch AND your "
            "speakers, then select it as the system output. Unmute the speakers FIRST: while a "
            "Multi-Output Device is selected the volume keys are disabled.",
            "Screen recording permission: System Settings > Privacy & Security > Screen & System Audio "
            "Recording. Enable it for the application that launches the commands. Inside a desktop agent "
            "app there may be two entries (the app and its command-line helper, often in lower case); "
            "the helper is the one that counts. Without it ffmpeg waits forever and says nothing.",
            "The first capture on macOS 15 shows a system prompt about bypassing the window picker. "
            "Answer it before the real recording, or it ends up in the middle of the picture.",
        ]
    else:
        guide = [
            "Loopback audio: PulseAudio / PipeWire already expose a monitor source for every output. "
            "If `pactl` is missing, install pulseaudio-utils (Debian/Ubuntu) or pipewire-pulse yourself: "
            "it needs sudo.",
            "Wayland sessions: recording the root window gives a black picture. Use the desktop's own "
            "recorder and treat the file as Route 0, or record one X11 window with --window-id.",
        ]
    guide += ["Then check, with nothing installed by this script:  %s --check-audio" % record,
              "And before any real recording:  %s --preflight" % record]
    steps = [step("guide-%d" % n, text, runs="manual", why="only a person can do this")
             for n, text in enumerate(guide, start=1)]
    return {"needed": True, "steps": steps, "notes": ["Guide only. --yes changes nothing here."],
            "covers": "loopback audio driver and screen-recording permission (Route C)"}


def build_plan(state, tier, engine):
    tiers = {}
    if tier in ("base", "all"):
        tiers["base"] = base_tier(state)
    if tier in ("whisper", "all"):
        tiers["whisper"] = whisper_tier(state, engine)
    if tier in ("recording", "all"):
        tiers["recording"] = recording_tier(state)
    version = tuple(state["python"][:2])
    return {"schema": "setup-plan/1", "platform": state["platform"], "arch": state["arch"],
            "python": {"version": ".".join(str(n) for n in state["python"]),
                       "ok": version >= MIN_PYTHON, "minimum": "%d.%d" % MIN_PYTHON},
            "tool_home": tool_home(),
            "found": {"ffmpeg": state["present"].get("ffmpeg"), "ffprobe": state["present"].get("ffprobe"),
                      "yt-dlp": state["present"].get("yt-dlp"), "yt_dlp_version": state.get("yt_dlp_version"),
                      "ffmpeg_version": state.get("ffmpeg_version"), "engines": state["engines"]},
            "tiers": tiers,
            "rules": ["dry run unless --yes", "no sudo, no password, no download piped into a shell",
                      "whisper is confirmed separately with --tier whisper --yes",
                      "the recording tier is a guide and is never executed"]}


def human(plan, mode):
    lines = ["=" * 70,
             "  Setup plan - %s / %s / Python %s   [%s]" % (plan["platform"], plan["arch"],
                                                            plan["python"]["version"], mode),
             "=" * 70]
    if not plan["python"]["ok"]:
        lines.append("  ! Python %s is older than %s: the other scripts cannot run on it. They hand over to"
                     % (plan["python"]["version"], plan["python"]["minimum"]))
        lines.append("    the private Python in %s; the base tier creates it when it is missing."
                     % os.path.join(plan["tool_home"], "venv"))
    found = plan["found"]
    for name in ("ffmpeg", "ffprobe", "yt-dlp"):
        extra = ""
        if name == "yt-dlp" and found.get("yt_dlp_version"):
            extra = "  (%s)" % found["yt_dlp_version"]
        if name == "ffmpeg" and found.get("ffmpeg_version"):
            extra = "  (%s)" % found["ffmpeg_version"]
        lines.append("  [%s] %-8s %s%s" % ("OK " if found[name] else "-- ", name, found[name] or "not found", extra))
    for name, tier in plan["tiers"].items():
        lines += ["", "TIER %s - %s" % (name, tier["covers"])]
        if not tier["steps"]:
            lines.append("  nothing to do")
        for item in tier["steps"]:
            if item["runs"] == "auto" and item.get("download"):
                d = item["download"]
                lines.append("  [auto]   %s" % item["title"])
                for n, src in enumerate(d.get("sources") or [d], start=1):
                    lines.append("           %s %s" % ("from   " if n == 1 else "or from", src["url"]))
                    lines.append("                   %s; version %s, %.1f MB, sha256 %s"
                                 % (src.get("label", "source %d" % n), d["version"], src["bytes"] / 1e6, src["sha256"]))
                lines.append("           to      %s" % d["to"])
            elif item["runs"] == "auto":
                lines.append("  [auto]   %s" % item["title"])
                lines.append("           $ %s" % item["shown_as"])
            else:
                lines.append("  [manual] %s" % item["title"])
                if item["why_manual"]:
                    lines.append("           why not automatic: %s" % item["why_manual"])
            if item["note"]:
                lines.append("           %s" % item["note"])
        for note in tier["notes"]:
            lines.append("  note: %s" % note)
    lines += ["", "-" * 70]
    if mode == "dry-run":
        lines += ["  Nothing was installed. To run the [auto] steps of one tier:",
                  "    python setup_tools.py --yes                  (base)",
                  "    python setup_tools.py --tier whisper --yes   (confirmed separately)",
                  "  [manual] steps are always yours to do; this script never uses sudo."]
    lines.append("-" * 70)
    return "\n".join(lines)


def is_forbidden(command):
    """True for anything that would raise privileges. Checked again right before running."""
    for part in command or []:
        if os.path.basename(str(part)).lower().split(".")[0] in FORBIDDEN:
            return True
    return False


class DownloadStop(Exception):
    """A failure that must NOT be answered by trying another source (a failed check, a refused redirect)."""


def restricted_opener(source):
    """An opener that follows redirects only to the hosts this source is known to use, over HTTPS."""
    import urllib.error
    import urllib.parse
    import urllib.request
    allowed = REDIRECT_HOSTS.get(source, ())

    class OnlyKnownHosts(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            parts = urllib.parse.urlsplit(newurl)
            host = (parts.hostname or "").lower()
            ok = parts.scheme == "https" and any(host == h or (h.startswith(".") and host.endswith(h)) for h in allowed)
            if not ok:
                raise DownloadStop("refused a redirect to %s://%s" % (parts.scheme, host or "?"))
            return urllib.request.HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)
    return urllib.request.build_opener(OnlyKnownHosts()).open


class DownloadStalled(Exception):
    """The host was reached and sent data, but the transfer could not be completed in time."""


RETRY_PAUSE = 3            # seconds between two attempts after a timeout (grows a little, capped at 20)


def is_timeout(exc):
    """A request that got no answer in time. The host may be fine and merely slow: that is retried.

    Connection refused, no route and a name that does not resolve are different: the host cannot
    be reached at all, and the next source is tried at once.
    """
    import socket
    reason = getattr(exc, "reason", exc)
    if isinstance(exc, (socket.timeout, TimeoutError)) or isinstance(reason, (socket.timeout, TimeoutError)):
        return True
    return "timed out" in str(reason).lower() or "timed out" in str(exc).lower()


def partial_path(src, target):
    """Where an unfinished download waits: named after the expected hash, so it can only continue the same file."""
    return "%s.%s.part" % (target, src["sha256"][:12])


def fetch_one(src, target, opener=None):
    """Download one pinned archive, check size and SHA-256, write out ONLY the named member.

    A transfer that stalls is resumed with a Range request. If it still cannot finish, the bytes
    received so far are KEPT next to the target and the next run continues from there. Whatever
    path the bytes took, the SHA-256 of the whole file decides; a mismatch deletes everything.
    """
    import hashlib
    import http.client
    import tarfile
    import time
    import urllib.error
    import urllib.request
    import zipfile

    partial = partial_path(src, target)
    open_url = opener or restricted_opener(src.get("source"))
    total = src["bytes"]
    digest, got = hashlib.sha256(), 0
    if os.path.isfile(partial):
        if os.path.getsize(partial) > total:
            os.remove(partial)                       # cannot be the same file
        else:
            with open(partial, "rb") as existing:
                for block in iter(lambda: existing.read(1 << 20), b""):
                    digest.update(block)
                    got += len(block)
            print("  continuing an earlier download: %.1f of %.1f MB are already here" % (got / 1e6, total / 1e6),
                  file=sys.stderr, flush=True)
    started = last_note = last_progress = time.time()
    resumes = idle_resumes = 0
    best = got
    keep = False

    def give_up(why):
        kept = (" The %.1f MB received are kept in %s: run the same command again and it continues from there"
                % (got / 1e6, partial)) if got > 0 else " Nothing was received, so nothing is kept."
        raise DownloadStalled("the host answers too slowly or not in time: the transfer stopped at %.1f of %.1f MB "
                              "after %d attempt(s) and %d s (%s).%s"
                              % (got / 1e6, total / 1e6, resumes, time.time() - started, why, kept))

    def stalled_too_long():
        return (idle_resumes > MAX_RESUMES or time.time() - last_progress > NO_PROGRESS_LIMIT
                or time.time() - started > TOTAL_LIMIT)
    try:
        with open(partial, "ab") as handle:
            while got < total:
                headers = {"User-Agent": "watch-video-like-human-setup"}
                if got:
                    headers["Range"] = "bytes=%d-" % got
                try:
                    response = open_url(urllib.request.Request(src["url"], headers=headers), timeout=READ_TIMEOUT)
                except DownloadStop:
                    raise
                except Exception as exc:  # noqa: BLE001
                    if resumes == 0 and not is_timeout(exc):
                        # Refused, no route, unknown name, a certificate or HTTP error on the very first
                        # request: the caller decides (next source, or stop). An earlier partial stays.
                        keep = got > 0 and getattr(exc, "code", None) is None
                        raise
                    # A timeout - even on the first request, even before a single byte - is a slow host:
                    # the same patience applies as for a transfer that stalls in the middle.
                    resumes += 1
                    idle_resumes += 1
                    if stalled_too_long():
                        keep = got > 0
                        give_up("%s: %s" % (type(exc).__name__, getattr(exc, "reason", exc)))
                    print("  no answer within %d s - trying again (%d so far)" % (READ_TIMEOUT, resumes),
                          file=sys.stderr, flush=True)
                    time.sleep(min(RETRY_PAUSE * idle_resumes, 20))
                    continue
                try:
                    status = getattr(response, "status", None) or (response.getcode() if hasattr(response, "getcode") else 200)
                    if got and status != 206:   # the server ignored the Range: start this file again
                        handle.seek(0)
                        handle.truncate()
                        digest, got = hashlib.sha256(), 0
                    while True:
                        block = response.read(1 << 16)
                        if not block:
                            break
                        got += len(block)
                        if got > total:
                            raise DownloadStop("the download is larger than the published size")
                        digest.update(block)
                        handle.write(block)
                        now = time.time()
                        if got > best:          # real progress: the patience starts again
                            best, last_progress, idle_resumes = got, now, 0
                        if now - last_note >= PROGRESS_EVERY:
                            last_note = now
                            print("  %5.1f of %.1f MB  (%d%%, %d s)" % (got / 1e6, total / 1e6, 100 * got // total,
                                                                    now - started), file=sys.stderr, flush=True)
                        if now - started > TOTAL_LIMIT:
                            keep = True
                            give_up("over the %d-hour safety limit" % (TOTAL_LIMIT // 3600))
                except (OSError, http.client.HTTPException) as exc:     # a read timed out or the connection dropped
                    resumes += 1
                    idle_resumes += 1
                    if stalled_too_long():
                        keep = True
                        give_up("nothing new for %d s; %s: %s" % (time.time() - last_progress, type(exc).__name__, exc))
                    print("  stalled at %.1f of %.1f MB - resuming (%d so far)" % (got / 1e6, total / 1e6, resumes),
                          file=sys.stderr, flush=True)
                    continue
                finally:
                    response.close()
                    handle.flush()
                if got < total:                 # the connection closed early without an error
                    resumes += 1
                    idle_resumes += 1
                    if stalled_too_long():
                        keep = True
                        give_up("the connection kept closing early")
        if got != total or digest.hexdigest() != src["sha256"]:
            raise DownloadStop("size or SHA-256 does not match the published values (%d bytes, %s...)"
                               % (got, digest.hexdigest()[:16]))
        try:
            if src.get("kind") == "tar":
                with tarfile.open(partial, "r:gz") as archive:
                    member = archive.extractfile(archive.getmember(src["member"]))   # this exact name, nothing else
                    data = member.read() if member else None
            else:
                with zipfile.ZipFile(partial) as archive:
                    data = archive.read(src["member"])
        except KeyError:
            data = None
        if not data:
            raise DownloadStop("the archive does not contain %s" % src["member"])
        with open(target, "wb") as handle:        # written under OUR name: nothing in the archive chooses a path
            handle.write(data)
        os.chmod(target, 0o755)
    finally:
        try:
            # Kept only when the host was reached and the bytes are a good prefix as far as anyone can
            # tell; removed on success, on any failed check, and when nothing was received.
            if os.path.exists(partial) and not (keep and os.path.getsize(partial) > 0):
                os.remove(partial)
        except OSError:
            pass


def download_verified(spec, opener=None):
    """Get uv from the first pinned source that can be REACHED; verify it; unpack only `uv`.

    Returns (ok, message). The second source is tried only when the first cannot be reached
    (connection refused, no route, a name that does not resolve). A request that merely times out is
    retried with the same patience as a stalled transfer. A certificate failure, a size or hash mismatch,
    a missing member or a redirect to an unknown host stops everything: those are never a reason
    to look elsewhere. A transfer that stalls is resumed; if it still cannot finish, what arrived is
    kept for the next run and the next source is tried. Certificate verification is never turned
    off; nothing downloaded is run.
    """
    target = spec["to"]
    made, folder = [], os.path.dirname(target)
    while folder and not os.path.isdir(folder):      # remember which folders this call creates ...
        made.append(folder)
        folder = os.path.dirname(folder)
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
    except OSError as exc:
        return False, "cannot create %s: %s" % (os.path.dirname(target), exc)
    ok, message = _download_from_sources(spec, target, opener)
    if not ok:
        for folder in made:                          # ... and take them away again if nothing was installed
            try:
                os.rmdir(folder)                     # only ever removes an EMPTY folder
            except OSError:
                break
    return ok, message


def _download_from_sources(spec, target, opener):
    import ssl

    sources = spec.get("sources") or [dict(spec, source="github", kind="zip" if spec["url"].endswith(".zip") else "tar")]
    unreachable = []
    for src in sources:
        print("  trying %s: %s" % (src.get("label") or src.get("source"), src["url"]), file=sys.stderr)
        try:
            fetch_one(src, target, opener)
            spec["used_source"] = src.get("source")
            return True, "uv %s from %s (%s): size and SHA-256 verified, placed at %s" % (
                spec["version"], src.get("source"), src.get("label") or "", target)
        except DownloadStop as exc:
            return False, "%s - stopped; the other source is not tried after a failed check" % exc
        except DownloadStalled as exc:               # reached, but too slow or interrupted: not "unreachable"
            unreachable.append("%s: %s" % (src.get("source"), exc))
            print("  %s: %s" % (src.get("source"), exc), file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, ssl.SSLError) or isinstance(exc, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(exc):
                return False, ("this Python could not verify the HTTPS certificate of %s (no CA certificates, a "
                               "proxy re-signing HTTPS, or a wrong system clock). Verification is never skipped."
                               % src.get("source"))
            if getattr(exc, "code", None):          # the host answered with an HTTP error: reached, but refused
                return False, "%s answered HTTP %s for the pinned file - stopped" % (src.get("source"), exc.code)
            unreachable.append("%s: could not connect (%s: %s)" % (src.get("source"), type(exc).__name__, reason))
            print("  could not reach %s (%s)" % (src.get("source"), reason), file=sys.stderr)
    return False, "no source could be completed (" + "; ".join(unreachable) + ")"


def is_uv(command):
    return bool(command) and os.path.basename(str(command[0])).lower().split(".")[0] == "uv"


def step_environment(command):
    """The environment for one step: uv gets patient network settings, nothing the user set is overridden."""
    env = clean_env()
    if is_uv(command):
        for key, value in UV_ENV.items():
            env.setdefault(key, value)
    return env


def run_step(item):
    """Run one command, saying every minute that it is still working (installs can take a long time)."""
    import threading
    import time
    command, started, done = item["command"], time.time(), threading.Event()

    def heartbeat():
        while not done.wait(HEARTBEAT_EVERY):
            print("  ... still running after %d min: %s (large downloads on a slow link take a while; "
                  "this is not a hang)" % ((time.time() - started) // 60, item["title"]), file=sys.stderr, flush=True)
    watcher = threading.Thread(target=heartbeat)
    watcher.daemon = True
    watcher.start()
    try:
        return subprocess.run(command, stdin=subprocess.DEVNULL, env=step_environment(command)).returncode
    finally:
        done.set()


def execute(tier):
    """Run the [auto] steps of one tier in order. Stops at the first failure or blocking manual step."""
    results = []
    for item in tier["steps"]:
        if item["runs"] != "auto":
            results.append({"id": item["id"], "status": "manual", "title": item["title"]})
            if item["blocking"]:
                print("\nSTOPPED: do this first, then run the same command again:\n  %s\n  %s"
                      % (item["title"], item["note"] or ""), file=sys.stderr)
                return 4, results
            continue
        if item.get("download"):
            spec = item["download"]
            print("\nDownloading uv %s (about %.0f MB; a stalled transfer is resumed and is only given up after "
                  "%d minutes without a single new byte; an unfinished download is kept and continued by the "
                  "next run) ..." % (spec["version"], spec["bytes"] / 1e6, NO_PROGRESS_LIMIT // 60), file=sys.stderr)
            ok, message = download_verified(spec)
            results.append({"id": item["id"], "status": "ok" if ok else "failed", "detail": message,
                            "source": spec.get("used_source")})
            if not ok:
                again = ("\nAn unfinished download was kept: running the same command again continues it."
                         if "are kept in" in message else "")
                print("\nCOULD NOT FETCH uv: %s\nNothing was installed.%s\nOr do it by hand instead:\n  %s"
                      % (message, again, item.get("fallback") or UV_MANUAL), file=sys.stderr)
                return 4, results
            print(message, file=sys.stderr)
            continue
        if is_forbidden(item["command"]):
            results.append({"id": item["id"], "status": "refused"})
            print("REFUSED: this step would raise privileges: %s" % item["shown_as"], file=sys.stderr)
            return 1, results
        print("\n$ %s" % item["shown_as"], file=sys.stderr)
        if is_uv(item["command"]):
            print("  (uv is given %s s per request and %s retries for slow links; every minute a line says it "
                  "is still running)" % (os.environ.get("UV_HTTP_TIMEOUT", UV_ENV["UV_HTTP_TIMEOUT"]),
                                         os.environ.get("UV_HTTP_RETRIES", UV_ENV["UV_HTTP_RETRIES"])), file=sys.stderr)
        try:
            code = run_step(item)
        except OSError as exc:
            print("Could not start: %s" % exc, file=sys.stderr)
            code = 127
        results.append({"id": item["id"], "status": "ok" if code == 0 else "failed", "exit": code})
        if code != 0:
            print("\nFAILED (exit %d): %s\nNothing after this step was run.\n%s"
                  % (code, item["title"], SLOW_NETWORK_HINT), file=sys.stderr)
            return 1, results
        if item["rerun_after"]:
            print("\nDone. Open a NEW terminal (so PATH is refreshed) and run the same command again "
                  "for the remaining steps.", file=sys.stderr)
            return 4, results
    return 0, results


def manual_exit_code(tier):
    """Exit code once every automatic step is done: 0 nothing left, 2 manual steps left, 4 one of them blocks."""
    manual = [item for item in tier["steps"] if item["runs"] != "auto"]
    if any(item["blocking"] for item in manual):
        return 4
    return 2 if manual else 0


def list_manual(tier):
    manual = [item for item in tier["steps"] if item["runs"] != "auto"]
    if not manual:
        return
    print("\nNOT FINISHED - still to be done by hand (exit code %d until then):" % manual_exit_code(tier), file=sys.stderr)
    for item in manual:
        print("  - %s%s" % (item["title"], "" if not item["note"] else "\n      " + item["note"]), file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tier", choices=["base", "whisper", "recording", "all"], default="base",
                        help="Which tier to plan. 'all' shows every tier but can never be run in one go.")
    parser.add_argument("--yes", action="store_true",
                        help="Run the [auto] steps of the chosen tier. Without it nothing is installed.")
    parser.add_argument("--json", action="store_true", help="Print the plan (and results) as JSON.")
    parser.add_argument("--whisper-engine", choices=["auto", "faster-whisper", "openai-whisper"], default="auto")
    parser.add_argument("--simulate", metavar="FILE",
                        help="Plan for a machine described in a JSON file instead of this one. Plan only: "
                             "--yes is refused together with it.")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass

    system = platform.system().lower()
    target = {"darwin": "macos", "windows": "windows", "linux": "linux"}.get(system, system)
    state = detect(target, platform.machine().lower())
    if args.simulate:
        if args.yes:
            raise SystemExit("--simulate describes another machine; refusing to run anything with --yes.")
        with open(args.simulate, "r", encoding="utf-8") as handle:
            fake = json.load(handle)
        empty = dict((name, None) for name in state["present"])
        empty.update(fake.pop("present", {}))
        state.update({"engines": {"whisper_cli": False, "faster_whisper": False, "whisper": False},
                      "venv_exists": False, "venv_ok": True, "newer_python": None, "yt_dlp_version": None,
                      "private_python": None, "private_problem": None, "ffmpeg_version": None, "is_root": False})
        state.update(fake)
        state["present"] = empty

    plan = build_plan(state, args.tier, args.whisper_engine)
    mode = "execute" if args.yes else "dry-run"
    plan["mode"] = mode
    code = 0
    if args.yes:
        if args.tier == "all":
            raise SystemExit("Tiers are confirmed one at a time: run --yes for base, then "
                             "--tier whisper --yes if you want it. Nothing was installed.")
        tier = plan["tiers"][args.tier]
        if not args.json:
            print(human(plan, mode))
        if args.tier == "recording":
            plan["results"] = []
            code = 2
            print("\nThe recording tier is a guide: nothing was run. Follow the steps above yourself. (Exit code 2: "
                  "manual steps only. This script cannot see whether you have done them; check with "
                  "record_browser_playback.py --preflight.)", file=sys.stderr)
        elif not any(item["runs"] == "auto" for item in tier["steps"]):
            plan["results"] = []
            code = manual_exit_code(tier)
            print("\nNothing to run automatically" + (": the remaining steps are manual." if tier["steps"]
                                                       else ": this tier is already complete."), file=sys.stderr)
            list_manual(tier)
        else:
            code, plan["results"] = execute(tier)
            if code == 0:
                print("\nAll automatic steps finished. Check with:  python %s"
                      % os.path.join("scripts", "probe_capabilities.py"), file=sys.stderr)
                code = manual_exit_code(tier)      # the same answer a second run gives
                list_manual(tier)
        if args.json:
            print(json.dumps(plan, indent=2))
        return code
    print(json.dumps(plan, indent=2) if args.json else human(plan, mode))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
