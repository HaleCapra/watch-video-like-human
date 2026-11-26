# Browser Extraction

JavaScript snippets for Rungs 0-4 of the evidence ladder. Every snippet is a self-contained
expression that returns a value — paste it into whatever "evaluate JavaScript in the page" tool
your environment provides.

Conventions used here:

- Snippets are IIFEs that **return** their result. If your JS tool needs a bare expression or a
  `return` at top level, adjust the wrapper, not the logic.
- Snippets marked `async` return a Promise. If your tool cannot await, use the sync variant
  given alongside, or run the steps as separate calls with a wait in between.
- **Some JS tools do not await an async IIFE: `(async () => {...})()` comes back as `{}`.**
  Several browser-extension script tools are among them. There, drop the wrapper and write the body
  at top level with `await`, ending on the expression you want returned:

  ```js
  const v = document.querySelector('video');
  await new Promise(r => setTimeout(r, 500));
  ({ at: v.currentTime, paused: v.paused })
  ```

  If a snippet returns `{}` where you expected data, this is the cause, not the page.
- Site selectors go stale. Where a selector was re-verified in the field the date is given, and
  the older selector is kept as a fallback. A snippet that returns zero items is first a reason
  to suspect the selector, not proof that the page has nothing.
- Nothing here defeats a protection. Every snippet reads data the page already loaded in order
  to play normally, or drives a control the viewer could click themselves.

---

## 0. Session setup

Before anything else, make the layout predictable. Below roughly 1000-1200px many video sites
switch to a narrow layout where the transcript panel and side rail **do not exist in the DOM at
all** — no amount of clicking will find them.

Resize the window to at least **1280x900** using your environment's window-resize tool, then
confirm:

```js
(() => ({
  innerWidth: window.innerWidth,
  innerHeight: window.innerHeight,
  layoutOk: window.innerWidth >= 1200,
  url: location.href,
  title: document.title
}))()
```

If `layoutOk` is false, resize before continuing. This single check would have saved four dead
clicks in the failure that motivated this skill.

---

## 1. Player state probe (generic, any HTML5 site)

```js
(() => {
  const v = document.querySelector('video');
  if (!v) return { found: false };
  return {
    found: true,
    duration: v.duration,
    currentTime: v.currentTime,
    paused: v.paused,
    muted: v.muted,
    readyState: v.readyState,
    src: v.currentSrc ? v.currentSrc.slice(0, 120) : null,
    textTracks: [...v.textTracks].map(t => ({
      kind: t.kind, label: t.label, language: t.language, mode: t.mode,
      cues: t.cues ? t.cues.length : null
    }))
  };
})()
```

`duration` is the ground truth for runtime. Do not trust a duration you read off a screenshot —
an ad has its own progress bar and its own duration, and mistaking one for the other will make
every timestamp you report wrong.

### Every media element, not just the first

A page can hold more than one player: a preview, a second instance left behind when a player
was closed and reopened, an autoplaying recommendation. `document.querySelector('video')` sees
one of them. Before and after a Route C recording, and whenever audio sounds doubled, list them
all:

```js
(() => [...document.querySelectorAll('video, audio')].map((m, i) => ({
  i, tag: m.tagName, paused: m.paused, ended: m.ended, muted: m.muted, volume: m.volume,
  currentTime: Math.round(m.currentTime * 10) / 10, duration: m.duration,
  visible: m.offsetParent !== null, src: (m.currentSrc || '').slice(0, 80)
})))()
```

Exactly one element should be playing. If two are, pause the extra one before recording. If a
recording is already done and more than one element advanced during it, the audio is two
overlapping copies of the track: discard that audio, do not transcribe it. A muted **tab** is
invisible here - `muted` stays `false` (see `recording-notes.md`).

### Pause before heavy reads

```js
(() => { const v = document.querySelector('video'); if (v) v.pause(); return v ? v.paused : null; })()
```

Pause via the element, not by sending a keystroke — keys go to whatever has focus, which after a
click may not be the player.

---

## 2. Page metadata and chapters

### YouTube

The description holds the author's own chapter list. It is collapsed by default and the
transcript entry point lives inside the expanded region, so expand it first.

```js
(() => {
  const expand = document.querySelector('tp-yt-paper-button#expand, #expand');
  if (expand) expand.click();
  return !!expand;
})()
```

Then read it as data:

```js
(() => {
  const text = el => el ? el.textContent.trim() : null;
  // Two separate lookups, in this order. A single '#a, #b' selector returns whichever comes
  // first in the DOM, and an SVG <g id="description"> comes first: it has no innerText.
  const desc = document.querySelector('#description-inline-expander') ||
               document.querySelector('div#description');
  const body = (desc && desc.innerText) || '';
  const STAMP = /^((?:\d{1,2}:)?\d{1,2}:\d{2})$/;
  const SAME_LINE = /^((?:\d{1,2}:)?\d{1,2}:\d{2})\s*[-–—:]?\s*(\S.*)$/;
  const lines = body.split('\n').map(l => l.trim()).filter(Boolean);
  const chapters = [];
  let layout = null;
  lines.forEach((line, i) => {
    const same = line.match(SAME_LINE);
    if (same) { chapters.push({ timestamp: same[1], label: same[2].trim() }); layout = layout || 'same-line'; return; }
    // Current layout (2026-11): the TITLE is on one line and the bare timestamp on the NEXT one.
    if (STAMP.test(line) && i > 0 && !STAMP.test(lines[i - 1]) && !SAME_LINE.test(lines[i - 1])) {
      chapters.push({ timestamp: line, label: lines[i - 1] });
      layout = layout || 'title-then-timestamp';
    }
  });
  return {
    title: text(document.querySelector('h1.ytd-watch-metadata, h1.title')),
    channel: text(document.querySelector('#channel-name a, ytd-channel-name a')),
    views: text(document.querySelector('#info span.bold, .view-count')),
    published: text(document.querySelector('#info-strings yt-formatted-string')),
    description: body,
    chapterLayout: layout,
    chapters
  };
})()
```

Chapters give you a citable timeline for the cost of one call. Capture them before touching the
player, and reuse them as the seek targets for Rung 3.

**Check the chapter list before using it.** The description shows each chapter as a title line
followed by a timestamp line. A parser that assumes "timestamp then title" on one line pairs
every timestamp with the NEXT chapter's title: the result looks perfectly normal and every
citation is off by one chapter. Sanity checks: the first chapter starts at `0:00`, the last
label is a chapter title and not a section heading such as "Transcript", and the count matches
the chapter markers on the progress bar.

### Generic sites

```js
(() => {
  const meta = n => document.querySelector(`meta[property="${n}"], meta[name="${n}"]`)?.content || null;
  const ld = [...document.querySelectorAll('script[type="application/ld+json"]')]
    .map(s => { try { return JSON.parse(s.textContent); } catch { return null; } })
    .filter(Boolean);
  return {
    title: meta('og:title') || document.title,
    description: meta('og:description'),
    duration: meta('video:duration') || meta('duration'),
    uploadDate: meta('video:release_date'),
    jsonLd: ld
  };
})()
```

`application/ld+json` on video pages frequently carries duration, upload date, and sometimes a
full description — free structured metadata that costs one call.

---

## 3. Ads

Detect, then use the platform's own Skip control if it is offered. If it is not offered, wait —
do not try to remove, mute, or seek past it.

```js
(() => {
  const player = document.querySelector('#movie_player');
  const adShowing = !!document.querySelector('.ad-showing') ||
                    !!document.querySelector('.ytp-ad-player-overlay');
  const skip = document.querySelector(
    '.ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern'
  );
  return { adShowing, skipAvailable: !!skip, playerFound: !!player };
})()
```

Click the skip control only when `skipAvailable` is true:

```js
(() => {
  const skip = document.querySelector(
    '.ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern'
  );
  if (!skip) return { clicked: false, reason: 'no skip control offered' };
  skip.click();
  return { clicked: true };
})()
```

A click is not proof. In a real test `skip.click()` returned `clicked: true` and the ad kept
playing to its end. **Re-run the detection snippet a few seconds later**; if `adShowing` is
still true, wait for the ad to finish. Do not click again and again.

Always re-probe player state after an ad ends. The layout re-renders and every element
reference you held before the ad is now stale.

---

## 4. Rung 1 — transcript panel, read as data

Open the panel first. On YouTube the button sits inside the expanded description region, so
snippet 2's expand step must run first.

```js
(() => {
  const visible = b => b && b.offsetParent !== null;
  // 1. Structural selector (verified 2026-11): independent of the interface language.
  let btn = [...document.querySelectorAll('ytd-video-description-transcript-section-renderer button')]
    .find(visible);
  let via = 'section-renderer';
  // 2. Fallback: match the button text. The wording changes with language and over time
  //    ("Show transcript", "显示文字记录", "内容转文字" under a "转写文稿" heading, ...).
  if (!btn) {
    btn = [...document.querySelectorAll('button, tp-yt-paper-button')]
      .find(b => /show transcript|transcript|显示文字记录|文字记录|内容转文字|转写文稿/i.test(b.textContent || '') && visible(b));
    via = 'text-match';
  }
  if (!btn) return { opened: false, reason: 'no visible transcript button' };
  btn.click();
  return { opened: true, via };
})()
```

Note `b.offsetParent !== null` — that filter skips hidden duplicate nodes. Clicking a hidden
duplicate reports success and does nothing, which is exactly the trap that burned six rounds in
the motivating failure.

Then read the segments. **Do not use a generic page-text tool for this** — panel content is
routinely excluded from "article content" extraction, so a fully loaded panel returns nothing
and looks like a failure.

```js
(() => {
  // Current panel (verified 2026-11): transcript-segment-view-model. Older panel kept as fallback.
  const READERS = [
    { layout: 'view-model', item: 'transcript-segment-view-model',
      t: '.ytwTranscriptSegmentViewModelTimestamp', x: '.ytAttributedStringHost' },
    { layout: 'segment-renderer', item: 'ytd-transcript-segment-renderer',
      t: '.segment-timestamp', x: '.segment-text, yt-formatted-string.segment-text' }
  ];
  for (const r of READERS) {
    const segs = [...document.querySelectorAll(r.item)];
    if (!segs.length) continue;
    const segments = segs.map(s => ({
      t: s.querySelector(r.t)?.textContent.trim(),
      text: (s.querySelector(r.x)?.textContent || '').replace(/\s+/g, ' ').trim()
    })).filter(x => x.text);
    // The whole transcript stays in the page, one "time text" line per segment, to be read in
    // pieces (section 5, "output is capped"). Only a short transcript is returned directly.
    const lines = segments.map(x => x.t + ' ' + x.text).join('\n');
    globalThis.__wvOut = lines;
    const out = { count: segs.length, layout: r.layout, chars: lines.length,
                  pieces: Math.ceil(lines.length / 900), lastTime: segments.length ? segments[segments.length - 1].t : null };
    if (lines.length <= 700) out.segments = segments;
    return out;
  }
  const loading = !!document.querySelector('ytd-transcript-renderer tp-yt-paper-spinner[active], .loading');
  // Tell "panel not loaded" apart from "panel loaded with markup this snippet does not know".
  const panel = document.querySelector(
    'ytd-engagement-panel-section-list-renderer[visibility="ENGAGEMENT_PANEL_VISIBILITY_EXPANDED"]');
  return { count: 0, loading, panelOpen: !!panel, panelTextLength: panel ? panel.innerText.length : 0 };
})()
```

The reply carries `chars` and `pieces`; a transcript of any real length comes back **without**
`segments` - read it with the piece snippet (`globalThis.__wvOut`), and check that the pieces
add up to `chars` before normalizing it. `count` and `lastTime` tell you whether the panel
covers the whole video.

**Chapters from the panel.** A description without timestamps yields no chapters (section 2),
yet the transcript panel often shows chapter headings between the segments (measured: 0 from
the description, 6 in the panel). Read each heading with the time of the first segment after it:

```js
(() => {
  // Current panel (seen on a real page, 2026-11): one row element per line, headings and segments
  // mixed in document order. Each row sits in a wrapper of its own - they are NOT siblings, so
  // walk the list; nextElementSibling finds nothing.
  const ROW = 'macro-markers-panel-item-view-model';
  const TITLE = ':scope > timeline-chapter-view-model h3.ytwTimelineChapterViewModelTitle';
  const SEGMENT = 'transcript-segment-view-model';
  const TIME = '.ytwTranscriptSegmentViewModelTimestamp, .segment-timestamp';
  const PANEL = 'ytd-engagement-panel-section-list-renderer';
  const clean = el => (el.textContent || '').replace(/\s+/g, ' ').trim();
  let rows = [...document.querySelectorAll(ROW)];
  // Several panels can be in the DOM at once (the chapter list uses the same row element): keep
  // only the panel that also holds transcript segments.
  const transcriptPanels = new Set(rows.filter(r => r.querySelector(SEGMENT)).map(r => r.closest(PANEL)));
  rows = rows.filter(r => transcriptPanels.has(r.closest(PANEL)));
  const chapters = []; let headings = 0, segments = 0, layout = rows.length ? 'macro-markers' : null;
  const heading = label => { if (label) { chapters.push({ timestamp: null, label }); headings++; } };
  const segment = t => { segments++; if (t) for (const c of chapters) if (c.timestamp === null) c.timestamp = t; };
  for (const row of rows) {
    const h3 = row.querySelector(TITLE);
    if (h3) heading(clean(h3)); else if (row.querySelector(SEGMENT)) segment(row.querySelector(TIME)?.textContent.trim());
  }
  if (!rows.length) {
    // Older panel, kept as a fallback. These heading selectors were never seen on a live page.
    const HEAD = 'ytd-transcript-section-header-renderer, transcript-section-header-view-model';
    const OLD = 'ytd-transcript-segment-renderer, transcript-segment-view-model';
    for (const el of document.querySelectorAll(HEAD + ', ' + OLD)) {
      layout = 'section-header';
      if (el.matches(HEAD)) heading(clean(el)); else segment(el.querySelector(TIME)?.textContent.trim());
    }
  }
  return { chapters: chapters.filter(c => c.timestamp !== null), untimed: chapters.filter(c => c.timestamp === null).map(c => c.label),
           headings, segments, rows: rows.length, layout, source: 'transcript panel',
           precision: 'chapter-level: each time is the first transcript line AFTER the heading' };
})()
```

- A heading has no time of its own. Its time is that of the first transcript line after it, which
  can be a few seconds later than the real boundary (measured: 0:00, 1:06, 2:49, 4:26, 5:35,
  6:17 for six chapters). That is `chapter-level` alignment, the same as chapters from the
  description - never a precise anchor.
- A heading is recognised by its element, not by its words. The text carries a localised prefix
  in the same node ("Chapter 2: ...", "第 2 章：..."); keep the label as the page shows it.
- `rows` should equal `headings + segments` (measured: 53 = 6 + 47). `untimed` lists headings with
  no transcript line after them.
- This structure was seen on one page. Other layouts and videos without chapters were not checked:
  if `headings` is 0 while headings are visible in the panel, inspect one heading's tag and adapt
  the selector - do not conclude that the video has no chapters.

If `count` is 0 but `panelOpen` is true and `panelTextLength` is in the thousands, the transcript
**is** loaded and the selectors are stale. Inspect one segment's markup, read it with the new
class names, and do not descend to Rung 2 or 3 for a transcript that is sitting on the page.

**Stop condition:** if this returns `count: 0` twice with an empty panel, or `loading: true`
after ~5 seconds, the panel is not going to load. Move to Rung 2. Some videos — auto-dubbed ones in particular — have
a transcript panel that never resolves. That is a page bug, not something to out-wait.

---

## 5. Rung 2 — the caption track the player already loaded

> **Field note (verified 2026-08): on YouTube this rung now yields the track LIST but not the
> track CONTENT.** Fetching a `baseUrl` returns HTTP 200 with an empty body — the caption
> endpoint is signature-gated, and the signature is produced by the player's own code. Both
> `fmt=json3` and the unmodified URL come back empty.
>
> Do not try to reconstruct the signature. That crosses from "reading what the page loaded"
> into "defeating a control", and it is also a losing maintenance battle.
>
> What this rung is still good for on YouTube: enumerating the tracks, so you can see whether a
> **human-written** track exists (`kind !== 'asr'`) and in which languages. That tells you what
> Rung 1 will give you. For the content itself, use Rung 1 — the transcript panel — because the
> panel's request is made by YouTube's own player code, which knows how to sign it.
>
> **The general principle this teaches:** do not reimplement the page's data fetching. Trigger
> the page's own mechanism and harvest the rendered result. It is more robust and it stays
> inside normal viewing by construction. On other sites the direct fetch may still work — try
> it, and fall back the same way.

### Two tool-level constraints that shape how you write these snippets

Both were hit in real use and both silently produce wrong-looking results:

1. **URLs containing query strings may be redacted** by the agent's browser tool before they
   reach you (they can carry session data). So a two-step "read the URL, then fetch it" flow
   breaks — you get a placeholder instead of a URL. **Select the track and fetch it in ONE
   call**, returning only the parsed text. The URL then never leaves the page context, which is
   both more robust and better hygiene.

2. **The JS tool's output is capped** - about 1,000 characters in two different hosts (a 1.6 KB
   reply came back cut off with `[TRUNCATED]`; another host cut silently). A full transcript, a
   long description or a caption track list never fits. **Any snippet whose reply could be longer
   than about 900 characters keeps the text in the page and hands it over in pieces:**

```js
// 1. keep it: run once, with TEXT being whatever long string the snippet produced
(() => { globalThis.__wvOut = String(TEXT); return { chars: globalThis.__wvOut.length,
                                                     pieces: Math.ceil(globalThis.__wvOut.length / 900) }; })()
```

```js
// 2. read piece N (0, 1, 2, ...): call until `last` is true
((n) => { const s = globalThis.__wvOut || ''; const piece = s.slice(n * 900, n * 900 + 900);
  return JSON.stringify({ n, chars: s.length, from: n * 900, length: piece.length,
                          last: n * 900 + 900 >= s.length, piece }); })(0)
```

   **Then check the total**: the lengths of the pieces you received must add up to `chars`
   (measured: 7,589 characters in nine pieces, equal to the stored length). A total that does
   not match means a piece was cut or skipped - fetch it again; never fill the gap from memory.
   Save the pieces as a JSON list (`[{"n":0,...,"piece":"..."}, ...]`): `normalize_transcript.py`
   joins them and stops with an error when their lengths do not add up to `chars`.
   The transcript reader in section 4 stores its text this way by itself. This applies equally
   to the description (section 2), a caption track list and multi-point samples. For the
   transcript panel there is also a pager that works by **character budget**, not by time (a
   time window that fits one video overflows on the next):

```js
// one page at a time; call again with START = the `next` it returned, until `next` is null
const toSec = t => { const p = t.split(':').map(Number);
  return p.length === 3 ? p[0]*3600 + p[1]*60 + p[2] : p[0]*60 + p[1]; };
const NEW = [...document.querySelectorAll('transcript-segment-view-model')];        // current panel
const OLD = [...document.querySelectorAll('ytd-transcript-segment-renderer')];        // older panel
const [items, T, X] = NEW.length
  ? [NEW, '.ytwTranscriptSegmentViewModelTimestamp', '.ytAttributedStringHost']
  : [OLD, '.segment-timestamp', '.segment-text'];
const all = items.map(s => ({
  t: s.querySelector(T)?.textContent.trim(),
  x: (s.querySelector(X)?.textContent || '').replace(/\s+/g,' ').trim()
})).filter(o => o.x && o.t);
const START = 0, BUDGET = 800;                      // <-- START: index of the first segment wanted
let text = '', i = START;
for (; i < all.length; i++) {
  const line = all[i].t + ' ' + all[i].x;
  if (text && text.length + line.length + 1 > BUDGET) break;   // stop BEFORE the tool would cut it
  text += (text ? '\n' : '') + line;
}
JSON.stringify({ from: START, next: i < all.length ? i : null, total: all.length,
                 lastTime: all.length ? all[all.length - 1].t : null, text })
```

Save what the snippet returned, exactly as returned - one page, a JSON list of all the pages, or
just the lines of text - and `normalize_transcript.py` reads it: it puts pages back in order,
refuses a set whose last page still says `next`, and reads each `0:06 words` line as one segment.
`next: null` means the end was reached; `total` says how many segments there are. A reply that
ends in `[TRUNCATED]` is not data - lower `BUDGET` and ask again. Panel lines carry a start time
only: pass the video's length to `normalize_transcript.py --duration` so the last line gets an
end and the coverage is not understated.

### YouTube

The player object exposes its own response, including the caption tracks it uses to render
subtitles:

```js
(() => {
  const p = document.querySelector('#movie_player');
  const r = (p && p.getPlayerResponse && p.getPlayerResponse()) || window.ytInitialPlayerResponse;
  const tracks = r?.captions?.playerCaptionsTracklistRenderer?.captionTracks || [];
  return {
    videoId: r?.videoDetails?.videoId,
    lengthSeconds: r?.videoDetails?.lengthSeconds,
    title: r?.videoDetails?.title,
    tracks: tracks.map(t => ({
      name: t.name?.simpleText || t.name?.runs?.[0]?.text,
      lang: t.languageCode,
      auto: t.kind === 'asr'
    }))
  };
})()
```

Prefer a human-authored track (`auto: false`) over an auto-generated one when both exist, and
among human tracks prefer a language you were asked for or can read - not simply the first in
the list. Say which language you read: a translated caption track is not a transcript of the
original audio.

Select and fetch the chosen track inside one page-context call. The signed URL never leaves the
page, and only one small time window is returned so the browser tool cannot truncate a full
transcript silently. Change `START` and `END` and repeat only when the endpoint returns content:

```js
(async () => {
  const START = 0;
  const END = 30;
  const p = document.querySelector('#movie_player');
  const r = (p && p.getPlayerResponse && p.getPlayerResponse()) || window.ytInitialPlayerResponse;
  const tracks = r?.captions?.playerCaptionsTracklistRenderer?.captionTracks || [];
  // "First human track" is whatever language sorts first (Arabic, on a 41-track video), not the
  // one you can read. Prefer the page language, then the browser language, then English.
  const base = l => (l || '').toLowerCase().split('-')[0];
  const want = [document.documentElement.lang, navigator.language, 'en'].map(base).filter(Boolean);
  const human = tracks.filter(t => t.kind !== 'asr');
  const byLang = list => want.map(w => list.find(t => base(t.languageCode) === w)).find(Boolean);
  const pick = byLang(human) || byLang(tracks) || human[0] || tracks[0];
  const track = tracks.find(t => t === pick);
  if (!track) return { ok: false, reason: 'no caption track' };
  const url = track.baseUrl + (track.baseUrl.includes('?') ? '&' : '?') + 'fmt=json3';
  const res = await fetch(url, { credentials: 'same-origin' });
  if (!res.ok) return { ok: false, status: res.status };
  const body = await res.text();
  if (!body.trim()) return { ok: false, reason: 'empty signed response' };
  let data;
  try { data = JSON.parse(body); }
  catch { return { ok: false, reason: 'caption response was not JSON' }; }
  const events = (data.events || []).filter(e => e.segs).map(e => ({
    start: e.tStartMs / 1000,
    end: (e.tStartMs + (e.dDurationMs || 0)) / 1000,
    text: e.segs.map(s => s.utf8).join('').replace(/\n/g, ' ').trim()
  })).filter(e => e.text && e.start >= START && e.start < END);
  return {
    ok: true,
    track: {
      name: track.name?.simpleText || track.name?.runs?.[0]?.text,
      lang: track.languageCode,
      auto: track.kind === 'asr'
    },
    window: { start: START, end: END },
    count: events.length,
    segments: events
  };
})()
```

If the fetch fails or comes back empty, drop to Rung 3. Do not construct alternative endpoints
or retry with different parameters — a caption track that will not load through the player's own
path is a stop condition, not a puzzle.

Save the result and run it through `scripts/normalize_transcript.py` to get clean SRT plus a
normalized JSON timeline.

### Generic HTML5 sites

Setting a text track to `hidden` loads its cues without displaying them — the cleanest generic
path there is:

```js
(async () => {
  const v = document.querySelector('video');
  if (!v || !v.textTracks.length) return { ok: false, reason: 'no text tracks' };
  const track = [...v.textTracks].find(t => t.kind === 'subtitles' || t.kind === 'captions') || v.textTracks[0];
  track.mode = 'hidden';
  await new Promise(r => setTimeout(r, 800));   // cues load asynchronously
  const cues = [...(track.cues || [])];
  return {
    ok: cues.length > 0,
    label: track.label,
    language: track.language,
    count: cues.length,
    segments: cues.map(c => ({ start: c.startTime, end: c.endTime, text: c.text }))
  };
})()
```

Also worth one look: `<track src="...">` elements often point straight at a `.vtt` file.

```js
[...document.querySelectorAll('track')].map(t => ({
  kind: t.kind, label: t.label, lang: t.srclang, src: t.src
}))
```

---

## 6. Rung 3 — timed caption sampling

When no full transcript is reachable but captions render on screen, seek and read the caption
text as text. One call per sample point, far cheaper than a screenshot.

Turn captions on first, **and make sure they are in the right language** (YouTube). Clicking
the button alone shows whichever track the player picks - in a real test the first of eleven,
Bulgarian, for an English talk - and every sample then "succeeds" in the wrong language.

```js
(async (WANT) => {            // WANT: the language the user asked for, or null for the video's own
  const p = document.querySelector('#movie_player');
  const btn = document.querySelector('.ytp-subtitles-button');
  if (btn && btn.getAttribute('aria-pressed') !== 'true') btn.click();
  await new Promise(r => setTimeout(r, 600));
  const get = (k) => { try { return p && p.getOption ? p.getOption('captions', k) : null; } catch (e) { return null; } };
  const list = get('tracklist') || [];
  const available = list.map(t => t.languageCode + (t.kind === 'asr' ? ' (auto)' : ''));
  // The video's own language: the auto-generated track is always in the spoken language.
  const original = (list.find(t => t.kind === 'asr') || {}).languageCode || null;
  const wanted = WANT || original;
  const same = (a, b) => !!a && !!b && a.toLowerCase().split('-')[0] === b.toLowerCase().split('-')[0];
  let now = get('track') || {}, switched = false;
  if (wanted && !same(now.languageCode, wanted)) {
    const pick = list.find(t => same(t.languageCode, wanted) && t.kind !== 'asr') || list.find(t => same(t.languageCode, wanted));
    if (pick && p.setOption) {
      p.setOption('captions', 'track', { languageCode: pick.languageCode });
      switched = true;
      // The player announces the change in the caption area itself ("English", "英语 >> ...").
      // Reading in the next seconds returns that notice as if it were speech: let it clear.
      await new Promise(r => setTimeout(r, 3000));
      now = get('track') || {};
    }
  }
  return { captionsOn: btn ? btn.getAttribute('aria-pressed') : null, language: now.languageCode || null,
           kind: now.kind === 'asr' ? 'auto-asr' : (now.languageCode ? 'human-or-translated' : null),
           translated: !!now.translationLanguage, wanted, original, switched,
           // true / false only when there is a wanted language to compare with. Without one (the
           // user named none and the video's own language could not be told) it is null: unknown.
           languageOk: wanted ? same(now.languageCode, wanted) : null, available };
})(null)
```

Read the reply before sampling anything:

- `languageOk: true` - a wanted language was known and it is the one showing.
- `languageOk: false` - the wanted language is not showing (no such track, or the switch did not
  take). **This is not a success.** Either choose from `available` together with the user, or
  report that captions in that language could not be read. Never sample and present another
  language's captions as the transcript.
- `language` is what is really on screen. It goes into every result and into the manifest
  (`add --kind captions --language bg`), and the Audio line of the disclosure shows it. Text in a
  language other than the one spoken is a translation, not what was said: `--caption-origin
  translated`.
- `switched: true` - the snippet has already waited three seconds. Do not sample sooner after
  any later track change either; a sample taken during the notice holds the notice.
- `languageOk: null` - **the caption language could not be confirmed.** Nobody named a language and the
  video's own could not be told, so there was nothing to compare with. It is not a pass: say
  "caption language not confirmed" in the answer, record the `language` that is showing, and do
  not present the text as what was said until it is settled. Two ways to get here:
  - `available` is empty: the player gave no track list (another site, or the API changed).
  - `available` has tracks but none is marked `(auto)`: the video has no auto-generated track,
    which is the only one that tells the spoken language (seen on a real page: 40 tracks, none
    automatic, an English talk showing `zh-CN` captions because the interface was Chinese).
  Settle it by asking the user which language the video is spoken in, or from the title, the
  description and the sound of the transcript itself, then run the snippet again with that
  language as `WANT` - the reply is then `true` or `false`.

Then sample one timestamp:

```js
(async (seconds) => {
  const v = document.querySelector('video');
  if (!v) return { ok: false, reason: 'no video element' };
  const read = () => [...document.querySelectorAll('.ytp-caption-segment')]
    .map(e => e.textContent.trim()).filter(Boolean).join(' ');
  const limit = (p, ms) => Promise.race([p, new Promise(r => setTimeout(r, ms))]);
  const before = read();
  const seeked = new Promise(r => v.addEventListener('seeked', r, { once: true }));
  v.currentTime = seconds;
  await limit(seeked, 8000);
  await limit(v.play().catch(() => {}), 3000);   // play() stays pending while the player buffers
  // Wait for a caption that is NOT the one shown before the seek. A fixed sleep reads the old line.
  let text = '', waited = 0;
  for (; waited < 4000; waited += 200) {
    await new Promise(r => setTimeout(r, 200));
    text = read();
    if (text && text !== before && !v.seeking && v.readyState >= 2) break;
  }
  v.pause();
  const stale = !!text && text === before;
  const track = (() => { try { return document.querySelector('#movie_player').getOption('captions', 'track') || {}; }
                         catch (e) { return {}; } })();
  return { ok: !v.seeking && v.readyState >= 2, at: v.currentTime, requested: seconds,
           caption: stale ? null : (text || null), stale, waitedMs: waited,
           language: track.languageCode || null };
})(150)
```

A brief play is needed — captions do not repaint on a paused seek. The snippet pauses again
immediately so the page stays quiet between samples.

**Never read a caption after a fixed sleep.** Setting `currentTime` returns at once; for the next
few hundred milliseconds the page still shows the caption of the old position, so a fixed wait
pairs the new timestamp with the old line. The snippet waits for the seek to complete and then
for the caption text to *change*. Read the result like this:

- `caption` has text: a line that appeared after the seek. Cite it at `at`, not at `requested`.
- `stale: true`: the text never changed. It is either the same line still running or a repaint
  that never came. It is **not a sample** - retry a second later, or leave the point out.
- `caption: null` with `stale: false`: nothing was on screen (no speech there, or captions are
  off). That is a result, and it is not evidence of silence.

Sample several points in one call when your JS tool supports async:

```js
(async (points) => {
  const v = document.querySelector('video');
  if (!v) return { ok: false, reason: 'no video element' };
  const read = () => [...document.querySelectorAll('.ytp-caption-segment')]
    .map(e => e.textContent.trim()).filter(Boolean).join(' ');
  const limit = (p, ms) => Promise.race([p, new Promise(r => setTimeout(r, ms))]);
  globalThis.__wvAbort = false;            // set it to true from another call to stop this loop
  const started = Date.now(), samples = [];
  for (const s of points) {
    if (globalThis.__wvAbort || Date.now() - started > 35000) break;   // end before the tool gives up
    const t0 = Date.now(), before = read();
    const seeked = new Promise(r => v.addEventListener('seeked', r, { once: true }));
    v.currentTime = s;
    await limit(seeked, 8000);
    await limit(v.play().catch(() => {}), 3000);   // play() stays pending while the player buffers
    let text = '', waited = 0;
    for (; waited < 4000 && !globalThis.__wvAbort; waited += 200) {
      await new Promise(r => setTimeout(r, 200));
      text = read();
      if (text && text !== before && !v.seeking && v.readyState >= 2) break;
    }
    const ok = !v.seeking && v.readyState >= 2;      // false: the seek never finished - not a sample
    const stale = !!text && text === before;
    samples.push({ requested: s, at: Math.round(v.currentTime * 10) / 10, ok,
                   caption: ok && !stale ? (text || null) : null, stale, waitedMs: waited,
                   tookMs: Date.now() - t0 });
  }
  v.pause();
  const track = (() => { try { return document.querySelector('#movie_player').getOption('captions', 'track') || {}; }
                         catch (e) { return {}; } })();
  return { ok: true, samples, usable: samples.filter(x => x.caption).length,
           notReached: points.length - samples.length, aborted: !!globalThis.__wvAbort,
           language: track.languageCode || null };
})([75, 165, 210, 270, 345, 495])
```

**A tool timeout does not stop the page.** In a real test the player buffered for 46 seconds;
the browser tool gave up at 45 s, but the loop kept running in the page and went on moving
`currentTime` for another minute, wrecking every seek made by hand meanwhile. So the loop now
limits `play()` as well as the seek, stops itself after 35 seconds (`notReached` says how many
points are left - ask for those in a second call), and can be stopped from outside: evaluate
`globalThis.__wvAbort = true`. A sample with `ok: false` did not finish seeking: the caption
layer may already show the new time while the picture has not arrived, so it is dropped too.
`waitedMs` counts only the wait for the caption to change; `tookMs` is the whole sample.
When seeks are this slow, `video.buffered` is no guide (it showed 0-33 s while playback had
passed 35 s) - trust `seeking` and `readyState`.

Every result carries `language`: the caption track that was showing when the samples were
taken. Compare it with the language you set; if it differs or is `null`, the samples are not the
transcript you were asked for - say so. With six or more points the reply can pass the tool's
output limit: keep it with the stash snippet (section 5) and read it in pieces.

Feed it the chapter timestamps from Rung 0 converted to seconds. That single call produces a
cited timeline covering the whole video. Report `usable` out of the number requested: sampled
captions are a handful of lines, not a transcript, and the Coverage line must say so.

For other sites, replace the caption selector with whatever the player uses: Bilibili
`.bili-subtitle-x-subtitle-panel-text` (verified 2026-11), `.vjs-text-track-display` (Video.js),
`.plyr__captions` (Plyr), `.jw-captions` (JW Player), or the `cuechange` event on the text track
itself.

**Every sample `caption: null` does not mean "no captions".** With the wrong selector five points
out of five come back empty and look exactly like a video without captions (this happened on
Bilibili with the YouTube selector). Before concluding anything, confirm that the selector
matches at all while a caption is visibly on screen:

```js
(() => ['.ytp-caption-segment', '.bili-subtitle-x-subtitle-panel-text', '.vjs-text-track-display',
        '.plyr__captions', '.jw-captions'].map(s => ({ selector: s, nodes: document.querySelectorAll(s).length,
        text: (document.querySelector(s)?.textContent || '').trim().slice(0, 60) })))()
```

If every `nodes` is 0 while you can see a caption in a screenshot, the player uses another
element: inspect it and use that. Report "captions could not be read", not "no captions".

### Bilibili: the caption track

`video.textTracks` is empty on Bilibili: the player draws captions itself. The track is a JSON
file the player downloads when a caption language is chosen. Choose the language in the player,
find that download among the page's own requests, and read it **in the same call** so the
address never leaves the page (verified in a field test, 2026-11):

```js
(async () => {
  // The language item is added several seconds after the page loads (measured: absent at 6 s,
  // present at 9 s): look for it for up to ten seconds before saying there is none.
  let item = null;
  for (let waited = 0; waited <= 10000 && !item; waited += 500) {
    item = document.querySelector('.bpx-player-ctrl-subtitle-language-item');
    if (!item) await new Promise(r => setTimeout(r, 500));
  }
  if (!item) return { ok: false, reason: 'no caption language item after 10 s: open the caption menu, or the video has none' };
  item.click();
  await new Promise(r => setTimeout(r, 1500));
  // The caption FILE, not the caption API: aisubtitle.hdslb.com/bfs/ai_subtitle/prod/<id>?<query>
  // (no extension), or .../bfs/subtitle/<id>.json for uploaded tracks. The page also calls
  // /x/v2/subtitle/web/view and /x/v2/dm/web/view, whose addresses contain "subtitle" too - those
  // are not caption files, so "contains subtitle" alone picks the wrong one.
  const urls = performance.getEntriesByType('resource').map(e => e.name)
    .filter(u => /aisubtitle|\/bfs\/(ai_)?subtitle\//i.test(u));
  if (!urls.length) return { ok: false, reason: 'no caption file was requested by the player' };
  const data = await (await fetch(urls[urls.length - 1])).json();
  const body = Array.isArray(data.body) ? data.body : [];
  const cues = body.map(c => ({ start: c.from, end: c.to, text: String(c.content || '').trim() })).filter(c => c.text);
  globalThis.__wvOut = JSON.stringify(cues);                 // long: read it in pieces (section 5)
  return { ok: cues.length > 0, count: cues.length, chars: globalThis.__wvOut.length,
           pieces: Math.ceil(globalThis.__wvOut.length / 900),
           language: (item.getAttribute('data-lan') || item.textContent || '').trim() || null,
           first: cues[0] || null, last: cues[cues.length - 1] || null };
})()
```

Read `globalThis.__wvOut` with the piece snippet, check the total, and save it as
`WORK/captions.json`; `normalize_transcript.py` reads this shape directly. Every cue has its own
start and end: **do not pass `--merge`**. An AI-generated track is `--caption-origin auto-asr`.

---

## 7. Rung 4 — visual sampling

Only when the question is visual. Seek first, pause, then screenshot with your environment's
screenshot tool:

```js
(async (seconds) => {
  const v = document.querySelector('video');
  if (!v) return { ok: false, reason: 'no video element' };
  v.pause();
  const seeked = new Promise(r => v.addEventListener('seeked', r, { once: true }));
  v.currentTime = seconds;
  // Wait for the seek to COMPLETE, then for a decodable frame, then for it to be painted.
  await Promise.race([seeked, new Promise(r => setTimeout(r, 8000))]);
  for (let i = 0; i < 40 && (v.seeking || v.readyState < 2); i++) await new Promise(r => setTimeout(r, 200));
  await new Promise(r => setTimeout(r, 400));
  return { ok: !v.seeking && v.readyState >= 2, at: v.currentTime, requested: seconds,
           readyState: v.readyState, seeking: v.seeking, paused: v.paused };
})(320)
```

**Never screenshot after a fixed sleep.** Setting `currentTime` returns at once and reports the
new time while the picture is still the old one: with a fixed 600-900 ms wait, seeks to 70 s and
130 s both produced screenshots of the frame at 20 s, with a buffering spinner on top - correct
timestamps on the wrong pictures, and nothing in the result to show it. Take the screenshot only
when `ok` is true, and treat a visible spinner or a frame identical to the previous one as a
failed sample. One cross-check that costs nothing: with captions on, the caption visible in the
frame should match the transcript line for that timestamp.

Hide the player chrome so controls do not cover the frame:

```js
(() => {
  const p = document.querySelector('#movie_player');
  if (p) p.classList.remove('ytp-autohide-active', 'ytp-hide-controls');
  document.querySelector('video')?.focus();
  return true;
})()
```

**Two consecutive screenshot failures means the renderer is stuck.** Stop screenshotting, verify
the DOM still answers a text query, and if it does, finish the job through text. If it does not,
close the tab and open a fresh one. See "Recovering a Stuck Page" in SKILL.md.

---

## 8. Keeping Route B evidence so it can be disclosed

Route B produces text in a tool result and pictures in a screenshot tool. Unless they are saved
as files, nothing can be hashed, re-checked or cited. When the host can write files:

1. **Transcript or captions**: save the JSON the snippet returned to `WORK/captions.json`, then
   `python scripts/normalize_transcript.py WORK/captions.json --out WORK/transcript`. Add `--merge`
   **only** for word-by-word auto-captions (cues of a word or two); captions that already come as
   lines keep their own times - merged, 103 timed lines became 5 blocks of 40 seconds. A panel
   that gives start times only also takes `--duration SECONDS`.
2. **Screenshots**: save each one as `WORK/shots/shot_<seconds>.png`, where `<seconds>` is the
   `at` value the seek snippet returned - the player's real time, not the time you asked for.
3. **Metadata and chapters**: save the Rung 0 result as `WORK/metadata.json`. A long description
   is read in pieces like any other long text; check the total length before saving.
4. Register them:

   ```bash
   M=WORK/evidence_manifest.json
   python scripts/evidence_manifest.py add -m $M --kind metadata --path WORK/metadata.json --command "page script: player state + chapters"
   python scripts/evidence_manifest.py add -m $M --kind captions --path WORK/transcript.srt --caption-origin human --language en --command "page script: transcript panel"
   python scripts/evidence_manifest.py add -m $M --kind screenshot --path WORK/shots/shot_75.png --time 75 --command "seek 75 s, wait for seeked, screenshot"
   python scripts/evidence_manifest.py rate -m $M --visual sampled --frames-inspected E3,E4 --audio captions-only --alignment timestamp-aligned
   ```

`--language` is the caption track that was really read (the `language` the snippets return), not
the one that was hoped for; the disclosure prints it. `--caption-origin` is `human`, `auto-asr`,
`translated` (by a machine: the player's auto-translate), `human-translation` (a track people
wrote in another language than the one spoken) or `unknown`. Say which: an
auto-generated track mishears names and numbers, and a translated one is not what was said. On
YouTube the caption track list marks generated tracks (`kind: 'asr'`); a track whose language
differs from the video's original language and was produced by the player's auto-translate is
`translated`. When you cannot tell, it is `unknown`.

When the host cannot write files (a pure browser session), write the disclosure by hand from
`references/disclosure.md` and say that no manifest exists.

**What Route B never gives, however well it goes:** real audio (tone, music, sound, who is
speaking), anything between two screenshots, and frames at source resolution - a screenshot is
the page at the window's size.

**When the host has no browser tool**, Route B does not exist. Do not imitate it by fetching the
page's HTML with a command-line client: the player loads its data with scripts, and what comes
back is not what a viewer sees. Go on to Route C if a person is present, or stop and say so.

---

## What Not To Do

Each of these is a real failure mode, not a hypothetical:

- **Do not hunt for a transcript button at a narrow viewport.** It is not hidden, it is absent.
  Resize first.
- **Do not click the same control repeatedly with different element references.** Duplicate
  hidden nodes accept clicks silently. Filter on visibility, click once, verify by reading state.
- **Do not use generic page-text extraction to read a side panel.** It skips them. Query the DOM.
- **Do not read a duration off a screenshot while an ad is playing.** You will get the ad's
  duration and every timestamp downstream will be wrong.
- **Do not keep screenshotting a page that just timed out.** Drop to text, or restart the tab.
- **Do not leave the video playing while you work.** Playback plus ads plus screenshots is what
  freezes the renderer in the first place.
- **Do not read a caption, or take a screenshot, after a fixed sleep.** Wait for the seek to
  finish and for the caption or the frame to actually change.
- **Do not claim you watched a video you sampled.** Say which minutes you covered and how.
