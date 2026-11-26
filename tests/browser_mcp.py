#!/usr/bin/env python3
"""Run Route B snippets from references/browser-extraction.md through real browser MCP servers.

    python -B tests/browser_mcp.py [--host playwright|chrome-devtools|all]

The snippets are taken from the reference file as written and put in the wrapper that
references/browser-mcp.md describes. They run against a local test page (a <video>, a WebVTT track
and a stand-in caption layer) in headless Chrome, through the MCP server itself over stdio - so the
tool names, the argument names, awaiting and the size of the replies are what an agent would meet.

Needs: node / npx, Chrome, ffmpeg. Meant for CI (Linux). Nothing leaves the machine except npx
fetching the two pinned packages.
"""

import argparse
import functools
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from mcp_stdio_client import McpStdio  # noqa: E402

DOC = (REPO / "skills" / "watch-video-like-human" / "references" / "browser-extraction.md").read_text(
    encoding="utf-8").replace("\r\n", "\n")
GUIDE = (REPO / "skills" / "watch-video-like-human" / "references" / "browser-mcp.md").read_text(
    encoding="utf-8").replace("\r\n", "\n")

PLAYWRIGHT_MCP = "@playwright/mcp@0.0.86"
CHROME_DEVTOOLS_MCP = "chrome-devtools-mcp@1.14.0"

CUES = [(1, 4, "Alpha: the first caption."), (5, 8, "Bravo: the second caption."),
        (9, 12, "Charlie: the third caption."), (13, 16, "Delta: the fourth caption."),
        (17, 20, "Echo: the fifth caption.")]

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>wvlh test page</title></head>
<body>
<h1>Test page: a video, a caption track, a stand-in caption layer</h1>
<video id="v" src="sample.webm" width="320" height="180" muted playsinline preload="auto" controls>
  <track kind="subtitles" srclang="en" label="English" src="captions.vtt" default>
</video>
<div id="layer" aria-label="what a player's own caption layer would show"></div>
<script>
  // A player draws its captions in its own elements. This stands in for that, so the Rung 3
  // sampler has a caption layer to read. It is test scaffolding, not part of the skill.
  const video = document.getElementById('v');
  const layer = document.getElementById('layer');
  const track = video.textTracks[0];
  track.mode = 'hidden';
  track.addEventListener('cuechange', () => {
    layer.textContent = '';
    for (const cue of track.activeCues || []) {
      const piece = document.createElement('span');
      piece.className = 'ytp-caption-segment';
      piece.textContent = cue.text;
      layer.appendChild(piece);
    }
  });
</script>
</body></html>
"""


def stamp(seconds):
    return "00:00:%02d.000" % seconds


def blocks():
    return re.findall(r"```js\n(.*?)\n```", DOC, flags=re.S)


def snippet(*markers):
    """The one ```js block of browser-extraction.md that contains every marker."""
    found = [b for b in blocks() if all(m in b for m in markers)]
    assert len(found) == 1, "%d blocks contain %r" % (len(found), markers)
    return found[0]


def wrapper():
    """The wrapper, read from browser-mcp.md, so the guide and the test cannot drift apart."""
    match = re.search(r"```js\n(async \(\) => \{ return await \(\n)\s*/\* the snippet, exactly as written \*/\n(\); \})\n```", GUIDE)
    assert match, "the wrapper is not in browser-mcp.md in the expected form"
    return match.group(1), match.group(2)


def wrapped(code):
    head, foot = wrapper()
    return head + code + "\n" + foot


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    """Static files with single-range support: a browser cannot seek in a video without it."""

    def log_message(self, *args):
        pass

    def send_head(self):
        wanted = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not wanted or not os.path.isfile(path):
            return super().send_head()
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", wanted.strip())
        size = os.path.getsize(path)
        if not match or (not match.group(1) and not match.group(2)):
            return super().send_head()
        if match.group(1):
            first = int(match.group(1))
            last = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
        else:
            first, last = max(0, size - int(match.group(2))), size - 1
        if first > last or first >= size:
            self.send_error(416)
            return None
        handle = open(path, "rb")
        handle.seek(first)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", "bytes %d-%d/%d" % (first, last, size))
        self.send_header("Content-Length", str(last - first + 1))
        self.end_headers()
        self._left = last - first + 1
        return handle

    def copyfile(self, source, target):
        left = getattr(self, "_left", None)
        if left is None:
            return super().copyfile(source, target)
        while left > 0:
            chunk = source.read(min(65536, left))
            if not chunk:
                break
            target.write(chunk)
            left -= len(chunk)
        self._left = None


def value_in(text):
    """The first JSON value in a tool's reply (the tools put their own words around it)."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r'[\[{"]', text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except ValueError:
            continue
        if isinstance(value, str):                       # a JSON string that itself holds JSON
            try:
                value = json.loads(value)
            except ValueError:
                pass
        return value
    raise AssertionError("no JSON value in the reply: %r" % text[:600])


class Host:
    def __init__(self, name, command, navigate, evaluate):
        self.name, self.command, self.navigate, self.evaluate = name, command, navigate, evaluate

    def run(self, url):
        passed = []

        def check(title, condition, detail=""):
            assert condition, "[%s] %s %s" % (self.name, title, detail)
            passed.append(title)
            print("PASS [%s] %s" % (self.name, title), flush=True)

        with McpStdio(self.command, start_timeout=300) as client:
            tools = {t["name"]: t for t in client.tools()}
            print("[%s] server %s, %d tools" % (self.name, json.dumps(client.server.get("serverInfo")), len(tools)))
            for needed in (self.navigate[0], self.evaluate):
                assert needed in tools, "[%s] no tool named %s; it has: %s" % (self.name, needed, sorted(tools))
                print("[%s] %s takes: %s" % (self.name, needed, json.dumps(tools[needed].get("inputSchema", {}).get("properties", {}))[:900]))

            def js(code, timeout=120):
                payload, is_error, raw = client.call(self.evaluate, {"function": code}, timeout=timeout)
                text = "\n".join(p.get("text", "") for p in (raw or {}).get("content") or [] if p.get("type") == "text")
                assert not is_error, "[%s] the tool reported an error:\n%s\n%s" % (self.name, text[:1500], client.stderr_text())
                return value_in(text), text

            payload, is_error, raw = client.call(self.navigate[0], dict(self.navigate[1], url=url), timeout=180)
            check("opens the test page", not is_error, json.dumps(payload)[:800] + client.stderr_text())

            value, text = js("async () => { await new Promise(r => setTimeout(r, 50)); return { awaited: true }; }")
            check("an async function is awaited", value == {"awaited": True}, text[:400])
            print("[%s] the envelope around a value looks like this:\n%s\n" % (self.name, text[:500]))

            value, text = js(wrapped(snippet("track.mode = 'hidden'", "cues load asynchronously")))
            check("Rung 2: the generic caption-track reader returns every cue",
                  value.get("ok") is True and value["count"] == len(CUES) and value["language"] == "en"
                  and [s["text"] for s in value["segments"]] == [c[2] for c in CUES]
                  and [round(s["start"]) for s in value["segments"]] == [c[0] for c in CUES], text[:800])
            print("[%s] the whole track came back in one reply of %d characters" % (self.name, len(text)))

            listing = snippet("[...document.querySelectorAll('track')].map")
            value, text = js("() => (\n" + listing + "\n)")
            check("Rung 2: the <track> listing", isinstance(value, list) and len(value) == 1
                  and value[0]["lang"] == "en" and value[0]["src"].endswith("captions.vtt"), text[:500])

            one = snippet("(async (seconds) =>", ".ytp-caption-segment")
            assert one.rstrip().endswith("})(150)"), one[-40:]
            value, text = js(wrapped(one.rstrip()[:-len("(150)")] + "(18)"))
            check("Rung 3: one sample point reads the caption that belongs to that time",
                  value.get("ok") is True and value["caption"] == CUES[4][2] and value["stale"] is False
                  and 17 <= value["at"] <= 20.5, text[:600])

            many = snippet("(async (points) =>")
            assert many.rstrip().endswith("})([75, 165, 210, 270, 345, 495])"), many[-60:]
            value, text = js(wrapped(many.rstrip()[:-len("([75, 165, 210, 270, 345, 495])")] + "([2, 6, 14, 22])"), timeout=180)
            got = [(s["requested"], s["caption"]) for s in value.get("samples", [])]
            check("Rung 3: several points in one call, each with its own caption, none where nothing is said",
                  value.get("ok") is True and got == [(2, CUES[0][2]), (6, CUES[1][2]), (14, CUES[3][2]), (22, None)]
                  and value["usable"] == 3 and value["notReached"] == 0 and value["aborted"] is False, text[:1200])

            long_text = "".join("%04d|" % n for n in range(520))                  # 2,600 characters
            keep = snippet("globalThis.__wvOut = String(TEXT)")
            keep = "\n".join(line for line in keep.splitlines() if not line.lstrip().startswith("//"))
            value, text = js(wrapped(keep.replace("String(TEXT)", "String(Array.from({length: 520}, (_, n) => String(n).padStart(4, '0') + '|').join(''))")))
            check("pieces: a long text is kept in the page", value == {"chars": len(long_text), "pieces": 3}, text[:400])
            read = snippet("((n) => { const s = globalThis.__wvOut")
            read = "\n".join(line for line in read.splitlines() if not line.lstrip().startswith("//")).rstrip()
            assert read.endswith("})(0)"), read[-30:]
            pieces = []
            for n in range(3):
                value, text = js(wrapped(read[:-len("(0)")] + "(%d)" % n))
                pieces.append(value)
            check("pieces: read back one by one, the lengths add up and the text is the same",
                  sum(p["length"] for p in pieces) == pieces[0]["chars"] == len(long_text)
                  and "".join(p["piece"] for p in pieces) == long_text and pieces[-1]["last"] is True
                  and [p["last"] for p in pieces[:-1]] == [False, False], json.dumps(pieces)[:600])
        return passed


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", choices=["playwright", "chrome-devtools", "all"], default="all")
    args = parser.parse_args()
    npx, ffmpeg = shutil.which("npx"), shutil.which("ffmpeg")
    assert npx and ffmpeg, "npx and ffmpeg are needed"
    extra = ["--no-sandbox"] if os.environ.get("WVLH_BROWSER_NO_SANDBOX") == "1" else []
    hosts = {
        "playwright": Host("Playwright MCP", [npx, "-y", PLAYWRIGHT_MCP, "--headless", "--isolated", "--browser", "chrome", *extra],
                           ("browser_navigate", {}), "browser_evaluate"),
        "chrome-devtools": Host("Chrome DevTools MCP",
                                [npx, "-y", CHROME_DEVTOOLS_MCP, "--headless", "--isolated",
                                 *(["--chrome-arg=--no-sandbox"] if extra else [])],
                                ("navigate_page", {"type": "url"}), "evaluate_script"),
    }
    chosen = list(hosts) if args.host == "all" else [args.host]

    site = Path(tempfile.mkdtemp(prefix="wvlh-browser-test-"))
    server = None
    try:
        (site / "index.html").write_text(PAGE, encoding="utf-8")
        (site / "captions.vtt").write_text(
            "WEBVTT\n\n" + "\n".join("%s --> %s\n%s\n" % (stamp(a), stamp(b), text) for a, b, text in CUES), encoding="utf-8")
        made = subprocess.run([ffmpeg, "-y", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i",
                               "testsrc2=s=320x180:d=24:r=10", "-c:v", "libvpx", "-b:v", "150k", "-g", "10",
                               "-deadline", "realtime", "-cpu-used", "8", "-an", str(site / "sample.webm")],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert made.returncode == 0, made.stderr.decode("utf-8", "replace")[-1500:]
        handler = functools.partial(RangeHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = "http://127.0.0.1:%d/index.html" % server.server_address[1]
        print("test page:", url)
        total = 0
        for key in chosen:
            total += len(hosts[key].run(url))
    finally:
        if server:
            server.shutdown()
        shutil.rmtree(str(site), ignore_errors=True)            # the folder this run created, nothing else
    print("\n%d checks passed through %s" % (total, " and ".join(hosts[k].name for k in chosen)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
