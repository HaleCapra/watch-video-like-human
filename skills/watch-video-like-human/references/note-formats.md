# Note Formats (optional)

Use these when the user asks for notes and has not prescribed a format. If they ask for one
document, a summary, or only frames, deliver that and nothing more. Read
`references/note-workflow.md` first: these formats hold the result of that workflow, they do not
replace it.

These are first-pass extraction formats. Keep every independent point, list item, compared
dimension, condition and worked example the video contains. A heading with nothing real to put
under it is left out, not filled with invented material. Keep three voices distinguishable: what
the video said or showed, a mnemonic the teacher offered, and your own regrouping (label that
"整理归纳 / my regrouping").

Every response still begins with the `What I Actually Did` disclosure from `SKILL.md`.

## Where files go

```text
notes/<subject>/<course>/<lesson title>-预习.md
notes/<subject>/<course>/<lesson title>-复习.md
notes/<subject>/<course>/assets/<video name>/<frame or crop>.jpg|png
```

- Use the directory the user names; otherwise the current task directory, and state the path.
  Never write into a notes vault or any other folder the user has not asked you to write to.
- **Pictures are referenced by relative path**: copy each cited frame or crop into
  `assets/<video name>/` beside the notes and link it as
  `![what is visible](assets/<video name>/frame_000012.jpg)`. No absolute paths, no paths into a
  temporary work directory, no base64 blobs. A link must point at a file that exists; if a
  picture could not be saved, say so instead of writing a link.
- `assets/` holds only pictures the notes cite. Each one gets its real time and a line saying
  what is visible in it.
- Existing complete notes are not overwritten unless asked; if one of two is missing, write the
  missing one.
- The transcript, the three-column draft and `evidence_manifest.json` stay in the work
  directory. Keep the source video where it is - later frames need it.

## Teaching video: two documents

### 预习 Preview - the knowledge itself

1. **One-page tree.** A code-block tree of the whole lesson in which every line is a full
   assertion - a concept, a judgement, a condition, a result - not a "Section 1 / Section 2"
   label. Confusable points and limits of applicability hang under the node they belong to.
2. **Sections.** Same structure as the tree. Definitions, conditions, differences and common
   mistakes written out so each can be read on its own. Organised by logic, not by the order of
   the class. Examples only if they are in the material.
3. **Index tables (when useful).** Several pairings, stages or properties of one concept
   gathered in a table. An entry from another lesson only if you actually read that lesson's
   notes, with the source named.

Discipline: no timestamps, no frame images and no "the teacher then says" narration here - the
evidence lives in the draft and in the review document. Numbers, formulas, option letters and
terms are written after checking them against the picture; what could not be checked keeps its
`[待证]` or `[仅转录]` tag in place. A spoken analogy may be kept for its value, but not dressed
up as printed text or as something seen.

### 复习 Review - recall, method, distinctions

Open with one line on how to use it: cover the preview, test yourself on the skeleton, jump back
by time anchor where memory fails.

1. **Recall skeleton.** A short label tree for self-testing; it does not repeat the preview's
   assertions. Nodes worth re-watching carry `t=mm:ss` (`t=hh:mm:ss` beyond an hour).
2. **Methods.** "Faced with this kind of problem, where do you start", taken from real
   instances in the video: the instance, what is done, why, under which conditions, and the
   anchor. The shape follows the content; do not invent methods to reach a count.
3. **Pitfalls and distinctions.** The specific mistakes, wrong approaches, limits and
   near-neighbour concepts of this lesson, each with a real instance, the verdict, the reason and
   an anchor. An ASR typo is never reported as the teacher's mistake.
4. **Open items (when any).** One row per unresolved point, matching the draft: where, what
   exactly, what was checked, what remains. Include the issue ids from
   `evidence_manifest.py list`. "Recorded" is not "resolved".

Discipline: anchors are copied from transcript segments or real frame times. With chunk-level
timing write the range and "chunk-level" rather than a precise second. Where the material gives
no reason, write "the video does not explain why" instead of supplying one. Length follows
content, not duration.

## 讲评课 Exam-review class: paper map and criteria

Still two documents, with a different centre:

- **Preview:** the structure of the paper; an index of question number -> topic -> answer; the
  conditions each question turns on. Scores or pass marks that are not on the paper are not
  invented.
- **Review:** the decision rules, elimination moves and condition checks that recur, with the
  real questions that show them - not a copy of the whole answer key.
- Question numbers, option text, which letter belongs to which option, ticks and crosses, and
  handwritten conclusions are taken from the picture first. A letter that appears only in the
  transcript is written `[字母待证]`, not as a confirmed answer.
- No full solution is constructed where the picture shows none. When sub-sections restart their
  numbering, identify a question by "sub-section + printed number".

## Non-teaching video: one report

For reviews, benchmarks, unboxings, launches and the like:

1. **Summary** - the main conclusions with their qualifications.
2. **Findings by topic** - data and comparisons; units, axes, test conditions and product
   versions as the picture shows them.
3. **Key frames** - picture, time, what is visible. Product and people names are not guessed
   from similar-sounding ASR words.
4. **Reservations** - methods not shown, missing conditions, what must not be extrapolated.
5. **Corrections** - where transcript, external OCR and picture disagreed, and how it was
   settled.

Claims the video's author makes and you did not verify stay attributed to the author.
