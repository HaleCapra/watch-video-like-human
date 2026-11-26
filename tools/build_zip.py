#!/usr/bin/env python3
"""Build dist/watch-video-like-human-<version>.zip for hosts that install a skill from a zip.

The archive has one top-level folder, `watch-video-like-human/`, with `SKILL.md` directly inside
it. Paths use forward slashes on every platform, and no `__pycache__` goes in. The zip is then
unpacked to a temporary folder and compared byte for byte with the source.

    python tools/build_zip.py
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "watch-video-like-human"
NAME = "watch-video-like-human"


def main() -> int:
    front = (SKILL / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1]
    match = re.search(r'version:\s*"?([0-9][\w.\-]*)"?', front)
    version = match.group(1) if match else "0"
    dist = REPO / "dist"
    dist.mkdir(exist_ok=True)
    target = dist / f"{NAME}-{version}.zip"
    files = sorted(p for p in SKILL.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, f"{NAME}/" + path.relative_to(SKILL).as_posix())
    check = Path(tempfile.mkdtemp(prefix="skill-zip-check-"))
    try:
        with zipfile.ZipFile(target) as zf:
            names = zf.namelist()
            assert zf.testzip() is None
            assert all("\\" not in n and ".." not in n and not n.startswith("/") for n in names), names
            zf.extractall(check)
        same = all((check / n).read_bytes() == (SKILL / n.split("/", 1)[1]).read_bytes() for n in names)
    finally:
        shutil.rmtree(check, ignore_errors=True)   # the folder this run created, nothing else
    assert same and len(names) == len(files)
    print(f"{target}: {len(names)} files, {target.stat().st_size} bytes, byte-identical after unzip: {same}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
