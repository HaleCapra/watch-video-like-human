#!/usr/bin/env python3
"""Route 0 from end to end THROUGH THE MCP SERVER, as a smoke test for CI and for the Docker image.

    python tools/mcp_route0_smoke.py --host-work DIR --video NAME [--out NAME] [--model tiny]
                                     [--language en] [--expect WORD] [--srt NAME] -- SERVER COMMAND...

DIR is the folder the server uses as its work root, as this script sees it (for Docker: the folder
mounted at /work). NAME is the video inside it. Everything after `--` starts the server, e.g.

    -- python server/mcp_server.py --root DIR
    -- docker run -i --rm -v DIR:/work -v CACHE:/cache IMAGE mcp

Only tool calls are made; the files are then checked from outside. Paths are given relative to the
work root, so the same calls work on the host and in the container. Nothing here is part of the skill.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_stdio_client import McpStdio  # noqa: E402


def main():
    argv = sys.argv[1:]
    if "--" not in argv:
        raise SystemExit("Give the server command after `--`.")
    cut = argv.index("--")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host-work", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--out", default="mcp-out")
    parser.add_argument("--language", default="en")
    parser.add_argument("--model", default="tiny")
    parser.add_argument("--expect", action="append", default=[])
    parser.add_argument("--srt", help="A transcript inside the work root to use instead of running the recogniser.")
    args = parser.parse_args(argv[:cut])
    command = argv[cut + 1:]
    host = Path(args.host_work).resolve()
    out = args.out
    if (host / out).exists():
        shutil.rmtree(str(host / out))                       # the folder a previous run of this script made

    with McpStdio(command) as client:
        def call(title, name, arguments, timeout=900):
            print("\n== %s\n-> %s %s" % (title, name, json.dumps(arguments, ensure_ascii=False)), flush=True)
            payload, is_error, _ = client.call(name, arguments, timeout=timeout)
            if is_error or not payload.get("ok"):
                print(json.dumps(payload, indent=2, ensure_ascii=False)[-4000:])
                raise SystemExit("FAILED at: %s\n%s" % (title, client.stderr_text()))
            return payload

        print("server:", json.dumps(client.server.get("serverInfo")))
        names = client.tool_names()
        print("tools:", ", ".join(names))
        assert not [n for n in names if "record" in n or "install" in n], names
        info = call("about", "about", {})
        print("work root as the server sees it:", info["work_root"], "| scripts:", ", ".join(info["scripts"]))

        payload, is_error, _ = client.call("read_transcript", {"transcript": "../outside.srt"})
        assert is_error and "outside the work root" in json.dumps(payload), payload
        payload, is_error, _ = client.call("extract_media_assets", {"video": "/etc/hostname"})
        assert is_error, payload
        print("paths outside the work root: refused")

        done = call("frames and audio", "extract_media_assets", {"video": args.video, "out_dir": out, "interval": 2})
        assert done["evidence"]["channel"] == "visual" and "frames seen" in done["evidence"]["does_not_count_as"]
        frames = json.loads((host / out / "frames.json").read_text(encoding="utf-8"))
        listed = frames.get("frames") or []
        assert listed, "no frames were extracted"
        audio = host / out / "audio.wav"
        assert audio.is_file() and audio.stat().st_size > 10000, "no audio was extracted"
        print("frames: %d, audio: %d bytes" % (len(listed), audio.stat().st_size))

        srt = out + "/audio.srt"
        if args.srt:
            shutil.copyfile(str(host / args.srt), str(host / srt))
            source, how, audio_rating = "manual", "copied (the recogniser was skipped)", "captions-only"
        else:
            done = call("speech to text", "transcribe_local", {"media": out + "/audio.wav", "language": args.language,
                                                              "model": args.model}, timeout=1800)
            assert done["evidence"]["channel"].startswith("audio"), done["evidence"]
            source, how, audio_rating = "asr", "MCP transcribe_local, model %s" % args.model, "transcribed"
        text = (host / srt).read_text(encoding="utf-8")
        spoken = " ".join(line for line in text.splitlines()
                          if line.strip() and not line.strip().isdigit() and "-->" not in line)
        print("transcript: %r" % spoken[:400])
        assert spoken.strip(), "the transcript is empty"
        if args.expect:
            assert any(word.lower() in spoken.lower() for word in args.expect), "none of %r is in it" % (args.expect,)

        page = call("read the transcript", "read_transcript", {"transcript": srt, "limit": 50})
        assert page["result"]["total_segments"] >= 1 and "watched" in page["evidence"]["does_not_count_as"]

        call("align", "align_transcript_frames", {"frames": out + "/frames.json", "transcript": srt,
                                                  "output": out + "/timeline.json",
                                                  "speech_source": "transcribed" if source == "asr" else "captions-only"})
        assert (host / out / "timeline.json").is_file() and (host / out / "visual_outline.json").is_file()

        manifest = out + "/evidence_manifest.json"
        call("manifest: init", "evidence_manifest_init", {"manifest": manifest, "source": args.video,
                                                          "title": "CI smoke run through MCP"})
        call("manifest: route", "evidence_manifest_route", {"manifest": manifest, "route": "0", "status": "succeeded",
                                                            "reason": "local file"})
        call("manifest: frames", "evidence_manifest_add", {"manifest": manifest, "kind": "frames",
                                                           "path": out + "/frames.json",
                                                           "command": "MCP extract_media_assets, interval 2"})
        call("manifest: transcript", "evidence_manifest_add", {"manifest": manifest, "kind": "transcript", "path": srt,
                                                               "transcript_source": source, "language": args.language,
                                                               "command": how})
        call("manifest: outline", "evidence_manifest_add", {"manifest": manifest, "kind": "visual_outline",
                                                            "path": out + "/visual_outline.json",
                                                            "command": "MCP align_transcript_frames"})
        record = json.loads((host / manifest).read_text(encoding="utf-8"))
        frame_evidence = next(e["id"] for e in record["artifacts"] if e["kind"] == "frames")
        inspected = ",".join("%s.f%03d" % (frame_evidence, n) for n in range(1, len(listed) + 1))
        call("manifest: rate", "evidence_manifest_rate", {
            "manifest": manifest, "visual": "sampled", "frames_inspected": inspected, "audio": audio_rating,
            "alignment": "timestamp-aligned",
            "gaps": ["Automated smoke run: the frames were checked by a script (present and non-empty), not looked at."]})
        call("manifest: verify", "evidence_manifest_verify", {"manifest": manifest})
        rendered = call("manifest: render", "evidence_manifest_render", {"manifest": manifest, "output": out + "/answer.md"})
        print(rendered["text"])
        assert rendered["text"].strip() == (host / out / "answer.md").read_text(encoding="utf-8").strip()
        call("manifest: lint", "evidence_manifest_lint", {"file": out + "/answer.md"})
    print("\nROUTE 0 THROUGH MCP: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
