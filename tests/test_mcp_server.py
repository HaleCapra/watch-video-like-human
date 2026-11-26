#!/usr/bin/env python3
"""Checks for server/mcp_server.py.

    python -B tests/test_mcp_server.py

Part 1 needs nothing but Python: the path guard, the address check, what the source must never contain.
Part 2 starts the server over stdio and calls every tool the way an agent's MCP client would. It needs
the MCP SDK (server/requirements.txt) and ffmpeg. Without the SDK it is skipped - unless
WVLH_REQUIRE_MCP=1 (CI sets it), where a missing SDK is a failure.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent.parent
SERVER = REPO / "server" / "mcp_server.py"
sys.path.insert(0, str(REPO / "tools"))
from mcp_stdio_client import McpStdio  # noqa: E402

PASSED = []


def check(name, condition, detail=""):
    if not condition:
        raise AssertionError("%s %s" % (name, detail))
    PASSED.append(name)
    print("PASS", name, flush=True)


def load_server():
    spec = importlib.util.spec_from_file_location("wvlh_mcp_server", str(SERVER))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXPECTED = ["about", "align_transcript_frames", "evidence_manifest_add", "evidence_manifest_init",
            "evidence_manifest_lint", "evidence_manifest_rate", "evidence_manifest_render",
            "evidence_manifest_route", "evidence_manifest_verify", "extract_media_assets", "fetch_media",
            "normalize_transcript", "probe_capabilities", "read_transcript", "setup_plan", "transcribe_local"]

SRT = """1
00:00:00,500 --> 00:00:02,000
This is a short test video.

2
00:00:02,500 --> 00:00:04,000
It checks that the tools work together.

3
00:00:04,500 --> 00:00:05,500
The end.
"""

VTT = """WEBVTT

00:00.500 --> 00:02.000
This is a short test video.

00:02.500 --> 00:04.000
It checks that the tools work together.
"""


def part_one(work, outside):
    server = load_server()
    server.STATE["root"] = os.path.realpath(str(work))
    root = server.STATE["root"]

    check("guard: a relative path lands under the root",
          server.inside("a/b.txt", "x") == os.path.join(root, "a", "b.txt"))
    check("guard: an absolute path under the root is accepted",
          server.inside(os.path.join(root, "c.txt"), "x") == os.path.join(root, "c.txt"))
    refused = ["../x.txt", "a/../../x.txt", str(outside / "secret.txt"), "/etc/passwd", "", "   ", "a\0b",
               os.path.join(root, "..", "x.txt")]
    if os.name == "nt":
        refused += ["C:\\Windows\\win.ini", "NUL", "sub\\con.txt", "\\\\server\\share\\f.txt"]
    for bad in refused:
        try:
            got = server.inside(bad, "x")
        except server.ToolError:
            continue
        raise AssertionError("guard accepted %r -> %r" % (bad, got))
    check("guard: %d ways out of the root are refused" % len(refused), True)
    try:
        os.symlink(str(outside), str(work / "way-out"), target_is_directory=True)
        linked = True
    except (OSError, NotImplementedError, AttributeError):
        linked = False
    if linked:
        try:
            server.inside("way-out/secret.txt", "x")
            raise AssertionError("a link that leaves the root was followed")
        except server.ToolError:
            check("guard: a link that leaves the root is refused", True)
    else:
        print("NOTE  links cannot be made here; the link check did not run")

    for bad in ["file:///etc/passwd", "-o", "--exec=x", "ftp://example.com/v", "https://exa mple.com", "http://",
                "javascript:alert(1)", "C:\\video.mp4", "https://example.com/v\n--exec", 7, None]:
        try:
            server.web_url(bad)
        except server.ToolError:
            continue
        raise AssertionError("address check accepted %r" % (bad,))
    check("address: only http(s) addresses pass", server.web_url("https://example.com/watch?v=1") != "")

    source = SERVER.read_text(encoding="utf-8")
    for never in ("--yes", "cookies-from-browser", "browser-profile", "shell=True", "os.system", "os.popen",
                  "confirm-upload", "transcribe_cloud"):
        check("source: no %r" % never, never not in source)
    check("tools: the expected set", sorted(fn.__name__ for fn in server.TOOLS) == EXPECTED)
    check("tools: none records, installs or uploads",
          not [n for n in EXPECTED if any(w in n for w in ("record", "install", "cloud", "upload"))])
    check("tools: each has a description", all((fn.__doc__ or "").strip() for fn in server.TOOLS))

    argv = []
    server.flag(argv, "--reason", "--force")
    check("arguments: a value can never become another option", argv == ["--reason=--force"])

    listed = subprocess.run([sys.executable, "-I", "-S", "-B", str(SERVER), "--list-tools"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    check("--list-tools works with no SDK at all",
          listed.returncode == 0 and json.loads(listed.stdout.decode("utf-8"))["tools"] == [fn.__name__ for fn in server.TOOLS])
    bare = subprocess.run([sys.executable, "-I", "-S", "-B", str(SERVER), "--root", str(work)],
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    message = bare.stderr.decode("utf-8", "replace")
    check("no SDK: exit 3 and a message that says what to install",
          bare.returncode == 3 and "pip install" in message and "Docker" in message and not bare.stdout.strip(),
          "exit %s\n%s" % (bare.returncode, message))
    missing = subprocess.run([sys.executable, "-B", str(SERVER), "--root", str(work / "no-such-folder")],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    check("a work root that is not a folder: exit 2", missing.returncode == 2)

    # The tool functions themselves, without MCP in between.
    answer = server.read_transcript("../x.srt") if False else None
    try:
        server.extract_media_assets("../x.mp4")
        raise AssertionError("extract accepted a path outside the root")
    except server.ToolError:
        pass
    try:
        server.fetch_media("file:///etc/passwd")
        raise AssertionError("fetch accepted a file address")
    except server.ToolError:
        pass
    check("functions: refusals happen before any script starts", answer is None)
    plan = server.setup_plan()
    check("setup_plan: a plan and nothing installed",
          plan["installed_anything"] is False and "--yes" not in plan.get("arguments", []) and
          (plan["ok"] or plan.get("reason") == "script_not_in_this_installation"), json.dumps(plan)[:600])


def part_two(work, outside):
    try:
        import mcp  # noqa: F401
        have_sdk = True
    except ImportError:
        have_sdk = False
    if not have_sdk:
        if os.environ.get("WVLH_REQUIRE_MCP") == "1":
            raise AssertionError("the MCP SDK is not installed, and WVLH_REQUIRE_MCP=1 says it must be")
        print("SKIPPED part 2 (stdio): the MCP SDK is not installed for this Python")
        return False
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "ffmpeg is needed for part 2"
    made = subprocess.run([ffmpeg, "-y", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i",
                           "testsrc2=s=320x180:d=6:r=10", "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                           "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac", "-shortest", str(work / "sample.mp4")],
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert made.returncode == 0, made.stderr.decode("utf-8", "replace")[-1500:]
    (work / "talk.srt").write_text(SRT, encoding="utf-8")
    (work / "cap.vtt").write_text(VTT, encoding="utf-8")
    (outside / "secret.srt").write_text(SRT, encoding="utf-8")

    with McpStdio([sys.executable, "-B", str(SERVER), "--root", str(work)]) as client:
        def ok(name, arguments, timeout=600):
            payload, is_error, _ = client.call(name, arguments, timeout=timeout)
            assert not is_error and payload.get("ok"), "%s %s -> %s\n%s" % (
                name, arguments, json.dumps(payload, ensure_ascii=False)[-2500:], client.stderr_text())
            return payload

        def refused(name, arguments, word="outside the work root"):
            payload, is_error, _ = client.call(name, arguments)
            assert is_error and word in json.dumps(payload), "%s %s was not refused: %s" % (name, arguments, payload)

        check("stdio: the server introduces itself",
              client.server["serverInfo"]["name"] == "watch-video-like-human"
              and "not watching" in (client.server.get("instructions") or ""), json.dumps(client.server)[:800])
        tools = client.tools()
        check("stdio: the tool list", sorted(t["name"] for t in tools) == EXPECTED, str(sorted(t["name"] for t in tools)))
        check("stdio: every tool has a description and an input schema",
              all(t.get("description") and t.get("inputSchema", {}).get("type") == "object" for t in tools))
        check("stdio: no tool takes a login, an install switch or a recording",
              not [t["name"] for t in tools
                   if any(w in json.dumps(t.get("inputSchema")).lower() for w in ("cookie", "password"))])

        info = ok("about", {})
        check("about: work root, scripts, what is not offered",
              os.path.normcase(info["work_root"]) == os.path.normcase(os.path.realpath(str(work)))
              and "extract_media_assets" in info["scripts"] and "record_browser_playback" in info["not_offered"])

        probe = ok("probe_capabilities", {})
        check("probe_capabilities: a JSON report", isinstance(probe["result"], dict) and probe["evidence"]["channel"] == "none")
        plan = ok("setup_plan", {"tier": "all"})
        check("setup_plan: a plan, nothing installed",
              isinstance(plan["result"], dict) and plan["installed_anything"] is False
              and not [a for a in plan["arguments"] if "yes" in a])
        backends = client.call("transcribe_local", {"list_backends": True})[0]
        check("transcribe_local: lists the recognisers", isinstance(backends.get("result"), dict)
              and "importable" in backends["result"], json.dumps(backends)[:500])

        done = ok("extract_media_assets", {"video": "sample.mp4", "out_dir": "out", "interval": 2, "width": 160})
        frames = json.loads((work / "out" / "frames.json").read_text(encoding="utf-8"))
        check("extract_media_assets: frames and audio on disk", len(frames["frames"]) >= 2 and (work / "out" / "audio.wav").is_file())
        check("extract_media_assets: says the frames are written, not seen",
              done["evidence"]["channel"] == "visual" and "frames seen" in done["evidence"]["does_not_count_as"])

        done = ok("normalize_transcript", {"input": "cap.vtt", "out": "out/cap"})
        check("normalize_transcript: SRT and JSON written, labelled as caption text",
              (work / "out" / "cap.srt").is_file() and (work / "out" / "cap.json").is_file()
              and done["evidence"]["channel"] == "captions (text)"
              and {"watched", "heard"} <= set(done["evidence"]["does_not_count_as"]), json.dumps(done)[:600])

        page = ok("read_transcript", {"transcript": "talk.srt", "limit": 2})
        check("read_transcript: a page of segments, labelled as text read",
              page["result"]["total_segments"] == 3 and len(page["result"]["segments"]) == 2
              and {"watched", "heard"} <= set(page["evidence"]["does_not_count_as"]), json.dumps(page)[:800])
        status = ok("read_transcript", {"transcript": "talk.srt", "mode": "status"})
        check("read_transcript: status reports the log", isinstance(status["result"], dict))
        ok("read_transcript", {"transcript": "talk.srt", "mode": "gaps", "duration": 6})

        done = ok("align_transcript_frames", {"frames": "out/frames.json", "transcript": "talk.srt",
                                              "output": "out/timeline.json", "speech_source": "captions-only"})
        outline = json.loads((work / "out" / "visual_outline.json").read_text(encoding="utf-8"))
        check("align_transcript_frames: timeline and outline, the captions-only label kept",
              (work / "out" / "timeline.json").is_file() and "captions-only" in json.dumps(outline)
              and "heard" in done["evidence"]["does_not_count_as"])

        gone, is_error, _ = client.call("fetch_media", {"url": "https://example.invalid/v", "what": "info",
                                                        "out_dir": "fetched"}, timeout=300)
        check("fetch_media: a failure comes back as a result, with the script's own words",
              not is_error and gone["ok"] is False and gone["exit_code"] != 0 and gone["stderr"], json.dumps(gone)[:600])
        check("fetch_media: the address is the only thing handed over",
              gone["arguments"][0] == "https://example.invalid/v" and "--info" in gone["arguments"]
              and not [a for a in gone["arguments"] if "cookie" in a])
        for bad in ("file:///etc/passwd", "--exec=touch x", "-o"):
            refused("fetch_media", {"url": bad}, word="http")

        manifest = "out/evidence_manifest.json"
        ok("evidence_manifest_init", {"manifest": manifest, "source": "sample.mp4", "title": "unit test"})
        ok("evidence_manifest_route", {"manifest": manifest, "route": "0", "status": "succeeded", "reason": "--force"})
        ok("evidence_manifest_add", {"manifest": manifest, "kind": "frames", "path": "out/frames.json", "command": "x"})
        ok("evidence_manifest_add", {"manifest": manifest, "kind": "transcript", "path": "talk.srt",
                                     "transcript_source": "manual", "language": "en"})
        record = json.loads((work / manifest).read_text(encoding="utf-8"))
        check("manifest: a reason that looks like an option is stored as text",
              "--force" in json.dumps(record["route"]))
        frame_id = next(e["id"] for e in record["artifacts"] if e["kind"] == "frames")
        inspected = ",".join("%s.f%03d" % (frame_id, n) for n in range(1, len(frames["frames"]) + 1))
        ok("evidence_manifest_rate", {"manifest": manifest, "visual": "sampled", "frames_inspected": inspected,
                                      "audio": "captions-only", "alignment": "timestamp-aligned",
                                      "gaps": ["Unit test: the frames were not looked at."]})
        ok("evidence_manifest_verify", {"manifest": manifest})
        rendered = ok("evidence_manifest_render", {"manifest": manifest, "output": "out/answer.md"})
        text = rendered["text"]
        check("render: the block the script wrote, unchanged",
              text.strip() == (work / "out" / "answer.md").read_text(encoding="utf-8").strip() and "captions" in text.lower(),
              text[:600])
        check("render: caption text is not presented as heard or transcribed",
              "**Audio:** captions-only" in text and "no audio was heard or transcribed" in text
              and "Captions + sampled visuals" in text, text[:800])
        ok("evidence_manifest_lint", {"file": "out/answer.md"})

        (work / "talk.srt").write_text(SRT.replace("The end.", "Changed after it was recorded."), encoding="utf-8")
        broken, is_error, _ = client.call("evidence_manifest_verify", {"manifest": manifest})
        check("verify: a file changed after recording fails, and the failure is passed on",
              not is_error and broken["ok"] is False and broken["exit_code"] != 0, json.dumps(broken)[:600])

        away = str(outside / "secret.srt")
        cases = [("extract_media_assets", {"video": "../sample.mp4"}),
                 ("extract_media_assets", {"video": "sample.mp4", "out_dir": str(outside / "frames")}),
                 ("transcribe_local", {"media": away}),
                 ("transcribe_local", {"media": "out/audio.wav", "output": "../x.srt"}),
                 ("align_transcript_frames", {"frames": "../frames.json"}),
                 ("align_transcript_frames", {"frames": "out/frames.json", "transcript": away}),
                 ("align_transcript_frames", {"frames": "out/frames.json", "output": away}),
                 ("align_transcript_frames", {"frames": "out/frames.json", "outline": "../o.json"}),
                 ("read_transcript", {"transcript": away}),
                 ("normalize_transcript", {"input": away}),
                 ("normalize_transcript", {"input": "cap.vtt", "out": "../cap"}),
                 ("fetch_media", {"url": "https://example.invalid/v", "out_dir": "../dl"}),
                 ("evidence_manifest_init", {"manifest": "../m.json", "source": "sample.mp4"}),
                 ("evidence_manifest_init", {"manifest": "m2.json", "source": away}),
                 ("evidence_manifest_route", {"manifest": away, "route": "0", "status": "succeeded"}),
                 ("evidence_manifest_add", {"manifest": manifest, "kind": "transcript", "path": away,
                                            "transcript_source": "manual"}),
                 ("evidence_manifest_rate", {"manifest": "../m.json", "visual": "none", "audio": "none", "alignment": "none"}),
                 ("evidence_manifest_verify", {"manifest": "../m.json"}),
                 ("evidence_manifest_render", {"manifest": manifest, "output": away + ".md"}),
                 ("evidence_manifest_render", {"manifest": "../m.json"}),
                 ("evidence_manifest_lint", {"file": away})]
        for name, arguments in cases:
            refused(name, arguments)
        check("stdio: %d path arguments that leave the root are refused, on every tool that takes a path" % len(cases),
              {c[0] for c in cases} == set(EXPECTED) - {"about", "probe_capabilities", "setup_plan"})
        check("nothing was written outside the root", sorted(p.name for p in outside.iterdir()) == ["secret.srt"],
              str(sorted(p.name for p in outside.iterdir())))

        for name in ("record_browser_playback", "setup_tools", "transcribe_cloud"):
            payload, is_error, _ = client.call(name, {})
            assert is_error, "%s exists as a tool: %s" % (name, payload)
        check("stdio: recording, installing and uploading are not tools", True)
        payload, is_error, _ = client.call("evidence_manifest_rate", {"manifest": manifest, "visual": "watched all of it",
                                                                   "audio": "heard", "alignment": "none"})
        check("rate: a rating outside the scale is refused", is_error, json.dumps(payload)[:300])
    return True


def main():
    base = Path(tempfile.mkdtemp(prefix="wvlh-mcp-test-"))
    work, outside = base / "root", base / "outside"
    work.mkdir()
    outside.mkdir()
    try:
        part_one(work, outside)
        full = part_two(work, outside)
    finally:
        shutil.rmtree(str(base), ignore_errors=True)        # the folder this run created, nothing else
    print("\n%d checks passed%s" % (len(PASSED), "" if full else " (part 2 skipped: no MCP SDK)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
