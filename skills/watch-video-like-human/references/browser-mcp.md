# Route B through a browser MCP

Route B needs one thing from the host: a tool that runs JavaScript in the page the video is
playing in. The skill does not ship a browser extension and does not drive a browser from inside
its Docker image. It uses the browser tool the agent already has. This page says how the snippets
of `browser-extraction.md` go into three such tools, unchanged in their logic.

What was run and what was only read is stated at the end. Tool names and parameters below are
those of the versions named there; a tool's own description (your MCP client shows it) wins when
it differs.

## Which tool, at a glance

| | Claude in Chrome | Playwright MCP | Chrome DevTools MCP |
|---|---|---|---|
| Package / where it comes from | the Claude browser extension (and the Claude desktop app's built-in browser) | `@playwright/mcp` (npm) | `chrome-devtools-mcp` (npm) |
| Tool that runs page JavaScript | `javascript_tool` (`action: "javascript_exec"`) | `browser_evaluate` | `evaluate_script` |
| Argument that carries the code | `text` | `function` | `function` |
| What the code must be | statements; the value of the **last expression** is returned | **a function**: `() => { ... }` or `async () => { ... }` | **a function**: `() => { ... }` or `async () => { ... }` |
| A snippet from `browser-extraction.md` | paste as it is | wrap it (below) | wrap it (below) |
| `await` | top-level `await` works | an `async` function is awaited | an `async` function is awaited |
| What comes back | the value, as JSON text | text containing the value as JSON | text containing the value as JSON; must be JSON-serialisable |
| Long replies | cut at about 1,000 characters: use the pieces (below) | not cut at that size in our run; `filename` writes the result to a file instead | not cut at that size in our run; `filePath` writes the result to a file instead |
| Open a page | `navigate` | `browser_navigate` (`url`) | `navigate_page` (`url`) or `new_page` |
| Resize to 1280x900 | `resize_window` | `browser_resize` | `resize_page` |
| Screenshot (Rung 4) | `computer` (`action: "screenshot"`) | `browser_take_screenshot` | `take_screenshot` |
| Whose browser | the person's own Chrome, with their logins | a browser the server starts (fresh profile unless told otherwise) | a Chrome the server starts, or one it attaches to |

The last row matters more than the syntax. A video the person can play in their own browser
(a course site they are signed in to) is reachable from Claude in Chrome at once. A browser
started fresh by an MCP server is signed in to nothing: it sees what an anonymous visitor sees.
Do not move logins into it yourself. If the person wants that browser signed in, they sign in,
in that window. A fresh Chromium may also lack the licensed codecs and play nothing where Chrome
plays fine - for Playwright MCP ask for the installed Chrome (`--browser chrome`).

## The one wrapper

Every snippet in `browser-extraction.md` is an expression that returns a value: an IIFE such as
`(() => {...})()` or `(async () => {...})()`, or a plain expression. Tools that want a function
get the snippet inside this, and nothing else changes:

```js
async () => { return await (
  /* the snippet, exactly as written */
); }
```

Example - the generic caption-track reader (Rung 2), for `browser_evaluate` or `evaluate_script`:

```js
async () => { return await (
(async () => {
  const v = document.querySelector('video');
  if (!v || !v.textTracks.length) return { ok: false, reason: 'no text tracks' };
  const track = [...v.textTracks].find(t => t.kind === 'subtitles' || t.kind === 'captions') || v.textTracks[0];
  track.mode = 'hidden';
  await new Promise(r => setTimeout(r, 800));
  const cues = [...(track.cues || [])];
  return { ok: cues.length > 0, label: track.label, language: track.language, count: cues.length,
           segments: cues.map(c => ({ start: c.startTime, end: c.endTime, text: c.text })) };
})()
); }
```

Three snippets are written as statements that end on an expression (the transcript-panel pager
is one). They run as they are in Claude in Chrome. For the function form, put the statements in
the body and `return` the last expression:

```js
() => {
  const all = [...document.querySelectorAll('track')];
  return all.map(t => ({ kind: t.kind, label: t.label, lang: t.srclang, src: t.src }));
}
```

Before the first real snippet, check that the tool awaits - one call:

```js
async () => { await new Promise(r => setTimeout(r, 50)); return { awaited: true }; }
```

`{ awaited: true }` back: go on. `{}` or nothing back: the tool did not wait for the Promise.
Then use the form from the top of `browser-extraction.md` (statements with top-level `await`) if
the tool takes statements, or run the steps as separate calls with a wait between them.

In Claude in Chrome a snippet's `(async () => {...})()` wrapper is awaited by current versions.
Where it comes back as `{}`, drop the wrapper and write the body at top level - the same
advice, from the same page.

## Long replies: pieces, or a file

`browser-extraction.md` (section 5) keeps long text in the page (`globalThis.__wvOut`) and reads
it in pieces of 900 characters, then checks that the piece lengths add up. That works in all
three tools, because the page keeps its state between calls as long as it is not reloaded.

- **Claude in Chrome:** always use the pieces for anything that can pass about 900 characters.
- **Playwright MCP, Chrome DevTools MCP:** a full caption track came back whole in our run, so
  the pieces are usually not needed. When a reply is large enough to crowd the conversation, let
  the tool write it to a file (`filename` / `filePath`) and hand that file to
  `normalize_transcript.py`. The file is written where the MCP server runs - on the host, in the
  folder that server uses for output - so check where it landed before pointing a script at it.
  If the tool wrapped the value in other text, save only the JSON.
- Either way, a reply that is visibly cut (`[TRUNCATED]`, or JSON that does not parse) is not
  data. Ask again in pieces; never fill the gap from memory.

## Addresses with query strings

Claude in Chrome may replace a URL that carries a query string with a placeholder before the
reply reaches you. The snippets already work around it: they select the track and fetch it in
**one** call, so the address never leaves the page. Keep it that way in the other tools too -
they would hand you the address, but an address with a signature in it is not something to move
around.

## What stays the same everywhere

- The order of work in `browser-extraction.md` and its stop conditions. A different tool is not
  a reason to try what the page refuses.
- Screenshots count as seen only for the frames you opened; captions read from the page are
  captions read (`captions-only`), in whatever tool they were read. Record the tool in the
  manifest (`route --route B --reason "Playwright MCP, anonymous session"`).
- Timeouts: a tool that gives up does not stop the page. The multi-point sampler ends itself
  after 35 seconds and can be stopped with `globalThis.__wvAbort = true` in any of the three.
- The Docker image has no browser, and the MCP server in it (`wvlh mcp`) has no browser tool.
  What the browser produced is saved as a file under the work root by the agent, and the file
  tools take it from there (`normalize_transcript`, `evidence_manifest_add --kind captions`).

## Field names, side by side

What a snippet returns is the same object everywhere; only the envelope differs.

| The snippet returns | Claude in Chrome shows | Playwright MCP shows | Chrome DevTools MCP shows |
|---|---|---|---|
| an object / array | its JSON | a `Result` section with its JSON, then the code that was run | a line of text, then its JSON in a code block |
| a string | the string | the string as JSON (in quotes) | the string as JSON (in quotes) |
| `undefined` | `undefined` or nothing | `undefined` | `undefined` or nothing |
| a thrown error | the error message | an error result with the message | an error result with the message |
| a Promise that is not awaited | `{}` | - (awaited) | - (awaited) |

Take the JSON out of the envelope before saving it. `normalize_transcript.py` reads the objects
the snippets return (`segments`, the pager's pages, the list of pieces); it does not read a
tool's surrounding text.

## What was run, and what was not

- **Run in CI on every pull request** (`tests/browser_mcp.py`, headless Chrome on Linux, a local
  test page with a `<video>`, a WebVTT track and a stand-in caption layer): Playwright MCP 0.0.86
  and Chrome DevTools MCP 1.14.0, each driven over stdio. Through each of them: the await check,
  the Rung 2 generic track reader, the `<track>` listing, the Rung 3 single-point and multi-point
  samplers, and the keep-and-read-in-pieces pair - taken from `browser-extraction.md` as written
  and put in the wrapper above.
- **Run by hand, in real use:** Claude in Chrome, on the sites named in `browser-extraction.md`.
  It is not in CI: it needs a person's own browser.
- **Not run anywhere by us:** these tools against real video sites other than through Claude in
  Chrome; the YouTube- and Bilibili-specific snippets through Playwright MCP or Chrome DevTools
  MCP; `filename` / `filePath` output; a signed-in session in either of them.
