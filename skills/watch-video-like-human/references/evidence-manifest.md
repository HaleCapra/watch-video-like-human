# Evidence Manifest Reference

## Evidence Manifest

Keep `evidence_manifest.json` in the work directory for every analysis. It is the record that
lets each line of the disclosure be traced to a file: the route used and every route that
failed first, each product file with its path, SHA-256 and the command that produced it, the
rating of each channel with the evidence ids it rests on, which frames were actually looked
at, and optional claim-to-evidence links.

```bash
M=WORK/evidence_manifest.json
python scripts/evidence_manifest.py init   -m $M --source URL_OR_FILE
python scripts/evidence_manifest.py route  -m $M --route A --status failed --reason "sign-in demanded"
python scripts/evidence_manifest.py route  -m $M --route 0 --status succeeded --reason "user supplied the file"
python scripts/evidence_manifest.py add    -m $M --kind frames --path WORK/frames.json --command "python scripts/extract_media_assets.py ..."
python scripts/evidence_manifest.py add    -m $M --kind transcript --path WORK/audio.srt --transcript-source asr --command "whisper ..."
python scripts/evidence_manifest.py add    -m $M --kind visual_outline --path WORK/visual_outline.json --command "python scripts/align_transcript_frames.py ..."
python scripts/evidence_manifest.py rate   -m $M --visual sampled --frames-inspected E1.f003,E1.f009 \
    --audio transcribed --alignment timestamp-aligned \
    --on-screen-text "burned-in caption text" --on-screen-frames E1.f003 --gap "frames 10-24 not opened"
python scripts/evidence_manifest.py claim  -m $M --text "The slide at 01:35 shows a state diagram" --evidence E1.f009
python scripts/evidence_manifest.py verify -m $M
python scripts/evidence_manifest.py render -m $M
```

- Record **every** route attempt, failures included, in the order tried; `route.history` becomes
  the Route history line.
- `add --kind frames` reads `frames.json` and registers each kept frame (`E1.f001`, ...) with its
  own hash, plus `audio.wav` when the file had an audio track. Other kinds: `media`, `audio`,
  `captions`, `transcript` (`--transcript-source asr|cloud-asr|captions|manual` is required), `timeline`,
  `visual_outline`, `metadata`, `screenshot` (Route B), `continuous-analysis`,
  `audio-native-analysis`, `crops` (reads `crops.json`; each crop becomes `E5.c001`, ...),
  `evidence-draft` (the three-column draft), `notes`, `other`.
- **Extracted is not inspected.** `--frames-inspected` lists the frames you actually opened and
  looked at (or `all`). A `sampled` rating with no inspected frame is rejected, and burned-in
  caption text can only be claimed for inspected frames.
- `verify` re-hashes every file and fails when a file is missing or changed, or when a rating
  outruns the files: `transcribed` without an ASR transcript and an audio file, or on a file
  whose `frames.json` says `"audio": "none"`; `captions-only` without a captions file;
  `continuous` or `heard` without a `continuous-analysis` / `audio-native-analysis` artifact;
  `timestamp-aligned` without a timeline or outline. The verdict is computed from the ratings,
  never typed by hand.
- `render` prints the `What I Actually Did` block from the manifest, each line followed by the
  evidence ids in brackets. It refuses to render a manifest that does not verify. Paste that
  block as the disclosure, then write the summary. When scripts cannot run at all (a pure
  browser session with no shell), write the disclosure by hand and say that no manifest exists.

**Claim records, issues and the transcript read (v5.3, for note-grade work):**

```bash
python scripts/evidence_manifest.py add   -m $M --kind crops --path WORK/crops.json --command "python scripts/crop_frame_region.py ..."
python scripts/evidence_manifest.py claim -m $M --text "..." --start 01:35 --end 01:52 \
    --frames E1.f004,E5.c001 --segments 41-44 --assessment confirmed --reasoning "written on the slide and read aloud"
python scripts/evidence_manifest.py issue -m $M --start 03:05 --end 03:12 --summary "option letter hidden by the cursor" \
    --attempted "frames at 03:05 and 03:09" --attempted "crop of the answer row" --unresolved-reason "never uncovered"
python scripts/evidence_manifest.py rate  -m $M ... --transcript-read full
python scripts/evidence_manifest.py list  -m $M
```

- A structured `claim` keeps the time range, the statement, the picture ids, the transcript
  segment indices (global indices from `read_transcript.py`) with their text, a judgement and
  the reasoning. `--assessment`: `confirmed` (said **and** shown - needs both a picture and a
  segment), `transcript-only` -> `[仅转录]`, `picture-only` -> `[仅画面、未讲解]`, `unverified` or
  `conflict` -> `[待证]`, `not-understood` -> `[未理解]`. The simple `--evidence` form still works.
- `verify` rejects a claim that rests on a picture not listed in `--frames-inspected`, cites a
  segment that does not exist, or whose time range none of its segments touches. Saving a claim
  checks references; it does not certify the statement.
- `issue` is for a problem that affects a conclusion and survived a reasonable effort. It stays
  `open` until `issue-update --status resolved --note "..."` gives real grounds. Open issues
  appear in the rendered disclosure as recorded, not solved.
- `--transcript-read full` is checked against the read log written by `read_transcript.py`.
  Complete notes require `full`; otherwise rate `partial` and deliver a partial result.

**Route B and Route C evidence (v5.3):**

```bash
python scripts/evidence_manifest.py add -m $M --kind captions --path WORK/transcript.srt --caption-origin auto-asr
python scripts/evidence_manifest.py add -m $M --kind screenshot --path WORK/shots/shot_75.png --time 75
python scripts/evidence_manifest.py add -m $M --kind recording-check --path capture.postcheck.json --confirmed-shows-video
python scripts/evidence_manifest.py render -m $M --format json
python scripts/evidence_manifest.py lint --file answer.md
```

- `--caption-origin human|auto-asr|translated|unknown` is shown on the Audio line of a
  `captions-only` disclosure.
- `--time` on a screenshot is the player's time when it was taken; the Visual line then lists
  the screenshots with their times and says how many were opened.
- `recording-check` is the recorder's `NAME.postcheck.json`. With Route C in use, `verify`
  requires one, rejects `sampled` on a black recording or without `--confirmed-shows-video`, and
  rejects `transcribed` on a silent one.
- `render --format json` is the same disclosure as fields (`schema: disclosure/1`).
- `lint` checks a hand-written block against the format; see `references/disclosure.md`.

**Added in v5.4, from the real-video tests on Windows, macOS and Linux:**

```bash
# The length of the ORIGINAL video. Give it for Route C and for focused extracts.
python scripts/evidence_manifest.py init -m $M --source URL --source-duration 7:46
# Captions AND a transcript are both recorded (the usual Route A case): say which one a claim cites.
python scripts/evidence_manifest.py claim -m $M --text "..." --start 02:14 --end 02:30 --segments 22-24 --transcript E5 --assessment transcript-only
# A claim recorded by mistake is withdrawn, not deleted; other ids do not move.
python scripts/evidence_manifest.py claim-update -m $M --id C2 --status withdrawn --note "misread the frame"
# One channel worked and the other did not, or only part of the video was captured.
python scripts/evidence_manifest.py route -m $M --route C --status partial --reason "audio clean; picture covered from 00:35"
# The download used the user's own browser login, with their yes. Only the browser's name is kept.
python scripts/evidence_manifest.py route -m $M --route A --status succeeded --browser-login firefox
# Text that is part of the picture but is not captions, and a note on what was read.
python scripts/evidence_manifest.py rate -m $M ... --on-screen-text "on-screen text" --on-screen-frames E1.f066 --on-screen-note "credits: music by ..."
```

- `--status` is `succeeded`, `partial`, `failed`, `blocked` or `skipped`: `failed` and `skipped`
  only add history, `succeeded` / `partial` mark the route whose material is used, and `blocked`
  is for the last route tried when nothing worked. A later `succeeded` or `partial` clears an
  earlier route's `(blocked)` mark; the Route line shows the used route's own status.
- `--on-screen-text` takes exactly one of `none`, `burned-in caption text`, `on-screen text`,
  `external OCR text (second-hand)`. It is a level, not free text; describe what was read with
  `--on-screen-note "..."`.
- `--source-duration` (on `init`, or on `rate`; `rate --media-covers START-END` names the stretch
  by hand): a recording or file that covers less than 90% of the video gets a verdict that
  starts with `Partial` and states the share, and the Coverage line gives the stretch covered.
  On Route C the stretch is derived from the recording offset in `timeline.json`; Coverage also
  states that offset and labels the runtime "recording length". Without it, Route C's verdict
  cannot say "Complete": it reads `... - completeness unknown: the source video's length is not
  recorded`, Coverage says the same, and `rate` prints how to supply the length.
- With both captions and a recognised transcript on record, a `transcribed` Audio line rests on
  the recognised transcript only. Coverage lists captions and transcript separately; their
  segment counts are never added up. Crops are counted apart from frames.
- **Frames are renumbered** whenever they are extracted again with other settings or with added
  `--at` moments: `frame_000029.jpg` then holds another moment. `frames.json` carries a
  `frame_set_id`; `timeline.json` / `visual_outline.json` copy it. The extractor renames a
  timeline or outline built from another set to `*.stale.json` and says so, and `verify` rejects
  one whose id differs from the recorded frame set, as well as any frame file whose content
  changed. Order of work: extract (cue frames included) -> align -> `add --kind frames` -> claims.
- `add --kind frames` also keeps `dropped_by_reason` (duplicates, the frame cap, look-alike
  frames of scene-change bursts); thinned bursts are mentioned in Coverage.
- `add --kind metadata` on a JSON file with `duration` gives Route B a video runtime in Coverage.
- `add --kind captions|transcript --language en` records the language of the text that was really
  read; the Audio line prints it. On Route B a manifest with screenshots but no caption language
  says "caption language not recorded" - a caption track in the wrong language (the player picks
  its own default) must never pass silently as the transcript.
- The read log proves the transcript was *served* to the end, page by page. It cannot prove it
  was understood; that stays the reader's responsibility.
