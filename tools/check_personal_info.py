#!/usr/bin/env python3
"""Scan a tree for things that must not be published: local paths, emails, keys.

    python tools/check_personal_info.py .                 # exit 0 = clean, 1 = findings
    python tools/check_personal_info.py . --term MyName --term my-project

It looks for
  * a Windows profile path        C:\\Users\\<name>\\...
  * a macOS / Linux home path     /Users/<name>/...   /home/<name>/...
  * an email address              (example.com / example.org and noreply addresses are allowed)
  * something shaped like a key   sk-..., gsk_..., ghp_..., AIza..., xox?-..., AKIA..., a PEM block
  * any extra term you pass with --term (your name, a project name, a machine name); matched
    case-insensitively and never written into this file

Placeholders such as C:\\Users\\<you>, /home/USER and ~/ are fine. A finding prints the file, the
line number and the kind - never the secret itself. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "dist", "__pycache__", "node_modules", ".venv", "venv"}
# Written by the test run and listed in .gitignore: it quotes tracebacks, which carry local paths.
SKIP_FILES = {"validation-result.json"}
TEXT_SUFFIXES = {".md", ".py", ".json", ".txt", ".toml", ".yaml", ".yml", ".cfg", ".ini", ".sh", ".ps1", ".bat",
                 ".srt", ".vtt", ".csv", ".html", ".js", ".ts", ""}
PLACEHOLDER = r"(?:<[^>\\/]*>|USER(?:NAME)?|NAME|YOU|you|username|user|Public|Default|runner|\$\w+|%\w+%|\{\w+\}|\.\.\.)"
RULES = [
    ("windows-user-path", re.compile(r"[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}(?!" + PLACEHOLDER + r"(?:[\\/\s\"'`,.)]|$))[^\\/\s\"'`<>|]+")),
    ("mac-user-path", re.compile(r"(?<![\w.~])/" + "Users/(?!" + PLACEHOLDER + r"(?:[/\s\"'`,.)]|$))[^/\s\"'`<>]+")),
    ("home-path", re.compile(r"(?<![\w.~])/" + "home/(?!" + PLACEHOLDER + r"(?:[/\s\"'`,.)]|$))[^/\s\"'`<>]+")),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")),
    ("api-key", re.compile(r"(?:sk-[A-Za-z0-9]{20,}|gsk_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_\w{30,}|"
                           r"AIza[0-9A-Za-z_-]{30,}|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|"
                           r"-----BEGIN [A-Z ]*PRIVATE KEY-----)")),
]
ALLOWED_EMAIL = re.compile(r"@(?:example\.(?:com|org|net)|[\w.-]*\.invalid|users\.noreply\.github\.com)$|^noreply@", re.I)


def is_text(path: Path) -> bool:
    if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in ("LICENSE", "AGENTS.md"):
        return False
    try:
        return b"\x00" not in path.read_bytes()[:4096]
    except OSError:
        return False


def scan(root: Path, terms: list[str]) -> tuple[list[dict], int]:
    findings: list[dict] = []
    scanned = 0
    lowered = [t.lower() for t in terms if t.strip()]
    for path in sorted(root.rglob("*")):
        if (not path.is_file() or SKIP_DIRS & set(path.relative_to(root).parts) or path.name in SKIP_FILES
                or not is_text(path)):
            continue
        scanned += 1
        rel = path.relative_to(root).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            for kind, pattern in RULES:
                for match in pattern.finditer(line):
                    if kind == "email" and ALLOWED_EMAIL.search(match.group(0)):
                        continue
                    findings.append({"file": rel, "line": number, "kind": kind})
                    break
            low = line.lower()
            for term in lowered:
                if term in low:
                    findings.append({"file": rel, "line": number, "kind": "extra-term"})
                    break
    return findings, scanned


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--term", action="append", default=[],
                        help="An extra word that must not appear (a name, a project). Repeatable.")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")
    findings, scanned = scan(root, args.term)
    print(json.dumps({"files_scanned": scanned, "findings": findings}, indent=2))
    if findings:
        print(f"{len(findings)} finding(s). Fix them before publishing.", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
