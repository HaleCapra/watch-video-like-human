# Note-grade Workflow: Read Everything, Look Closely, Keep What You Could Not Settle

Read this before writing **complete notes** from a video - lecture notes, a study guide, a
review of a recorded class, a detailed report. A short answer to one question ("what does he
say at 12:30?") does not need it. The four routes and the three-channel disclosure in `SKILL.md`
are unchanged; this file is about what happens after the material is on disk.

The job at this stage is **faithful extraction**: keep the definitions, conditions, list items
and examples the video really contains, with a trace back to where each came from. Plain wording
is fine. Dropping content to make the notes look tidy, or inventing a "method" or "pitfall" to
fill a heading, is not.

## 1. The picture comes first; OCR only assists

1. **Open the frame and look at it.** Printed slides, handwriting, charts, formulas and exam
   questions are all treated the same way: your own look at the image is the evidence. Reading a
   file name, a timestamp or somebody else's description is not looking.
2. **Too small to read? Climb the ladder in this order** - cropping is the last step:

   ```bash
   # 1. the same moment at full source width
   python scripts/extract_media_assets.py VIDEO --out-dir WORK --width 0 --at 83.4
   # 2. nearby frames: the board is often clearer, or less covered, a moment later
   python scripts/extract_media_assets.py VIDEO --out-dir WORK --width 0 --at 82,83.4,85,88
   # 3. only then, crop the region at source resolution
   python scripts/crop_frame_region.py VIDEO --at 83.4 --region 0.05,0.30,0.50,0.25 --out-dir WORK
   ```

   `--region` is `x,y,width,height` as fractions (0-1) of the frame, origin top-left. The crop is
   cut from the decoded source frame and saved as a lossless PNG. It is only ever scaled **down**,
   never up, and it cannot recover detail the source video does not contain: a 480p upload stays
   480p. Register crops with `evidence_manifest.py add --kind crops --path WORK/crops.json`; they
   get ids such as `E5.c001` and count as pictures you can cite once you have opened them.
3. **OCR is a tool for dense text, used after looking, never instead of it.** The default path
   has no OCR engine at all. If the user configured `analyze_keyframes.py`, its text is
   second-hand: take every character you intend to use back to the image and check it there.
   Do not run OCR "because the page is printed", and do not run it on every cited frame.
4. **Some things only the picture can settle**, whatever any OCR text says: coordinates and
   axes, arrows, colours, circles and underlines, which option letter belongs to which line,
   superscripts and subscripts, fractions, roots, and how blocks are laid out relative to each
   other.
5. **If you cannot view images at all**, say that visual verification was not done. Notes built
   from the transcript alone may still be delivered, labelled as such; they are not verified
   video notes.

## 2. Read the whole transcript - a hard rule

Before writing complete notes you **must** read every segment of the transcript.

```bash
python scripts/read_transcript.py WORK/transcript.srt                # segments 1-200
python scripts/read_transcript.py WORK/transcript.srt --offset 200   # ... until next_offset is null
python scripts/read_transcript.py WORK/transcript.srt --status
python scripts/read_transcript.py WORK/transcript.srt --gaps --duration 1830
```

- Keep going until `next_offset` is `null`. **Forbidden as a substitute for the full read:**
  reading only the beginning and the end, keyword search, sampling pages, or reading a summary.
- The script writes a read log beside the transcript. `evidence_manifest.py rate
  --transcript-read full` is checked against that log and is rejected when pages are missing.
  If the transcript was only partly read, rate it `partial`, say so in the disclosure, and
  deliver a partial result - not "complete notes".
- The number in `[brackets]` is the segment's **global index**. Cite that index in claims, not
  the row's position on a page.
- **Chunk-level timing.** When `timing` is `chunk` (long blocks, as some remote ASR services
  return), a block's time range is where a sentence lies, not when it was said. Cite the range
  and its precision ("06:00-06:30, chunk-level"). Find the exact moment with frames if you need
  it; never manufacture a precise anchor from a block.
- **Gaps longer than 20 seconds are leads.** `--gaps` lists them. Look at the frames inside each
  window: it may be silence, a break, music, a demonstration with no narration, or content the
  transcript missed. Record what it turned out to be. A gap is not proof that something is
  missing, and it is not safe to ignore.
- Every time anchor in the notes is copied from a segment or from a frame's real time. Never
  estimate one from memory. On a long video, re-check three to five anchors spread over the
  beginning, middle and end; if one is wrong, re-check every anchor that came from the same
  source, not just the one you happened to test.

## 3. The three-column working draft

Split the video into parts by meaning (not by fixed minutes). For each part keep this table in
the work directory - it is a working paper, not the deliverable:

| 转录依据 Transcript basis | 画面依据 Picture basis | 冲突与待证 Conflicts and open points |
|---|---|---|
| Segment indices, their time range in seconds, the original words | The frame or crop id, the time requested, **what is actually visible in it**, and which statement it supports | Where the two differ, what was checked, what is still unresolved |

Rules for filling it:

- After fetching a frame, check what it really shows - section title, question number, object,
  annotation. The moment the speaker changes topic is not automatically the moment the picture
  changes. Title cards, watermarks, a desktop or a chat window are not content pictures.
- A clear picture may correct ASR or OCR text. Printed text can be wrong too. When transcript
  and picture disagree, decide from neighbouring frames, context and a derivation you can
  re-check; a transcript mismatch alone never proves the speaker misspoke.
- Coverage is judged by content, not by a frame quota. Few pages means few frames; do not pad
  with duplicates, and do not stop at a round number.

### Tags

Anything that is not confirmed by both channels carries a tag, in the draft **and** in the
final notes. Merging parts must not erase a tag.

| Tag | Meaning | `claim --assessment` |
|---|---|---|
| (none) | The transcript says it and a picture you opened shows it | `confirmed` |
| `[仅转录]` | Said, but no picture was found that shows it | `transcript-only` |
| `[仅画面、未讲解]` | Visible on screen, never explained in speech | `picture-only` |
| `[待证]` | Could not be settled, or transcript and picture conflict and it is unresolved | `unverified` / `conflict` |
| `[未理解]` | The material is there, but what it means is not clear to you | `not-understood` |

Never turn a tagged item into a confirmed fact by filling the hole with general knowledge.

## 4. Do not take half an item

- **Enumerations.** "Three differences", "five conditions": write out every item. If you have
  two of three, the third is somewhere in the following frames or sentences - go and get it.
- **Comparison tables.** Cover every row and every compared dimension, not the header and the
  first column.
- **Writing in progress and scrolling pages.** A board that is still being written, a page that
  scrolls, code that grows: follow it through the later frames of the same part and take the
  finished state. An early, unfinished board is never the final content. Complementary regions
  of a scrolled page may each need their own frame.
- **Fill before you tag.** If the missing piece is in the material and looking further through
  that part would supply it, supply it. `[待证]` is for what the material cannot settle, not for
  what you did not go back for.
- Automatic keyframes help here but do not guarantee it: deduplication keeps a frame when a
  region changed, yet a board can gain a line between two kept frames. Add frames with `--at`,
  or re-extract that span with `--no-dedupe`.

## 5. Claim records and issues in the manifest

For each key conclusion that goes into the notes, save a structured record:

```bash
M=WORK/evidence_manifest.json
python scripts/evidence_manifest.py claim -m $M --text "Method B needs the matrix to be symmetric" \
    --start 01:35 --end 01:52 --frames E1.f004,E5.c001 --segments 41-44 --assessment confirmed \
    --reasoning "condition is written on the slide and read aloud"
python scripts/evidence_manifest.py claim -m $M --text "The result also holds for n = 0" \
    --start 02:10 --end 02:30 --segments 51-53 --assessment transcript-only
```

A record holds the time range, the claim, the picture ids, the transcript segment indices with
the text they had at that moment, the judgement and the reasoning. It must cite at least one
real picture or one real transcript segment. `verify` rejects a claim whose picture was never
listed as inspected, whose segments do not exist, or whose time range none of its segments
touches. A claim that rests on a chunk-length segment is marked `time_precision: chunk`.

**Saving a record proves the references exist. It does not prove the statement is right** - you
still have to have looked and read.

When something that **affects a conclusion** still cannot be settled after a reasonable effort
(nearby frames, full width, a crop, context), record an issue and carry on with the rest:

```bash
python scripts/evidence_manifest.py issue -m $M --start 03:05 --end 03:12 \
    --summary "Option letter for question 4 is hidden by the cursor" \
    --attempted "frames at 03:05 and 03:09" --attempted "crop of the answer row" \
    --unresolved-reason "the letter is never uncovered in this part"
python scripts/evidence_manifest.py list -m $M          # claims and issues as Markdown tables
```

- **Do not guess the answer.** The issue records the real time range, what was tried and why it
  is still open.
- Not an issue: something you could see fine without OCR; a transient tool error that a retry
  fixed. Do not file issues to look thorough, and do not file the same one twice.
- Put each open issue, with its id, in the open-items section of the deliverable. "Recorded" is
  not "resolved". Close one only with `issue-update --status resolved --note "..."` and real
  grounds for it.

## 6. Before delivering

1. Check content first, format second: is every key item of each part in the notes? Fill what
   can be filled; mark separately what the video never covered, what is missing from the
   material, and what could not be confirmed.
2. Re-check formulas, numbers, conditions, option letters and chart labels against the picture.
3. Frame count, transcript segment count, a successful ASR run or a manifest that verifies do
   not substitute for the content check, and "all checks passed" must not hide a known hole.
4. State the file paths, the range processed, how many pictures are really cited, and what is
   still open. Do not say a picture was looked at, or a fact verified, unless it was.

Formats for the finished notes are in `references/note-formats.md`.
