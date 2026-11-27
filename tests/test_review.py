#!/usr/bin/env python3
"""Checks for v5.6: contact sheets, the evidence view page and the review pack.

    python -B tests/test_review.py

Needs Python and ffmpeg, nothing else. A small video is generated, frames are cut from it, and the
three new pieces are run on them the way an agent would run them. The page is checked as a
structure (parsed, not looked at): the parts that must be there, nothing that loads from elsewhere,
and text from the manifest that tries to be markup stays text.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "skills" / "watch-video-like-human" / "scripts"
PASSED = []

EVIL_TITLE = '<img src=x onerror=alert(1)> "Title" & more'
EVIL_CLAIM = "</script><script>alert(2)</script><svg onload=alert(3)> the bars are shown"
EVIL_REASON = "local file <iframe src=https://example.com/x></iframe>"
EVIL_GAP = "</pre><a href=\"https://example.com/steal\">click</a> javascript:alert(4)"
SRT = """1
00:00:01,000 --> 00:00:04,000
First line with <b>tags</b> & an ampersand.

2
00:00:09,000 --> 00:00:12,000
Second line, "quoted", with a url https://example.com/talk in it.

3
00:00:16,000 --> 00:00:19,000
Third line.
"""


def check(name, condition, detail=""):
    if not condition:
        raise AssertionError("%s %s" % (name, detail))
    PASSED.append(name)
    print("PASS", name, flush=True)


def run(script, *args, ok=(0,), cwd=None):
    proc = subprocess.run([sys.executable, "-I", "-B", str(SCRIPTS / script), *[str(a) for a in args]],
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
    out, err = proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")
    assert proc.returncode in ok, "%s %s -> exit %d\n%s\n%s" % (script, args, proc.returncode, out[-1500:], err[-2500:])
    return proc.returncode, out, err


def em(*args, ok=(0,)):
    return run("evidence_manifest.py", *args, ok=ok)


def load(name):
    spec = importlib.util.spec_from_file_location("wvlh_" + name.replace(".", "_"), str(SCRIPTS / name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Page(HTMLParser):
    """What the page is made of: tags, ids, attributes that load or link, scripts, and its text."""

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.tags, self.ids, self.loads, self.handlers, self.scripts, self.words = {}, set(), [], [], [], []
        self.metas, self.seen, self._in_script, self.buttons, self.images = [], [], False, 0, []
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags[tag] = self.tags.get(tag, 0) + 1
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        for key, value in attrs.items():
            if key.startswith("on"):
                self.handlers.append((tag, key))
            if key in ("src", "href", "srcset", "poster", "action", "data", "formaction", "background"):
                self.loads.append((tag, key, value or ""))
        if tag == "meta":
            self.metas.append(attrs)
        if tag == "script":
            self._in_script = True
            self.scripts.append("")
        if tag == "tr" and attrs.get("data-seen"):
            self.seen.append((attrs.get("class"), attrs["data-seen"]))
        if tag == "button" and "data-t" in attrs:
            self.buttons += 1
        if tag == "img":
            self.images.append(attrs.get("src") or "")

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script:
            self.scripts[-1] += data
        else:
            self.words.append(data)

    @property
    def text(self):
        return " ".join(" ".join(self.words).split())


def page_is_sound(text, manifest_module, what):
    page = Page(text)
    for needed in ("verify", "disclosure", "seen-counts", "video", "timeline", "timeline-table", "claims",
                   "issues", "files", "files-table"):
        assert needed in page.ids, "%s: no element with id %s" % (what, needed)
    assert page.tags.get("script") == 1 and page.scripts[0].strip() == manifest_module.VIEW_SCRIPT.strip(), \
        "%s: the only script must be the fixed one" % what
    assert not page.handlers, "%s: event-handler attributes: %s" % (what, page.handlers)
    for banned in ("iframe", "object", "embed", "link", "base", "form", "svg", "a", "audio", "source", "track"):
        assert banned not in page.tags, "%s: a <%s> element" % (what, banned)
    outside = [load for load in page.loads if not (load[2].startswith("data:image/") or
                                                   (":" not in load[2] and not load[2].startswith(("/", "\\"))))]
    assert not outside, "%s: something loads from or links to elsewhere: %s" % (what, [(a, b, c[:60]) for a, b, c in outside])
    csp = [m.get("content", "") for m in page.metas if (m.get("http-equiv") or "").lower() == "content-security-policy"]
    assert csp and "default-src 'none'" in csp[0] and "connect-src" not in csp[0] and "http" not in csp[0], csp
    assert "@import" not in text and "url(" not in text, "%s: the style sheet reaches out" % what
    return page


def check_outputs(argv):
    """--check-page FILE --check-pack ZIP: the structure checks alone, on files made somewhere else (a container)."""
    manifest_mod = load("evidence_manifest.py")
    if "--check-page" in argv:
        path = Path(argv[argv.index("--check-page") + 1])
        page = page_is_sound(path.read_text(encoding="utf-8"), manifest_mod, str(path))
        states = [seen for css, seen in page.seen if css == "row-frame"]
        check("page %s: sound; %d frames (%d opened, %d as tiles, %d not opened), %d pictures"
              % (path.name, len(states), states.count("opened"), states.count("tile"), states.count("not-opened"),
                 len(page.images)), bool(states) and "/work" not in page.text and "/tmp" not in page.text)
    if "--check-pack" in argv:
        path = Path(argv[argv.index("--check-pack") + 1])
        with zipfile.ZipFile(str(path)) as pack:
            names = pack.namelist()
            page_is_sound(pack.read("review/index.html").decode("utf-8"), manifest_mod, "page in " + path.name)
            copy = pack.read("review/evidence_manifest.json").decode("utf-8")
        check("pack %s: %d files under review/, a sound page, no video, no container path in the manifest copy"
              % (path.name, len(names)),
              all(n.startswith("review/") and ".." not in n for n in names) and not any(n.startswith("review/media/") for n in names)
              and '"/work' not in copy and "/tmp/" not in copy, str(names))
    return 0


def main():
    if "--check-page" in sys.argv or "--check-pack" in sys.argv:
        return check_outputs(sys.argv[1:])
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "ffmpeg is needed"
    base = Path(tempfile.mkdtemp(prefix="wvlh-review-test-"))
    work = base / "work folder"                         # a space in the path, on purpose
    work.mkdir()
    try:
        made = subprocess.run([ffmpeg, "-y", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i",
                               "testsrc2=s=640x360:d=24:r=10", "-f", "lavfi", "-i", "sine=frequency=440:duration=24",
                               "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac", "-shortest", str(work / "sample.mp4")],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert made.returncode == 0, made.stderr.decode("utf-8", "replace")[-1500:]
        out = work / "out"
        run("extract_media_assets.py", work / "sample.mp4", "--out-dir", out, "--interval", "3", "--no-audio")
        frames = json.loads((out / "frames.json").read_text(encoding="utf-8"))["frames"]
        assert len(frames) == 8, len(frames)
        (work / "talk.srt").write_text(SRT, encoding="utf-8")
        sheet_mod = load("contact_sheet.py")
        manifest_mod = load("evidence_manifest.py")

        # ------------------------------------------------------------------ contact sheets
        _, printed, _ = run("contact_sheet.py", "--frames", out / "frames.json", "--columns", "3", "--rows", "2")
        said = json.loads(printed)
        sheets = json.loads((out / "sheets.json").read_text(encoding="utf-8"))
        check("sheet: 8 frames at 3 x 2 give two sheets, every frame on exactly one",
              [len(s["frames"]) for s in sheets["sheets"]] == [6, 2] and said["frames_on_sheets"] == 8
              and sorted(f["index"] for s in sheets["sheets"] for f in s["frames"]) == list(range(1, 9)))
        first = sheets["sheets"][0]
        size = sheet_mod.image_size(out / "sheets" / first["file"])
        check("sheet: the picture has the size the record gives, and every cell lies inside it",
              size == (first["width"], first["height"]) and first["columns"] == 3 and first["rows"] == 2
              and all(0 <= f["cell"]["left"] and f["cell"]["left"] + f["cell"]["width"] <= size[0]
                      and f["cell"]["top"] + f["cell"]["height"] + first["label_band"] <= size[1] for f in first["frames"]),
              "%s %s" % (size, first))
        check("sheet: labels carry the frame's index and its real time",
              [f["label"] for f in first["frames"][:3]] == ["#001 00:00.0", "#002 00:03.0", "#003 00:06.0"]
              and first["frames"][1]["time_seconds"] == frames[1]["time_seconds"])

        def bright(sheet, left, top, width, height):
            raw = subprocess.run([ffmpeg, "-nostdin", "-loglevel", "error", "-i", str(out / "sheets" / sheet["file"]), "-vf",
                                  "crop=%d:%d:%d:%d,format=gray" % (width, height, left, top), "-f", "rawvideo", "-"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
            return sum(1 for value in raw if value > 180), len(raw)

        cell = first["frames"][4]["cell"]
        lit, total = bright(first, cell["left"], cell["top"] + cell["height"], cell["width"], first["label_band"])
        second = sheets["sheets"][1]
        empty, _ = bright(second, 2 * second["tile_width"], 0, second["tile_width"], second["height"])
        check("sheet: the label band really has a label drawn in it (no font involved), and an unused cell is black",
              total == cell["width"] * first["label_band"] and 40 < lit < total / 2 and empty == 0,
              "lit %s of %s, empty-cell bright pixels %s" % (lit, total, empty))
        check("sheet: the note says what a tile is worth", "reduced size" in said["note"] and "not at full size" in said["note"])

        run("contact_sheet.py", "--frames", out / "frames.json", "--only", "1,3-5", "--columns", "2", "--out-dir", work / "pick")
        picked = json.loads((work / "pick" / "sheets.json").read_text(encoding="utf-8"))
        check("sheet: --only picks frames, in the order given",
              [f["index"] for f in picked["sheets"][0]["frames"]] == [1, 3, 4, 5] and picked["sheets"][0]["rows"] == 2)
        run("contact_sheet.py", "--frames", out / "frames.json", "--start", "5", "--end", "13", "--out-dir", work / "span")
        span = json.loads((work / "span" / "sheets.json").read_text(encoding="utf-8"))
        check("sheet: --start / --end keep the frames inside the span",
              [f["time_seconds"] for f in span["sheets"][0]["frames"]] == [6.0, 9.0, 12.0])
        for bad in (["--only", "99"], ["--only", "x"], ["--columns", "0"], ["--tile-width", "50"], ["--start", "30"]):
            code, _, err = run("contact_sheet.py", "--frames", out / "frames.json", "--out-dir", work / "bad", *bad, ok=(1, 2))
            assert code != 0 and err.strip(), bad
        check("sheet: wrong arguments are refused with a message, nothing half-made is left behind",
              not (work / "bad" / "sheets.json").exists())
        source = (SCRIPTS / "contact_sheet.py").read_text(encoding="utf-8")
        check("sheet: ffmpeg only - no drawtext, no font file, no imaging package",
              "drawtext" not in source.split('"""', 2)[2].replace("ffmpeg's drawtext wants", "")
              and "import PIL" not in source and "fontfile" not in source and "tile=" in source)

        # ------------------------------------------------------------------ the manifest knows what a sheet is
        m = out / "evidence_manifest.json"
        em("init", "-m", m, "--source", work / "sample.mp4", "--title", EVIL_TITLE)
        em("route", "-m", m, "--route", "0", "--status", "succeeded", "--reason", EVIL_REASON)
        code, _, err = em("add", "-m", m, "--kind", "contact-sheets", "--path", out / "sheets.json", ok=(1,))
        check("manifest: sheets cannot be recorded before the frames they are made of", "Record the frames first" in err)
        em("add", "-m", m, "--kind", "frames", "--path", out / "frames.json", "--command", "extract_media_assets.py --interval 3")
        em("add", "-m", m, "--kind", "transcript", "--path", work / "talk.srt", "--transcript-source", "manual", "--language", "en",
           "--command", "written by hand")
        _, printed, _ = em("add", "-m", m, "--kind", "contact-sheets", "--path", out / "sheets.json", "--command", "contact_sheet.py")
        sheet_artifact = json.loads(printed)["added"][0]
        record = json.loads(m.read_text(encoding="utf-8"))
        recorded = next(a for a in record["artifacts"] if a["id"] == sheet_artifact)["details"]["sheets"]
        check("manifest: each sheet is recorded with its hash and the ids of the frames on it",
              [s["id"] for s in recorded] == [sheet_artifact + ".s001", sheet_artifact + ".s002"]
              and [f["id"] for f in recorded[0]["frames"]] == ["E1.f%03d" % n for n in range(1, 7)]
              and all(len(s["sha256"]) == 64 for s in recorded))
        s1, s2 = recorded[0]["id"], recorded[1]["id"]

        def rate(inspected, *more):
            em("rate", "-m", m, "--visual", "sampled", "--frames-inspected", inspected, "--audio", "captions-only",
               "--alignment", "timestamp-aligned", "--gap", EVIL_GAP, *more)

        rate("E1.f001," + s1)
        em("verify", "-m", m)
        status = manifest_mod.seen_status(json.loads(m.read_text(encoding="utf-8")))
        check("seen: a frame opened is 'opened', a frame on an opened sheet is 'tile', the rest are 'not-opened'",
              status["E1.f001"] == "opened" and [status["E1.f%03d" % n] for n in range(2, 7)] == ["tile"] * 5
              and status["E1.f007"] == status["E1.f008"] == "not-opened" and status[s1] == "opened" and status[s2] == "not-opened")
        _, block, _ = em("render", "-m", m, "--output", out / "answer.md")
        check("disclosure: says how many frames were opened and how many were only seen as tiles",
              "1 of 8 actually looked at" in block and "plus 5 seen only as tiles of a contact sheet (reduced size)" in block
              and "1 of them inspected, 5 more only as contact-sheet tiles" in block, block)
        em("lint", "--file", out / "answer.md")
        check("disclosure: the block still passes lint", True)
        em("claim", "-m", m, "--text", EVIL_CLAIM, "--start", "3", "--end", "4", "--frames", "E1.f002", "--segments", "1",
           "--assessment", "confirmed")
        em("verify", "-m", m)
        check("verify: a claim may rest on a frame that was seen as a tile of an opened sheet", True)
        em("claim", "-m", m, "--text", "Something at the end", "--start", "21", "--end", "22", "--frames", "E1.f008",
           "--assessment", "picture-only")
        code, printed, _ = em("verify", "-m", m, ok=(1,))
        check("verify: a claim on a frame that is only on a sheet nobody opened is refused",
              "E1.f008, which is not listed in --frames-inspected" in printed)
        em("claim-update", "-m", m, "--id", "C2", "--status", "withdrawn", "--note", "test")
        em("verify", "-m", m)
        rate("E1.f001," + s1, "--on-screen-text", "on-screen text", "--on-screen-frames", s1)
        code, printed, _ = em("verify", "-m", m, ok=(1,))
        check("verify: on-screen text cannot be read off a contact sheet", "a contact sheet: a tile is a frame at reduced size" in printed)
        rate(s2)          # claim C1 now rests on a frame of a sheet that is no longer opened: see the block anyway
        _, block, _ = em("render", "-m", m, "--allow-unverified")
        check("disclosure: with only a sheet opened, no frame is said to have been opened at full size",
              "none of 8 opened at full size, plus 2 seen only as tiles" in block, block)
        rate("E1.f001," + s1)
        em("issue", "-m", m, "--start", "20", "--summary", "What <the> last frames show was not checked")

        untouched = out / "plain.json"
        em("init", "-m", untouched, "--source", work / "sample.mp4")
        em("route", "-m", untouched, "--route", "0", "--status", "succeeded")
        em("add", "-m", untouched, "--kind", "frames", "--path", out / "frames.json", "--command", "x")
        em("rate", "-m", untouched, "--visual", "sampled", "--frames-inspected", "E1.f001,E1.f002", "--audio", "none",
           "--alignment", "none")
        _, block, _ = em("render", "-m", untouched)
        _, verified, _ = em("verify", "-m", untouched)
        check("unchanged: without sheets the disclosure and verify say nothing about sheets or tiles",
              "tile" not in block and "contact" not in block and "contact_sheets" not in verified
              and "2 of 8 actually looked at (00:00, 00:03)" in block, block)

        # ------------------------------------------------------------------ the view page
        _, printed, _ = em("view", "-m", m)
        said = json.loads(printed)
        text = (out / "evidence_view.html").read_text(encoding="utf-8")
        page = page_is_sound(text, manifest_mod, "view")
        check("view: one file with the parts that must be there, one fixed script, a policy that allows no network",
              said["single_file"] is True and said["verifies"] is True)
        frame_rows = [seen for css, seen in page.seen if css == "row-frame"]
        check("view: every frame is marked opened / tile / not opened, as verify counts them",
              frame_rows.count("opened") == 1 and frame_rows.count("tile") == 5 and frame_rows.count("not-opened") == 2
              and said["frames"] == {"opened": 1, "tile": 5, "not-opened": 2}, str(frame_rows))
        check("view: the pictures are inside the file",
              len(page.images) == 10 and all(src.startswith("data:image/jpeg;base64,") for src in page.images), str(len(page.images)))
        check("view: text that tries to be markup stays text",
              page.tags.get("img") == 10 and "svg" not in page.tags and "iframe" not in page.tags and "a" not in page.tags
              and EVIL_TITLE in page.text and "alert(2)" in page.text and "<iframe src=https://example.com/x>" in page.text
              and 'href="https://example.com/steal"' in page.text and "javascript:alert(4)" in page.text)
        check("view: the transcript lines, the claim, the open question and the disclosure are on the page",
              "First line with tags & an ampersand." in page.text and "Third line." in page.text
              and "the bars are shown" in page.text and "last frames show was not checked" in page.text
              and "seen only as tiles of a contact sheet" in page.text and "text supplied by hand" in page.text)
        check("view: a player with the video beside the page, and times that jump to it",
              page.tags.get("video") == 1 and ("video", "src", "../sample.mp4") in page.loads and page.buttons >= 12)
        home, here = str(Path.home()), str(work)
        check("view: no folder of this machine is written into the page",
              home not in text and here not in text and here.replace("\\", "/") not in text
              and str(base) not in text and "sample.mp4" in text)

        em("view", "-m", m, "--no-video", "--output", out / "quiet.html")
        quiet = page_is_sound((out / "quiet.html").read_text(encoding="utf-8"), manifest_mod, "view --no-video")
        check("view --no-video: no player, times are plain text", "video" not in quiet.tags and quiet.buttons == 0 and "no-video" in quiet.ids)
        em("view", "-m", m, "--link-pictures", "--output", out / "linked.html")
        linked = page_is_sound((out / "linked.html").read_text(encoding="utf-8"), manifest_mod, "view --link-pictures")
        check("view --link-pictures: relative links to files that exist",
              all(not src.startswith("data:") and (out / src.replace("%20", " ")).is_file() for src in linked.images)
              and (out / "linked.html").stat().st_size < (out / "evidence_view.html").stat().st_size / 5)
        em("view", "-m", m, "--within", work / "pick", "--output", work / "pick" / "fenced.html")
        fenced = page_is_sound((work / "pick" / "fenced.html").read_text(encoding="utf-8"), manifest_mod, "view --within")
        check("view --within: a recorded file outside that folder is not read into the page",
              not fenced.images and "video" not in fenced.tags and "the picture is not here" in fenced.text
              and "First line with tags" not in fenced.text)

        tampered = out / "sheets" / recorded[1]["relpath"].split("/")[-1]
        keep = tampered.read_bytes()
        tampered.write_bytes(keep + b"x")
        code, printed, _ = em("verify", "-m", m, ok=(1,))
        em("view", "-m", m, "--output", out / "broken.html")
        broken = Page((out / "broken.html").read_text(encoding="utf-8"))
        check("view: a manifest that does not verify is shown as such, with the reason",
              "contact sheet file changed" in printed and "The manifest does not verify." in broken.text
              and "contact sheet file changed since it was recorded" in broken.text)
        tampered.write_bytes(keep)
        em("verify", "-m", m)

        # ------------------------------------------------------------------ the review pack
        _, printed, _ = em("pack", "-m", m, "--output", work / "review.zip")
        said = json.loads(printed)
        with zipfile.ZipFile(work / "review.zip") as pack:
            names = pack.namelist()
            texts = {n: pack.read(n).decode("utf-8") for n in names if n.endswith((".html", ".json", ".txt", ".md", ".srt"))}
        check("pack: everything sits under review/ with relative, forward-slash names",
              all(n.startswith("review/") and "\\" not in n and ".." not in n and ":" not in n for n in names), str(names))
        check("pack: the page, the manifest copy, the disclosure, the pictures that were used, the transcript - and no video",
              {"review/index.html", "review/evidence_manifest.json", "review/disclosure.md", "review/README.txt",
               "review/files/E1.f001.jpg", "review/files/E1.f002.jpg", "review/files/E2.srt",
               "review/files/%s.jpg" % s1} == set(names) and said["video_included"] is False, str(names))
        packed_page = page_is_sound(texts["review/index.html"], manifest_mod, "pack page")
        check("pack: the page shows the pictures in the pack and says the others are not here",
              sorted(packed_page.images) == ["files/E1.f001.jpg", "files/E1.f002.jpg", "files/%s.jpg" % s1]
              and all("review/" + src in names for src in packed_page.images) and "video" not in packed_page.tags
              and "The video is not in this pack" in packed_page.text and "the picture is not here" in packed_page.text)
        copy = json.loads(texts["review/evidence_manifest.json"])
        check("pack: the manifest copy has relative paths, says what was left out, and is marked as a copy",
              all(a["path"] == a.get("in_pack") or "/" not in a["path"].replace("(elsewhere)/", "") for a in copy["artifacts"])
              and copy["source"]["input"] == "sample.mp4" and len(copy["review_pack"]["left_out"]) >= 6
              and "not on this copy" in copy["review_pack"]["note"])
        leaks = [n for n, t in texts.items() if home in t or here in t or here.replace("\\", "/") in t or str(base) in t
                 or str(base).replace("\\", "\\\\") in t]
        check("pack: no text in it holds a folder of this machine", not leaks, str(leaks))

        em("pack", "-m", m, "--output", work / "full.zip", "--include-video", "--all-frames")
        with zipfile.ZipFile(work / "full.zip") as pack:
            names = pack.namelist()
            full_page = page_is_sound(pack.read("review/index.html").decode("utf-8"), manifest_mod, "pack page with video")
        check("pack --include-video --all-frames: the video and every picture, and the page plays the packed video",
              "review/media/sample.mp4" in names and sum(1 for n in names if n.startswith("review/files/E1.f")) == 8
              and ("video", "src", "media/sample.mp4") in full_page.loads)

        (work / "mail.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nWrite to someone" + "@" + "realmail.test.io today.\n",
                                        encoding="utf-8")      # written in pieces so the repository scan does not trip on it
        _, printed, _ = em("add", "-m", m, "--kind", "captions", "--path", work / "mail.srt", "--language", "en", "--command", "test")
        mail_id = json.loads(printed)["added"][0]
        code, printed, err = em("pack", "-m", m, "--output", work / "mail.zip", ok=(1,))
        found = json.loads(printed)
        check("pack: an email address in a transcript stops the pack; the report names file, line and kind, not the text",
              not (work / "mail.zip").exists() and found["ok"] is False
              and {"file": "files/%s.srt" % mail_id, "line": 3, "kind": "email"} in found["findings"]
              and "someone@" not in printed and "Nothing was packed" in err, printed)
        _, printed, _ = em("pack", "-m", m, "--output", work / "mail.zip", "--accept-findings")
        check("pack --accept-findings: packed, and the accepted findings are listed",
              (work / "mail.zip").is_file() and len(json.loads(printed)["findings_accepted"]) >= 2)
        em("claim", "-m", m, "--text", "The slide shows /" + "home/alice/notes/plan.txt", "--start", "1", "--segments", "1",
           "--transcript", "E2", "--assessment", "transcript-only")
        code, printed, _ = em("pack", "-m", m, "--output", work / "path.zip", "--accept-findings", ok=(0,))
        code, printed, _ = em("pack", "-m", m, "--output", work / "path2.zip", ok=(1,))
        check("pack: a home path written into a claim is found too",
              any(f["kind"] == "home-path" for f in json.loads(printed)["findings"]) and not (work / "path2.zip").exists())
    finally:
        shutil.rmtree(str(base), ignore_errors=True)        # the folder this run created, nothing else
    print("\n%d checks passed" % len(PASSED))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
