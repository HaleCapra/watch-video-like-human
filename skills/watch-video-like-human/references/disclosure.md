# The Disclosure Format

Every answer about a video starts with the same block, whatever route was used and whether the
attempt succeeded, was partial, or was blocked. The block is the product of this skill as much as
the summary is: it tells the reader how far to trust what follows.

## The block

```markdown
## What I Actually Did
- **路由 Route:** <0|A|B|C> - <name>
- **路由过程 Route history:** <every attempt in order, failures with their reason>
- **Verdict:** <one of the verdicts below - computed from the ratings, never chosen>
- **Visual:** <none | second-hand | sampled | continuous> - <how many pictures were opened, and when>
- **Audio:** <none | second-hand | captions-only | transcribed | heard> - <what that means here>
- **Alignment:** <none | chapter-level | timestamp-aligned>
- **On-screen text:** <none | burned-in caption text | external OCR text (second-hand)>
- **Coverage:** <runtime; transcript span; frames extracted versus opened; self-checks>
- **Known gaps:** <what is missing, in plain words>            (when there are any)
```

Optional lines appear only when they apply, in this order after Coverage: `Second-hand
evidence`, `Claims on record`, `Unresolved issues`, `Known gaps`, `Evidence manifest`.

Rules that hold for every line:

- **One channel, one rating.** Visual, Audio and Alignment are never merged into a single
  sentence such as "analysed the video".
- **Rate what was done, not what was possible.** A complete file on disk is not a watched video;
  120 extracted frames of which 9 were opened is "9 of 120".
- **`none` is a rating, not an omission.** Write the line and say `none`.
- **Numbers, not adjectives.** Frame counts and timestamps, a transcript span in `mm:ss`, a
  runtime. Never "most of", "thoroughly", "in detail".
- **The verdict follows from the ratings** by the table in `SKILL.md`. If the sentence you want
  to write needs a higher verdict, the evidence is missing - get it or lower the sentence.

## What each route can honestly reach

| Route | Visual at best | Audio at best | Typical verdict | What it can never claim |
|---|---|---|---|---|
| **0** user file | `sampled` (`continuous` only with a real continuous-video process) | `transcribed` | Complete audio + sampled visuals | - |
| **A** download | `sampled` | `transcribed`, or `captions-only` with `--detail transcript` | Complete audio + sampled visuals / Captions only | - |
| **B** browser | `sampled` - page screenshots at seek points | `captions-only` | Captions + sampled visuals | anything heard: tone, music, sound, who is speaking |
| **C** recording | `sampled` from the recording | `transcribed` when the loopback device carried signal | Complete audio + sampled visuals | that the recording shows the video, until the check frames were opened |
| any, blocked | `none` | `none` | No reliable video analysis | everything |

## One example per route

**Route 0**

```markdown
## What I Actually Did
- **路由 Route:** 0 - user file
- **路由过程 Route history:** 0 succeeded (user supplied the file)
- **Verdict:** Complete audio + sampled visuals
- **Visual:** sampled - 14 of 38 actually looked at (00:00, 00:42, 01:35, ...); 38 frames extracted (9 scene-change, 28 max-gap, 1 first-frame)
- **Audio:** transcribed - speech recognised from the real audio track; not listened to as audio
- **Alignment:** timestamp-aligned
- **On-screen text:** none
- **Coverage:** runtime 12:40; transcript 00:03-12:36 in 212 segments; 38 frames extracted over 00:00-12:38, 14 of them inspected
- **Known gaps:** frames 15-38 not opened
```

**Route A, transcript detail**

```markdown
## What I Actually Did
- **路由 Route:** A - download
- **路由过程 Route history:** A succeeded (captions fetched; no media downloaded)
- **Verdict:** Captions only
- **Visual:** none
- **Audio:** captions-only - no audio was heard or transcribed; text is auto-generated (machine speech recognition) captions
- **Alignment:** timestamp-aligned
- **On-screen text:** none
- **Coverage:** runtime 31:05; transcript 00:00-31:02 in 540 segments; transcript read in full
```

**Route B**

```markdown
## What I Actually Did
- **路由 Route:** B - browser extraction
- **路由过程 Route history:** A failed (sign-in check; not bypassed) -> B succeeded (transcript panel + 6 screenshots)
- **Verdict:** Captions + sampled visuals
- **Visual:** sampled - 6 of 6 page screenshots actually looked at; taken at 01:15, 02:45, 03:30, 04:30, 05:45, 08:15 (stills of the player in the page, not frames of a media file)
- **Audio:** captions-only - no audio was heard or transcribed; text is human-written captions
- **Alignment:** timestamp-aligned
- **On-screen text:** none
- **Coverage:** runtime 12:40; transcript 00:00-12:38 in 198 segments; 6 page screenshot(s) over 01:15-08:15
- **Known gaps:** nothing between the six screenshots was seen; no audio of any kind
```

**Route C**

```markdown
## What I Actually Did
- **路由 Route:** C - screen + loopback recording
- **路由过程 Route history:** A failed (source unsupported) -> B failed (no caption track) -> C succeeded (user present, 150 s recorded)
- **Verdict:** Complete audio + sampled visuals
- **Visual:** sampled - 8 of 22 actually looked at (...); 22 frames extracted
- **Audio:** transcribed - speech recognised from the real audio track; not listened to as audio
- **Alignment:** timestamp-aligned
- **On-screen text:** none
- **Coverage:** runtime 02:30 of recording, video starts 7.0 s in; transcript 00:07-02:28 in 41 segments; recording self-check: picture has_picture, audio signal_present, check frames confirmed to show the video
- **Known gaps:** times are on the recording's clock; subtract 7.0 s for the video's clock
```

**Blocked** - still starts with the route:

```markdown
## What I Actually Did
- **路由 Route:** C - screen + loopback recording (blocked)
- **路由过程 Route history:** A failed (network blocked) -> B failed (no browser tool in this host) -> C blocked (every frame black: protected playback)
- **Verdict:** No reliable video analysis
```

## Producing it

With scripts available, do not write the block by hand:

```bash
python scripts/evidence_manifest.py verify -m WORK/evidence_manifest.json
python scripts/evidence_manifest.py render -m WORK/evidence_manifest.json                  # the Markdown block
python scripts/evidence_manifest.py render -m WORK/evidence_manifest.json --format json    # the same, as fields
```

`render` refuses a manifest that does not verify. `--format json` gives `schema: disclosure/1`
with `route`, `blocked`, `route_history`, `verdict`, `levels` and one entry per line (`label`,
`text`, `evidence` ids), for hosts or tools that want data rather than Markdown.

Without a manifest (a browser-only session, a host that cannot run scripts), write the block by
hand from the template above and say that no manifest exists. If a shell is available at all,
check the hand-written answer:

```bash
python scripts/evidence_manifest.py lint --file answer.md
```

`lint` fails when the block is not the first thing in the answer, a channel line is missing, a
level is not one of the allowed words, a `sampled` Visual line has no count or timestamp, or the
Verdict does not follow from the ratings. It checks the form. It cannot check that the ratings
are true - only the manifest can do that.

## Contact sheets: seen as tiles (v5.6)

`contact_sheet.py` puts many frames on one picture, each tile labelled `#INDEX TIME`. It is a way
to look over a long video quickly and decide which frames to open. What it counts for follows
from what was really done:

- **A sheet nobody opened counts for nothing.** Making it is like extracting frames: files on disk.
- **A sheet you opened counts as its frames seen as tiles.** List the sheet's id in
  `--frames-inspected` (`E6.s001`). The Visual line then says so in words, and keeps the two
  numbers apart: `3 of 40 actually looked at (...), plus 21 seen only as tiles of a contact sheet
  (reduced size)`. Coverage repeats it: `3 of them inspected, 21 more only as contact-sheet tiles`.
  When no frame was opened by itself the line starts `none of 40 opened at full size`.
- **A tile is a frame at reduced size.** It is enough to say what kind of picture is where (a
  slide, a face, a chart, a scene change). It is not enough for small text, numbers, option
  letters or fine detail. For those, open the frame itself or a crop and list that id as well.
  `verify` refuses on-screen text whose source is a sheet (`--on-screen-frames E6.s001`).
- **Claims.** A claim may rest on a frame that was seen as a tile of an opened sheet, or on the
  sheet itself. A frame that sits only on a sheet nobody opened supports nothing, as before.
- The level stays `sampled`: tiles never make it `continuous`, and they do not change the Verdict.

`evidence_manifest.py view` shows the same three states for every frame - opened at full size,
seen only as a tile of a contact sheet, extracted and not opened - with the rule `verify` uses.
The page and the review pack (`pack`) are ways to look at the record. Making them or opening
them adds no evidence to any channel.

## Partial results (v5.4)

- **Route** may end in `(partial - see the route history)`: one channel worked and the other did
  not, or only part of the video was captured. The history line says which.
- **Verdict** starts with `Partial` instead of `Complete` (or ends in `(partial)`) and gives the
  share of the video covered, for example `Partial audio + sampled visuals - about 30% of the
  video`. "Complete" is never used for media that covers less than 90% of the video's real length.
- **A recording whose source length is not on record is never "Complete".** On Route C without
  `--source-duration` the verdict drops the word and ends in `completeness unknown: the source
  video's length is not recorded` (for example `Audio + sampled visuals - completeness unknown:
  ...`), and Coverage says how to supply it. A recording is as long as someone let it run.
- **Coverage** on Route C says `video runtime`, `recording length` and `recording offset`, so a
  recording's clock is never mistaken for the video's.
- **On-screen text** has one more level, `on-screen text`: text that is part of the picture but is
  not captions (titles, slides, credits, captions a web player overlays). Like
  `burned-in caption text` it is read by the model from named frames and is never audio evidence.
