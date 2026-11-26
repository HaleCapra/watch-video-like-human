#!/usr/bin/env python3
"""Route 0 from end to end on one small file, as a smoke test for CI and for the Docker image.

    python tools/route0_smoke.py VIDEO --work WORK [--language en] [--model tiny] [--backend auto]
                                 [--expect WORD] [--srt READY.srt]

It runs the skill's own scripts in the documented order and stops at the first failure:

    extract_media_assets.py -> transcribe_local.py -> align_transcript_frames.py
    -> evidence_manifest.py init / route / add / rate / verify / render / lint

Nothing here is part of the skill. It exists so that a machine with no person at it can show that
the tools are installed and work together. The disclosure it renders says so: the frames were
checked by this script (they exist and decode), not looked at.

--srt skips the speech recogniser and uses a transcript that already exists (for a quick local
check of everything else).

Exit code 0 when every step passed; otherwise the failing step's output is printed and the code is 1.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(os.environ.get("WVLH_SCRIPTS") or ROOT / "skills" / "watch-video-like-human" / "scripts")


def step(title, name, *args, ok=(0,)):
    command = [sys.executable, "-I", "-B", str(SCRIPTS / name), *[str(a) for a in args]]
    print("\n== %s\n$ %s %s" % (title, name, " ".join(str(a) for a in args)), flush=True)
    proc = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    if proc.returncode not in ok:
        print(out[-3000:])
        print(err[-3000:], file=sys.stderr)
        raise SystemExit("FAILED at: %s (exit %d)" % (title, proc.returncode))
    return out, err


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video")
    parser.add_argument("--work", required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument("--model", default="tiny")
    parser.add_argument("--backend", default="auto")
    parser.add_argument("--expect", action="append", default=[],
                        help="A word that must appear in the transcript (case-insensitive). Repeatable; one hit is enough.")
    parser.add_argument("--srt", help="Use this transcript instead of running the recogniser.")
    args = parser.parse_args()

    video = Path(args.video).resolve()
    work = Path(args.work).resolve()
    if work.exists():
        shutil.rmtree(str(work))
    work.mkdir(parents=True)
    manifest = work / "evidence_manifest.json"

    out, _ = step("frames and audio", "extract_media_assets.py", video, "--out-dir", work, "--interval", "2")
    frames = json.loads((work / "frames.json").read_text(encoding="utf-8"))
    listed = frames.get("frames") or []
    assert listed, "no frames were extracted"
    for item in listed:
        picture = Path(frames.get("frames_dir") or work / "frames") / item["file"]
        assert picture.is_file() and picture.stat().st_size > 500, "frame missing or empty: %s" % picture
    audio = work / "audio.wav"
    assert audio.is_file() and audio.stat().st_size > 10000, "no audio was extracted"
    print("frames: %d, audio: %d bytes" % (len(listed), audio.stat().st_size))

    srt = work / "audio.srt"
    if args.srt:
        shutil.copyfile(args.srt, str(srt))
        source, how = "manual", "copied from %s (the recogniser was skipped)" % args.srt
    else:
        out, err = step("speech to text", "transcribe_local.py", audio, "--language", args.language,
                        "--model", args.model, "--backend", args.backend)
        print(out[-1500:])
        source, how = "asr", "python scripts/transcribe_local.py audio.wav --language %s --model %s --backend %s" % (
            args.language, args.model, args.backend)
    text = srt.read_text(encoding="utf-8")
    spoken = " ".join(line for line in text.splitlines() if line.strip() and not line.strip().isdigit() and "-->" not in line)
    print("transcript: %r" % spoken[:400])
    assert spoken.strip(), "the transcript is empty"
    if args.expect:
        assert any(word.lower() in spoken.lower() for word in args.expect), \
            "none of %r is in the transcript" % (args.expect,)

    step("align speech and frames", "align_transcript_frames.py", "--transcript", srt, "--frames", work / "frames.json",
         "--output", work / "timeline.json", "--speech-source", "transcribed")
    assert (work / "timeline.json").is_file() and (work / "visual_outline.json").is_file()

    step("manifest: init", "evidence_manifest.py", "init", "-m", manifest, "--source", video, "--title", "CI smoke run")
    step("manifest: route", "evidence_manifest.py", "route", "-m", manifest, "--route", "0", "--status", "succeeded",
         "--reason", "local file")
    step("manifest: frames", "evidence_manifest.py", "add", "-m", manifest, "--kind", "frames", "--path", work / "frames.json",
         "--command", "python scripts/extract_media_assets.py VIDEO --out-dir WORK --interval 2")
    step("manifest: transcript", "evidence_manifest.py", "add", "-m", manifest, "--kind", "transcript", "--path", srt,
         "--transcript-source", source, "--language", args.language, "--command", how)
    step("manifest: outline", "evidence_manifest.py", "add", "-m", manifest, "--kind", "visual_outline",
         "--path", work / "visual_outline.json", "--command", "python scripts/align_transcript_frames.py ...")
    record = json.loads(manifest.read_text(encoding="utf-8"))
    frame_evidence = next(e["id"] for e in record["artifacts"] if e["kind"] == "frames")
    inspected = ",".join("%s.f%03d" % (frame_evidence, n) for n in range(1, len(listed) + 1))
    step("manifest: rate", "evidence_manifest.py", "rate", "-m", manifest, "--visual", "sampled",
         "--frames-inspected", inspected, "--audio", "transcribed" if source == "asr" else "captions-only",
         "--alignment", "timestamp-aligned",
         "--gap", "Automated smoke run: the frames were checked by a script (present and non-empty), not looked at.")
    step("manifest: verify", "evidence_manifest.py", "verify", "-m", manifest)
    answer = work / "answer.md"
    step("manifest: render", "evidence_manifest.py", "render", "-m", manifest, "--output", answer)
    print(answer.read_text(encoding="utf-8"))
    step("manifest: lint", "evidence_manifest.py", "lint", "--file", answer)
    print("\nROUTE 0 SMOKE: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
