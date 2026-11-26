# watch-video-like-human

An agent skill for watching videos honestly. If a person can play it, the agent should be able
to work with it too - and then say exactly how much of it was actually seen, heard, or only read.

让 AI 助手"像人一样看视频"的技能：人能播放的视频，助手也应该能处理；处理完必须如实说明到底看了多少、听了多少、还是只读了字幕。

[English](#english) · [中文](#中文)

---

## English

### What it does

- **Four routes to the material**, tried in order, each failure reported:

  | Route | When | What you get |
  |---|---|---|
  | **Route 0** - a file you already have | the user supplies a local video | complete media: picture and real audio |
  | **Route A** - download | `yt-dlp` supports the source and retrieval is allowed | complete media |
  | **Route B** - browser extraction | the page plays but no file can be obtained | sampled frames and caption text, no real audio |
  | **Route C** - screen plus loopback recording | nothing else works and normal OS capture is permitted | a real-time recording |

- **Evidence disclosure on every answer.** The reply starts with a `What I Actually Did` block:
  the route used and the routes that failed first, then separate ratings for Visual (none /
  sampled / continuous), Audio (none / captions-only / transcribed / heard) and Alignment, with
  coverage and known gaps. Reading captions is never described as watching or hearing.
- **Keyframes with real timestamps**: scene changes plus a maximum gap, near-duplicate removal
  that keeps small on-screen changes, detail levels from transcript-only to uncapped, focus on a
  time range, extra frames where the presenter says "look here".
- **Looking closer**: full-width frames, then a crop of one region at source resolution - never
  enlarged, because enlarging adds pixels, not detail.
- **Complete notes done properly**: the whole transcript is read (a read log proves every page
  was served), a three-column working draft keeps transcript evidence, picture evidence and
  open conflicts apart, and anything unconfirmed keeps its tag.
- **An evidence manifest**: every product file with its hash and the command that made it, which
  frames were actually opened, claim records, and a list of problems that could not be solved -
  recorded, never guessed. The disclosure block is generated from it.

### Requirements

- Python 3.9 or later. The scripts use the standard library only.
- `ffmpeg` and `ffprobe` on PATH.
- Optional, and only to unlock more: `yt-dlp` (Route A), a local Whisper (transcribing audio), a
  browser tool in your agent (Route B), a loopback audio device (audio in Route C).
- Windows, macOS and Linux.

### First-time setup

One command shows what this machine is missing. It installs nothing:

```
python skills/watch-video-like-human/scripts/setup_tools.py
```

Read the plan, then let it run the automatic steps:

```
python skills/watch-video-like-human/scripts/setup_tools.py --yes                  # ffmpeg, a current yt-dlp
python skills/watch-video-like-human/scripts/setup_tools.py --tier whisper --yes   # a local speech recogniser (large)
python skills/watch-video-like-human/scripts/setup_tools.py --tier recording       # guide for screen recording
```

- Nothing is installed without `--yes`. In an agent, the agent asks you first, in one sentence.
- It never uses `sudo`, never asks for a password and never pipes a download into a shell. Steps
  that need administrator rights (for example `apt-get` on Linux) are printed for you to run.
- Python packages go into `~/.watch-video-like-human`, not into your system Python. An existing,
  outdated yt-dlp is left alone; the scripts use the fresh copy first.
- It runs on Python 3.6 and later, so it is also what to run when the other scripts say Python is
  too old. With `uv` installed it fetches Python 3.12 by itself.
- When the system Python is too old, or has no `venv` / `pip` (a default Ubuntu), and there is no
  `uv`, the plan includes one download: a fixed `uv` release from its official GitHub release page
  (or, only when GitHub cannot be reached, the same version's official wheel on PyPI, from which
  just the `uv` program is taken) into `~/.watch-video-like-human/bin`. The plan shows both
  addresses, the version, sizes and SHA-256 values, and the run says which one was used;
  the file is checked against that hash and against HTTPS certificates, no installer script is
  run and PATH is not changed. If the download or a check fails, nothing is installed and the
  manual steps are printed instead.
- Windows uses `winget` for ffmpeg. macOS uses Homebrew when it is there; on an Intel Mac where
  Homebrew will not install, the plan is `uv` plus a signed static ffmpeg build that you download
  yourself. Linux prints the package-manager command.
- Screen recording (Route C) needs a loopback audio driver and, on macOS, a system permission.
  Those are yours to do; the `recording` tier is a step-by-step guide and runs nothing.

Checked so far: the plan on Windows for real, and on simulated macOS and Linux machines. A real
`--yes` run has not been made on any system yet.

### Install

Replace `<owner>/<repo>` with wherever this repository is published.

**Most agents - one command**

```
npx skills add <owner>/<repo>
```

The `skills` installer copies the folder to the right place for the agent it detects (add `-g`
for a user-level install, `-a <agent>` to name one). It covers Claude Code, Codex, Cursor,
Gemini CLI, GitHub Copilot, CodeBuddy, Trae, Qoder, Qwen Code, OpenCode, Windsurf and others.
It does **not** know WorkBuddy - see the manual steps below. None of these installs was tested
end to end for this skill.

| Agent | Project folder | User folder |
|---|---|---|
| Claude Code | `.claude/skills/` | `~/.claude/skills/` |
| Codex | `.agents/skills/` | `~/.agents/skills/` (`~/.codex/skills/` is also read on current builds) |
| Cursor | `.agents/skills/` | `~/.cursor/skills/` |
| Gemini CLI | `.agents/skills/` | `~/.gemini/skills/` |
| GitHub Copilot | `.agents/skills/` | `~/.copilot/skills/` |
| CodeBuddy | `.codebuddy/skills/` | `~/.codebuddy/skills/` |
| WorkBuddy | `.workbuddy/skills/` | `~/.workbuddy/skills/` (community-sourced, unverified) |
| Trae | `.trae/skills/` | `~/.trae/skills/` |
| Qoder | `.qoder/skills/` | `~/.qoder/skills/` |
| Qwen Code | `.qwen/skills/` | `~/.qwen/skills/` |
| OpenCode | `.agents/skills/` | `~/.config/opencode/skills/` |

Folders are those the `skills` installer writes to; a vendor's own documentation may list more.
In every case the result is the same: a folder named `watch-video-like-human` with `SKILL.md`
directly inside it.

**Claude Code - as a plugin**

```
/plugin marketplace add <owner>/<repo>
/plugin install watch-video-like-human@watch-video-like-human
```

**Claude Code - as a plain skill**

Copy `skills/watch-video-like-human/` to `~/.claude/skills/watch-video-like-human/` (all your
projects) or to `.claude/skills/watch-video-like-human/` inside one project.

**Claude apps that accept skill uploads**

Run `python tools/build_zip.py` and upload `dist/watch-video-like-human-5.4.0.zip` in the app's
skill settings. A hosted sandbox has no screen, no audio device and limited network, so expect
Route 0 on uploaded files only.

**Codex**

Copy `skills/watch-video-like-human/` to `~/.codex/skills/watch-video-like-human/`
(`%USERPROFILE%\.codex\skills\` on Windows). The repository also carries a
`.codex-plugin/plugin.json`; that manifest is modelled on a working plugin but is **unverified**
here.

**CodeBuddy / WorkBuddy (Tencent)**

- CodeBuddy: `npx skills add <owner>/<repo> -a codebuddy`, or copy the folder to
  `.codebuddy/skills/watch-video-like-human/` in your workspace (from the vendor's
  documentation), or use "import skill" in its settings.
- WorkBuddy - manual, **community-sourced and unverified**: copy the folder to
  `~/.workbuddy/skills/watch-video-like-human/` (Windows:
  `%USERPROFILE%\.workbuddy\skills\watch-video-like-human\`), then restart WorkBuddy. No official
  Tencent page for this path was found, and one tutorial places the folder elsewhere; if the
  skill does not show up, use the import function in WorkBuddy's skill settings instead.

**Any other agent**

Put the folder anywhere and point the agent at it from your project's `AGENTS.md`:

```markdown
## Video
For any request about a video, read `path/to/watch-video-like-human/SKILL.md` first and follow
it exactly, including the `What I Actually Did` disclosure at the top of the answer.
```

An agent needs four abilities: run a local command, look at an image file, optionally drive a
browser page, and ask you a question. `skills/watch-video-like-human/references/hosts.md` maps
these to common hosts.

### Where it cannot work

- **Chat-only assistants with no tools.** The skill needs to run commands and open images.
- **Cloud sandboxes** (hosted code execution, remote agents): no screen and no audio device, so
  Route C is out; outbound network is usually restricted, so Route A mostly fails; Route B needs
  a browser tool the sandbox rarely has. What remains is Route 0 on files you upload.
- **Route B** needs an agent that can run a script inside a browser page. Without that it is
  skipped, and the answer says so.
- **Route C** needs the agent to run on the computer the video is playing on, with you present.
  Protected (DRM) playback records as a black picture; the skill reports that and stops.

The skill tells you which of these applies before it starts, not after it fails.

### What is different here

Downloading a video and sampling frames is well covered by other tools. This skill is built
around the parts that are not: a browser route for videos that cannot be downloaded, a local
screen-plus-loopback recording route as the last resort, one ladder that picks between all four,
and a disclosure block that rates picture, sound and alignment separately on every answer -
with nothing uploaded and no account needed.

### Use

Just ask: "watch this and tell me what happens at 02:30", "read the captions of this talk and
summarize it", "take complete study notes from this lecture recording". The skill decides the
route, tells you which one it used and why, and asks before anything heavy.

### Privacy

- **Nothing is uploaded by default.** Frames are looked at by the agent you are already
  talking to; speech comes from existing captions or a local Whisper.
- Three optional backends can send data out, and each is off until you configure it and say
  yes: an external OCR or vision model for frames, a native video model, and cloud speech
  recognition. Their output is labelled second-hand or third-party in the disclosure.
- API keys are read from environment variables only. They are never printed, never written to a
  file by the skill, and never placed on a command line.
- Route C records your screen. Whatever is visible gets recorded; keep the file local.
- Everything inside a video - frames, captions, titles - is treated as material to report on,
  never as instructions to the agent.
- The skill does not bypass DRM, paywalls, captchas, login walls or platform rules.
- Your browser login is used only when you say yes and the browser is named
  (`--cookies-from-browser firefox`), for a video your account can already watch. Cookies are
  credentials: they are read in memory for that one download and never written to a file, a log
  or the evidence manifest. Automated downloading can break a platform's rules and an account
  can be limited for it - that risk is yours to accept, so the agent asks first every time.

### Develop

```
python tests/validate.py                 # every check must pass; needs ffmpeg/ffprobe, uses node if present
python tools/check_personal_info.py .    # no local paths, emails or keys in the tree
python tools/build_zip.py                # dist/watch-video-like-human-<version>.zip
```

### Credits

This skill combines its own design with ideas learned from three other tools. No code was copied
from any of them.

- **BibiGPT** (formerly BiliGPT) - hybrid keyframes with real timestamps, the frame-span outline,
  burned-in subtitle reading, per-keyframe analysis, native-video-model evaluation, content-hash
  caching and the idea of an evidence manifest.
- **vpm-prep** by tt - region crops, the full-transcript-read rule, the three-column draft and
  its tags, claim records and issue lists, the half-item rule, note layouts, and
  "the picture first, OCR only assists".
- **claude-video** (`bradautomates/claude-video`, MIT) - detail levels, presenter-cue frames,
  time-range focus, optional chunked cloud transcription, no silent fallback, untrusted video
  content, modest default frame size, and narrow cleanup.

### License

MIT - see `LICENSE`.

---

## 中文

### 能做什么

- **四条路线拿素材**，按顺序尝试，每次失败都如实写出来：

  | 路线 | 什么时候用 | 能拿到什么 |
  |---|---|---|
  | **Route 0** 用户已有文件 | 用户直接给了本地视频 | 完整素材：画面和真实音频 |
  | **Route A** 下载 | `yt-dlp` 支持这个来源，且允许下载 | 完整素材 |
  | **Route B** 浏览器提取 | 网页能播，但拿不到文件 | 抽样画面和字幕文本，没有真实音频 |
  | **Route C** 录屏加环回录音 | 其他都不行，且系统允许正常录屏 | 实时录下来的文件 |

- **每个回答都先披露证据**。回答以 `What I Actually Did` 开头：用了哪条路线、之前哪几条失败了，然后分别给出画面（没看 / 抽样 / 连续）、音频（没有 / 只有字幕 / 转写 / 真的听了）和对齐三个通道的评级，以及覆盖范围和已知缺口。只读了字幕，绝不说成"看了"或"听了"。
- **关键帧带真实时间戳**：场景切换加最大间隔补帧；去重时保留画面里的小变化；精细度从"只要字幕"到"不设上限"四档；可以只聚焦一段时间；讲解者说"看这里"的时刻可以补帧。
- **看不清怎么办**：先全宽重抽，再从源分辨率裁出一个区域。只缩不放，因为放大只会多出像素，不会多出细节。
- **认真做完整笔记**：转录必须全部读完（有阅读日志记录每一页都取过）；三栏中间稿把转录依据、画面依据、冲突与待证分开；没确认的内容一直带着标签。
- **证据清单**：每个产物文件的哈希和生成命令、实际打开过哪些帧、每条结论的证据记录、解决不了的问题清单（只留档，不猜答案）。披露块就是从这份清单生成的。

### 运行条件

- Python 3.9 或更高。脚本只用标准库。
- `ffmpeg` 和 `ffprobe` 在 PATH 里。
- 可选项，只为解锁更多能力：`yt-dlp`（Route A）、本地 Whisper（转写音频）、助手自带的浏览器工具（Route B）、环回音频设备（Route C 的声音）。
- Windows、macOS、Linux 都能用。

### 第一次使用：一句话装齐

先看这台电脑缺什么。这条命令什么都不会装：

```
python skills/watch-video-like-human/scripts/setup_tools.py
```

看完计划，同意了再让它执行：

```
python skills/watch-video-like-human/scripts/setup_tools.py --yes                  # ffmpeg、最新的 yt-dlp
python skills/watch-video-like-human/scripts/setup_tools.py --tier whisper --yes   # 本地语音识别（体积大，单独确认）
python skills/watch-video-like-human/scripts/setup_tools.py --tier recording       # 录屏的分步引导
```

- 不带 `--yes` 什么都不装。在助手里使用时，助手会先用一句话问你。
- 不会用 sudo，不会要密码，也不会把下载的东西直接交给 shell 执行。需要管理员权限的步骤（比如 Linux 上的 `apt-get`）只打印出来，由你自己运行。
- Python 包装到 `~/.watch-video-like-human`，不动系统 Python。已有的旧版 yt-dlp 原样保留，脚本优先用新装的那份。
- 它自己能在 Python 3.6 以上运行，所以别的脚本提示"Python 太旧"时也是运行它。装了 `uv` 的话它会自己取 Python 3.12。
- 系统 Python 太旧，或者没有 `venv` / `pip`（Ubuntu 默认就是这样），又没有 `uv` 时，计划里会多一步下载：从 uv 官方 GitHub 发布页取一个固定版本（只有 GitHub 连不上时，才改用 PyPI 上同一版本的官方 wheel，并且只取出里面的 `uv` 程序），放到 `~/.watch-video-like-human/bin`。计划会列出两个网址、版本、大小和 SHA-256，执行时会打印实际用了哪一个；下载后核对哈希，全程校验证书，不运行安装脚本，不改 PATH。下载或校验失败时什么都不装，改为打印手动步骤。
- Windows 用 `winget` 装 ffmpeg。macOS 有 Homebrew 就用 Homebrew；Intel Mac 上 Homebrew 装不了时，方案是 `uv` 加一个你自己下载的已签名静态 ffmpeg。Linux 打印包管理器命令。
- 录屏（Route C）需要环回声音驱动，macOS 还要系统权限。这些只能你自己做，`recording` 这一档只是分步引导，不执行任何东西。

目前验证到的程度：Windows 上真实跑过出计划，macOS 和 Linux 用模拟环境跑过。任何系统上都还没有真实执行过 `--yes`。

### 安装

把 `<owner>/<repo>` 换成这个仓库实际发布的位置。

**大多数助手：一条命令**

```
npx skills add <owner>/<repo>
```

`skills` 安装器会识别你用的助手，把文件夹放到对的位置（加 `-g` 装到用户级，`-a <助手名>` 指定某一个）。它支持 Claude Code、Codex、Cursor、Gemini CLI、GitHub Copilot、CodeBuddy、Trae、Qoder、Qwen Code、OpenCode、Windsurf 等，**不支持 WorkBuddy**，WorkBuddy 见下面的手动步骤。这些安装方式都没有针对本技能做过完整实测。

各家的目录见上面英文部分的表格。不管哪家，结果都一样：一个叫 `watch-video-like-human` 的文件夹，里面直接放着 `SKILL.md`。

**Claude Code：作为插件**

```
/plugin marketplace add <owner>/<repo>
/plugin install watch-video-like-human@watch-video-like-human
```

**Claude Code：作为普通技能**

把 `skills/watch-video-like-human/` 复制到 `~/.claude/skills/watch-video-like-human/`（所有项目可用），或某个项目里的 `.claude/skills/watch-video-like-human/`。

**支持上传技能的 Claude 应用**

运行 `python tools/build_zip.py`，在应用的技能设置里上传 `dist/watch-video-like-human-5.4.0.zip`。云端沙箱没有屏幕、没有音频设备、联网受限，一般只能对上传的文件走 Route 0。

**Codex**

把 `skills/watch-video-like-human/` 复制到 `~/.codex/skills/watch-video-like-human/`（Windows 是 `%USERPROFILE%\.codex\skills\`）。仓库里还带了 `.codex-plugin/plugin.json`，是照着一个能用的插件写的，但在这里**未验证**。

**腾讯 CodeBuddy / WorkBuddy**

- CodeBuddy：`npx skills add <owner>/<repo> -a codebuddy`；或把文件夹复制到工作区的 `.codebuddy/skills/watch-video-like-human/`（来自官方文档）；或在设置里用"导入 Skill"。
- WorkBuddy（手动安装，**来源是社区教程，未验证**）：把文件夹复制到 `~/.workbuddy/skills/watch-video-like-human/`（Windows 是 `%USERPROFILE%\.workbuddy\skills\watch-video-like-human\`），然后重启 WorkBuddy。没有找到腾讯官方写这个路径的页面，有一篇教程说的位置不一样；如果技能没出现，请改用 WorkBuddy 技能设置里的导入功能。

**其他任何助手**

文件夹放哪都行，然后在你项目的 `AGENTS.md` 里指过去：

```markdown
## Video
凡是和视频有关的请求，先读 `path/to/watch-video-like-human/SKILL.md` 并严格照做，
包括回答开头的 `What I Actually Did` 披露。
```

助手需要四种能力：运行本地命令、查看图片文件、（可选）操作浏览器页面、向你提问。各家助手对应什么工具，见 `skills/watch-video-like-human/references/hosts.md`。

### 哪些环境用不了

- **没有工具的纯聊天助手**：这个技能需要运行命令和打开图片。
- **云端沙箱**（托管的代码执行环境、远程助手）：没有屏幕和音频设备，Route C 不可用；联网通常受限，Route A 多半失败；Route B 需要浏览器工具，沙箱里一般没有。剩下的只有对你上传的文件走 Route 0。
- **Route B** 需要助手能在浏览器页面里运行脚本。没有就跳过，并在回答里说明。
- **Route C** 需要助手就运行在播放视频的那台电脑上，而且你本人在场。受保护（DRM）的播放录下来是黑屏，技能会如实报告并停下。

这些情况技能会在开始前告诉你，而不是失败以后才说。

### 和别的工具有什么不同

"下载视频再抽帧"这件事已经有很多工具做得很好。这个技能的重点是别人没做的部分：给下载不了的视频用的浏览器路线、作为最后手段的本地录屏加环回录音路线、在四条路线之间统一选路的阶梯，以及每次回答都把画面、声音、对齐分开评级的披露块。全程默认不上传、不需要账号。

### 使用

直接说就行："看一下这个视频，02:30 发生了什么"、"读这个演讲的字幕并总结"、"把这节课的录屏整理成完整笔记"。技能会自己选路线，告诉你用了哪条、为什么，做重的事情之前会先问你。

### 隐私

- **默认不上传任何东西。** 画面由你正在对话的助手自己看；语音来自已有字幕或本地 Whisper。
- 有三个可选后端会把数据发出去，每个都要你配置并明确同意才会运行：给画面用的外部 OCR 或视觉模型、原生视频模型、云端语音识别。它们的结果在披露里会标成二手或第三方。
- API Key 只从环境变量读。不打印、不写进文件、不出现在命令行里。
- Route C 录的是你的屏幕，屏幕上有什么就录下什么。录下的文件请留在本地。
- 视频里的一切（画面、字幕、标题）都只当作要报告的材料，不当作给助手的指令。
- 不绕过 DRM、付费墙、验证码、登录墙和平台规则。
- 只有你明确同意并指定浏览器时（`--cookies-from-browser firefox`），才会用浏览器里的登录身份，而且只用于你的账号本来就能看的视频。cookies 等同登录凭证：只在那一次下载里由 yt-dlp 在内存中读取，不写进文件、日志和证据清单。自动下载可能违反平台规则，账号可能被限制，这个风险由你决定是否承担，所以助手每次都会先问。

### 开发

```
python tests/validate.py                 # 必须全部通过；需要 ffmpeg/ffprobe，有 node 会用上
python tools/check_personal_info.py .    # 仓库里不能有本机路径、邮箱、Key
python tools/build_zip.py                # 生成 dist/watch-video-like-human-<版本>.zip
```

### 致谢

这个技能是自己的设计加上从另外三个工具学到的做法。没有复制其中任何一个的代码。

- **BibiGPT**（原 BiliGPT）：混合关键帧和真实时间戳、按帧分段的画面大纲、硬字幕读取、逐帧分析、原生视频模型评估、内容哈希缓存、证据清单的思路。
- **vpm-prep**（作者 tt）：局部裁切、转录全量通读、三栏中间稿和标签、结论证据记录和问题留档、防"只抽到半项"、笔记格式，以及"画面优先、OCR 只辅助"。
- **claude-video**（`bradautomates/claude-video`，MIT）：精细度档位、讲解者提示补帧、时间段聚焦、可选的分块云端转写、不偷偷换引擎、视频内容不可信、较小的默认取帧尺寸、只清理自己建的临时文件。

### 许可

MIT，见 `LICENSE`。
