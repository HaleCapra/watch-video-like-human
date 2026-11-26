# Browser Recording Notes

> Read this only for **Route C** - after the user-file, allowed-download, and browser-extraction
> routes have been tried and found unavailable or insufficient.
> Recording is the most expensive and most fragile way to read a video. See
> `references/browser-extraction.md` for everything that comes before it.
>
> Record only what the user is authorized to view and record. Never record to defeat a
> protection that exists to prevent recording.

## Audio Capture

Browser control often exposes screen state but not system audio. To capture speech from browser playback, use one of these authorized paths:

- Existing captions or transcript: fastest and most reliable.
- Extracted audio from a local video file or allowed recording.
- Windows ffmpeg `dshow` audio device, such as Stereo Mix, virtual-audio-capturer, or a virtual loopback device.
- macOS AVFoundation audio device backed by an allowed loopback tool such as BlackHole or Loopback.
- Linux PulseAudio or PipeWire-compatible monitor source.
- Browser/tab audio capture through an extension or environment-specific browser API, when available.

Always close unrelated audio sources before recording with system loopback. If the selected audio device is wrong, the recording may be silent or may include unrelated system sounds.

Before a long recording, run `--check-audio` and then `--test-audio` while the video is playing.
The signal test reports `signal_present`, `too_quiet`, or `digital_silence`; only the last state
means no audio is reaching the device. A quiet signal is real audio but may need more source gain
or later amplification before transcription.

## Before Any Recording: What Route C Actually Captures

The recorder captures the **screen** (Windows `gdigrab desktop`, macOS AVFoundation screen,
Linux X11 root or one window) and the **system output**. It has no idea where the video is.

- **The player must be full screen and stay in front** from the first second to the last.
  In a real test the user kept working during a 150-second recording: ffmpeg exited 0, the file
  was complete and the audio perfect, and every extracted frame showed other applications. In a
  second attempt the player was in front but another window covered the right 40% of it.
- **A person must be present.** Windows refuses to let a background process take the
  foreground, browser automation often cannot enter full screen, and nobody can use the
  computer while it records. Unattended or remote use cannot meet this; then Route C is
  unavailable for the picture, and that is the honest report.
- **One player only.** Closing and reopening a player, or a second tab, can leave two media
  elements playing the same track about half a minute apart. Monitoring one element shows
  "all fine". List every `video` and `audio` element before and after (snippet in
  `browser-extraction.md`, section 1); if more than one played, the audio is unusable.
- **`video.play()` from a script needs one real click first.** Chrome rejects it with
  `NotAllowedError` until the user has interacted with the page.
- **A recording's clock is not the video's clock.** The recording starts first; in the test the
  video began 7.0 s later. Measure the offset (`ffmpeg -i capture.mp4 -af silencedetect -f null -`
  shows where sound begins) and pass `--recording-offset` to `align_transcript_frames.py`.
- **The agent's own app must stay out of the way.** In a real test nobody touched the computer:
  the desktop agent app kept a small floating window over 30% of the player, and when the agent
  finished its turn the app's main window came to the front and covered the video for the
  remaining five minutes. So, from the start of the recording to its end: **do not end your
  turn, do not post a message, do not call a tool that opens a window or a permission dialog** -
  cover the whole recording with one blocking wait. Before starting, ask the user to minimise
  the agent app, or put the player on another screen and record only that area
  (`--offset-x/--offset-y/--video-size`).
- **System dialogs go on top of everything.** A firewall prompt, an update notice or a permission
  dialog appears above the player and cannot be moved behind it by a script. Do Not Disturb does
  not stop these. Look at the screen before starting; if one appears during the recording, the
  frames from that moment on show the dialog - say so, or record again.
- **Silence notifications.** Minimising the agent app is not enough: its notification toasts
  (and every other program's) still appear over the player and are recorded. Turn on Do Not
  Disturb / Focus assist (Windows), Focus (macOS) or the desktop's equivalent for the length of
  the recording, and turn it off again afterwards.
- **When you record a region, measure it last.** A browser driven by an agent shows a "started
  debugging this browser" bar at the top. It disappears on its own some time later, the page
  moves up, and a region measured earlier is then cut at the top (measured: 77 px lost; 68 px on
  two later runs - it happens every time). Close
  the bar (its x) before measuring, measure the player's rectangle immediately before starting,
  or record the whole screen and crop afterwards.
- **No one to click full screen? A pop-up window can stand in.** `requestFullscreen` from a
  script is never granted to a browser extension, but this worked end to end in a field test:
  1. one real click in the page through the browser tool (that is the user activation);
  2. `window.open(location.href, 'wvlh', 'popup,width=1280,height=760')` - the same video in a
     small window of its own, controllable from the opening page because it is same-origin;
  3. the player's own "web full screen" / "theatre in window" control inside that pop-up, so the
     video fills the pop-up and nothing else is in it;
  4. read the pop-up's position and size (`screenX`, `screenY`, `innerWidth`, `innerHeight`, times
     `devicePixelRatio`) and record just that rectangle with `--offset-x`, `--offset-y`,
     `--video-size`.
  The check frames still have to show the video, and the pop-up must stay on top: this replaces
  the click, not the rule that nothing may cover the player.
- **Full screen is confirmed, not assumed.** A page script cannot enter full screen and the
  browser tool's click on the button is ignored. Ask the user to double-click the player, then
  poll `document.fullscreenElement` in the page and start recording only once it is set:

  ```js
  ({ fullscreen: !!document.fullscreenElement, visible: document.visibilityState,
     players: document.querySelectorAll('video, audio').length })
  ```
- **Watch the page while it records.** The same three values, read every few seconds, tell you
  early what the recording will show: `visible` turning `hidden` means another window took the
  screen - from that moment the picture is not the video, whatever `fullscreen` still says.
  In the test it flipped at second 25; the recording ran 315 seconds more for nothing.
- **Private things get recorded too.** A screen recording contains whatever was visible. Keep
  the file local, and tell the user if the frames show anything other than the video.

### Preflight - before spending real time

```bash
python scripts/record_browser_playback.py --preflight                  # JSON; exit 2 when blocked
python scripts/record_browser_playback.py --test-audio                 # with the video playing
```

`--preflight` records nothing. It reports the platform, the screen session (on Linux: display,
Wayland, detected size), the loopback devices and the one that would be used, `blockers` (no
display, a Wayland root capture, a missing macOS screen index) and `warnings` (no loopback
device, a non-monitor source, how VB-CABLE must be routed). On Windows it reports the screen's
real size and scaling. On macOS it finds the screen and loopback devices by name, and grabs one
discarded frame with a time limit: without the Screen Recording permission ffmpeg does not fail,
it **waits forever** - that shows up here as a blocker instead of a hang. It also prints the
five things only a person can make true, and the three it cannot check at all: whether the
player will be in front, whether the tab is muted, and whether playback is protected.
`ready: true` means nothing known stands in the way - not that the recording will be good.

### An early look while it records

```bash
python scripts/record_browser_playback.py --audio-device auto --duration 780 --output capture.mp4 --early-check 15,60
```

At each of those seconds a separate screenshot of the same area is saved as
`capture.early-1.jpg`, `capture.early-2.jpg` and announced. Run the recording as a background
command, open the picture, and stop the recording if it does not show the video - that costs
seconds instead of the video's whole length. Looking at a file is safe; ending the turn is not.

### Stopping a recording early

- **Ctrl+C** (or Ctrl+Break on Windows): ffmpeg finishes the file, the usual check runs, and the exit code
  is **130 whatever the check finds** - read `ok` in the report for that (3 is only for a recording that
  ended by itself). Pressing it again changes nothing: only the recording command hears it, ffmpeg does not,
  and the command answers "Already stopping". If the check then fails, a last line says not to use the file.
- **macOS, Linux: SIGTERM or SIGHUP** to the recording command (`kill PID`) or to its whole process group:
  ffmpeg is asked to stop and normally finishes the file within a second (if it has not after 20 seconds
  it is killed, and the message gives the seconds that passed), and the command ends with 143 (129),
  without the check. It also works when the command was started with an old Python that handed over: the
  process id stays the same. With `nohup`, SIGHUP stays ignored. Before the recording has begun (a screen
  probe, a level test) the running probe is ended too.
- While it records, ffmpeg's own keys do not work on macOS and Linux; use Ctrl+C.
- **Windows: ffmpeg ends whenever the recording command ends**, however that happens - `Stop-Process`,
  `taskkill /F`, a host's hard stop, closing the console window, a crash: the system ends ffmpeg with it
  (a job object). A file ended that way usually does not play. Only if the start printed "ffmpeg could
  not be tied to this process" does the old limit apply: then end the whole tree,
  `taskkill /T /F /PID <id>`, and check that no `ffmpeg` is left.
- **`kill -9 PID` (SIGKILL to the recording command alone) has the same limit** on macOS and Linux: ffmpeg
  goes on until its `--duration` is over. `kill -9 -- -PGID` (the whole group) does end ffmpeg.
- **Started in the background by a shell script (`command &`), SIGINT is ignored** by the recording command.
  Neither it nor ffmpeg reacts to SIGINT then: the recording goes on. Stop such a job with SIGTERM.
- Always pass `--duration`: it is the last safety net in every one of these cases.

### Finding the offset

```bash
python scripts/record_browser_playback.py --detect-offset capture.mp4
```

It reports where sound first begins in the recording as `sound_onset` (an opening silence that
starts within half a second of the file's start counts as "silent from the start": on real
recordings the detector places it at about 0.05 s, not at 0). That is where *sound*
begins, **not the offset**: a video that opens with a second or two of silence makes it later
than where the *video* begins (1.8 s later on one real video; equal on another), and a click or page sound before playback
makes it **earlier** (1.3 s earlier on a third). It is a place to start looking, in both directions. Calibrate with
one known sentence: `offset = its time in the recording's transcript - its time in the video`
(from captions or the page). Pass that to `align_transcript_frames.py --recording-offset`, and
give the video's real length when rating: `evidence_manifest.py rate ... --source-duration 5:22`
- the disclosure then states the offset, and a recording that covers only part of the video is
called partial. A file with no audio track returns `null`.

A recogniser can also invent a short sentence over the silence after the video ends ("Thank
you."). Drop anything that starts after the video's end: `transcribe_local.py --max-end SECONDS`
(in recording time: video length + offset).

### Post-recording self-check

`record_browser_playback.py` runs it automatically and exits 3 when it fails; run it by hand
with `--post-check capture.mp4` (add `--allow-silent` for a picture-only file).

1. **Black picture?** Eight frames are sampled; if all are black the picture is unusable (DRM,
   protected playback, Wayland / XWayland root capture, display off). "Black" is judged on the
   90th-percentile brightness, not on the brightest pixel: a mouse pointer, a clock or a small
   dialog on a black capture is still black (a pointer alone used to pass as a picture). A very bright, uniform
   picture adds a `hint`: that is what an application window looks like, not a video.
2. **Silent track?** `digital_silence` with an audio device given means nothing reached the
   loopback device.
The report is also written beside the recording as `capture.postcheck.json`. Register it, and
say whether you looked:

```bash
python scripts/evidence_manifest.py add -m $M --kind recording-check --path capture.postcheck.json --confirmed-shows-video
```

With Route C in use, `verify` refuses a `sampled` visual rating when no check is recorded, when
the picture was black, or when `--confirmed-shows-video` is absent; and refuses `transcribed`
audio when the recording was silent. Pass the flag only after opening the check frames.

3. **Right picture?** Open `capture.check-1.jpg` to `capture.check-4.jpg` (taken at 10%, 35%,
   65% and 90% of the recording; `check_frame_times` gives the seconds). Only you can tell the
   video from another window. Do this before extraction, not after transcription. If only some
   of them show the video, only that stretch is evidence: record the route as
   `--status partial` and say which stretch.

## Windows: VB-CABLE Setup and Measured Behaviour

VB-CABLE (vb-audio.com/Cable) is the preferred Windows loopback device. It is not in winget;
download the driver pack from the vendor site and run the installer as administrator.

- **The installer changes the system default output to `CABLE Input`.** The speakers go silent
  and the user thinks sound is broken. Right after installing, go to Settings > System > Sound
  and set the speakers back as the default output.
- **Route only the browser into the cable:** Settings > System > Sound > Volume mixer > the
  browser's row > Output device = `CABLE Input (VB-Audio Virtual Cable)`. Record from
  `CABLE Output (VB-Audio Virtual Cable)`. While routed this way the user does not hear the
  video through the speakers; set the browser's output back to Default when finished.
- **The browser appears in Volume mixer only while it is really producing sound.** If the tab is
  muted (Chrome: right-click the tab > Unmute site), the browser opens no audio session and is
  simply **missing** from Volume mixer, so there is nothing to route. Page scripts cannot detect
  this: `video.muted` stays `false` and the player volume looks normal.

Measured on a real machine (Windows 11, Chinese locale, Chrome playing YouTube, 2026-11-24):

| Condition | mean dB | peak dB | `--test-audio` status |
|---|---:|---:|---|
| Browser not routed into the cable | -91.0 | -90.3 | `digital_silence` |
| Browser routed to CABLE Input, `--audio-device auto` | -19.0 | -4.1 | `signal_present` |
| System master volume 80 / 0 / 80 / 0, 8 s each | -16.9 / -17.1 / -17.8 / -16.2 | about -1 | `signal_present` |

The system master volume slider does **not** affect a VB-CABLE recording: 80 and 0 read within
1 dB of each other, the differences being the speech itself. Not measured: the `CABLE Input`
device's own volume slider and the browser's per-app slider in Volume mixer; both sit before
the split and can be expected to change the recorded level. When re-testing levels, watch that
the video is still the same one and still playing - an autoplay hand-over to the next video
produces a silent gap that looks like a routing fault.

On a non-UTF-8 console (for example Chinese Windows, cp936 / GBK) the scripts decode ffmpeg
output as UTF-8 and print JSON as ASCII with `\uXXXX` escapes, so device names with non-ASCII
characters, such as a Chinese-named Stereo Mix, are listed, auto-selected, and passed back to
ffmpeg intact.

### Routing sound into the cable: two ways

1. **Route the browser alone** (Settings > System > Sound > Volume mixer > the browser's output
   = `CABLE Input`). Other sounds stay out of the recording and the speakers keep working. This
   is a person's job: an agent driving the Settings window has mis-clicked there and has had the
   window masked by its own tooling.
2. **Switch the default output for the length of the recording.** Before recording, note the
   current default output device (its id, not just its name), make `CABLE Input` the default,
   record, then set the noted device back and check volume and mute are as before. An agent can
   do this with a script and it has proved more reliable than the mixer. The cost: every system
   sound goes into the recording and the user hears nothing meanwhile - tell them first.

Either way, **outside a recording the speakers must be the default output**.

## Windows ffmpeg Flow

1. List devices:

```powershell
python scripts/record_browser_playback.py --list-devices
```

2. Record video-only desktop capture:

```powershell
python scripts/record_browser_playback.py --duration 60 --output capture.mp4 --allow-silent
```

3. Record with a known audio device:

```powershell
python scripts/record_browser_playback.py --duration 60 --output capture.mp4 --audio-device "Stereo Mix (Realtek(R) Audio)"
```

Device names vary by machine. If no loopback device exists, install or enable an authorized virtual audio device, or ask the user for the video/audio file or transcript.

## macOS ffmpeg Flow

Measured on macOS 15.7 (Intel), ffmpeg 9.1, BlackHole 2ch 0.7.1. Four things have to be true
before a recording has both picture and sound; `--preflight` checks the first three.

**1. Screen Recording permission - for the right app.** System Settings > Privacy & Security >
Screen & System Audio Recording (系统设置 > 隐私与安全性 > 录屏与系统录音). The switch that counts is the
app that *runs the command*: Terminal or iTerm in a terminal; inside a desktop agent app, the row
of its bundled command-line helper, which has the app's name in lower case (in the Claude desktop
app: **claude**, not **Claude**). Without it ffmpeg does not fail - it waits forever. The
recorder therefore opens the screen for a moment with a 12-second limit first, and on a timeout
prints which app chain needs the switch (exit 4). The permission applied without restarting the
app when tested; if macOS offers "Quit & Reopen", Later is fine.

**2. The window-picker dialog (macOS 15+).** The first capture after granting permission, and
again every few weeks, macOS shows: *"ffmpeg" is requesting to bypass the system private window
picker and directly access your screen and audio* (“ffmpeg”正在请求绕过系统无痕浏览窗口选择器，直接访问屏幕和
音频) with buttons Open System Settings / Allow. Capture does **not** wait for it, so the dialog
is recorded in the middle of the picture and the black-frame check still passes. Run
`--preflight` (its screen-open test triggers the dialog) and have the user click Allow before
the real recording.

**3. A loopback device and a Multi-Output Device.** macOS cannot record what it plays. Install
BlackHole 2ch (signed installer from existential.audio/blackhole, or `brew install blackhole-2ch`;
Homebrew no longer installs on Intel Macs) and log out or restart if it does not appear. Then:

1. **First** unmute the speakers and set a comfortable volume - the volume keys and the menu-bar
   slider are disabled while a Multi-Output Device is selected. A muted speaker stays muted: the
   loopback records normally and the user hears nothing.
2. Open **Audio MIDI Setup** (音频 MIDI 设置), press **+** at the bottom left, choose **Create
   Multi-Output Device** (创建多输出设备).
3. Tick both the speakers and **BlackHole 2ch**; keep the speakers as the primary device and
   turn on Drift Correction for BlackHole.
4. Right-click the new device > **Use This Device For Sound Output** (将此设备用于声音输出).
5. After the recording, select the speakers again. The Multi-Output Device can stay for next time.

`--preflight` reports the current output and warns when it is plain speakers (the loopback would
read `digital_silence`) or muted.

**4. Devices by name, not by number.** AVFoundation indexes are not stable: an iPhone used as a
Continuity Camera coming into or out of range, or a newly installed virtual device, renumbers
the list within minutes (measured: `Capture screen 0` moved from 2 to 1 between preflight and
recording). `--screen-device` defaults to `auto` (the first `Capture screen`), and both device
options take `auto`, a name or part of one (`"BlackHole"`), or an index; they are resolved
against the list as it is at that moment and the choice is printed.

```bash
python scripts/record_browser_playback.py --preflight --audio-device auto
python scripts/record_browser_playback.py --audio-device auto --test-audio          # while something is playing
python scripts/record_browser_playback.py --audio-device auto --duration 780 --output capture.mp4
python scripts/record_browser_playback.py --duration 60 --output capture.mp4 --allow-silent   # picture only
```

Retina screens capture at 3360 px or wider (46 MB in three minutes, with dropped frames); the
recording is scaled down to 1920 px wide by default (`--scale 0` keeps the native size,
`--scale 1280` goes smaller; never enlarged). Built-in microphone capture records room audio, not
clean browser audio - the recorder warns when the chosen audio device is not a loopback device.

ffmpeg 9 accepts `-thread_queue_size` only as an output option; the recorder asks the installed
ffmpeg once and leaves the option out when it would be rejected (all platforms).

## Linux ffmpeg Flow

The helper uses X11 screen capture and an optional PulseAudio/PipeWire-compatible audio source:

```bash
python scripts/record_browser_playback.py --platform linux --list-devices
python scripts/record_browser_playback.py --platform linux --check-audio
python scripts/record_browser_playback.py --platform linux --video-size 1920x1080 --audio-device auto --duration 60 --output capture.mp4
```

`--video-size` may be omitted when `xdpyinfo` or `xrandr` is installed. If `pactl` is missing,
install `pulseaudio-utils` (Debian/Ubuntu) or your distribution's `pipewire-pulse` package.

**Audio: use a `.monitor` source, never `default`.** The default *source* on PulseAudio and
PipeWire is the input device - the microphone. `--audio-device default` records the room and
still passes `--test-audio` as `signal_present` (measured: -26.4 dB of microphone while the
real loopback read -41.1 dB). `--audio-device auto` picks the monitor of the **default sink**
first, which matters on machines with HDMI or Bluetooth sinks; the script warns on any Linux
device name that does not end in `.monitor`.

**On PulseAudio the sink's volume and mute reach the monitor** - the opposite of VB-CABLE on
Windows. Measured on PulseAudio 17:

| Sink state | mean dB | peak dB | `--test-audio` status |
|---|---:|---:|---|
| volume 100% | -37.3 | -34.1 | `signal_present` |
| volume 20% | -78.8 | -73.4 | `too_quiet` |
| muted | -91.0 | -91.0 | `digital_silence` |

So on Linux keep the sink unmuted at 100% while recording. PipeWire is expected to behave
differently by default (sink volume not applied to the monitor port); that was not measured.

**Wayland.** x11grab reads the X root window. In a Wayland session, including rootless XWayland
(GNOME, KDE, Sway, WSLg), the root window is empty, so the recording is completely black while
ffmpeg reports success (measured on WSLg: every frame at luma 16, audio normal). The script now
refuses to start in a Wayland session and the post-recording check fails a black file. Options:

- Record with the desktop's own tool and continue as Route 0: GNOME's built-in recorder
  (Ctrl+Shift+Alt+R), KDE Spectacle, `wf-recorder` or `wl-screenrec` on wlroots compositors
  (system sound through the sink's `.monitor`). These were researched, not tested here.
- `--window-id 0x...` (from `xwininfo`) grabs one X11 client window; measured working under
  XWayland on WSLg. It cannot see a Wayland-native window, which is what current Chrome and
  Firefox may use by default.
- `--force-x11` when a real X server owns the display (Xorg, Xvfb): measured working on Xvfb
  with picture and audio.

With no `DISPLAY` at all the script stops and says so instead of guessing `:0.0`.

## Automatic Platform Selection

Omit `--platform` to use the current operating system automatically. Windows can record the desktop without more setup. macOS finds the screen by name (`--screen-device auto` is the default); Linux detects the screen size from `xdpyinfo` or `xrandr`, and needs `--video-size` only when neither is installed.

## Practical Viewing Tips

- Prefer full-screen playback when page chrome or controls obscure content.
- Wait for ads, cookie banners, and overlays to clear before recording.
- If subtitles exist, turn them on for visual backup even when audio is recorded.
- For long videos, capture in chapters or 10-15 minute chunks to keep processing manageable.
- Document whether the result is full coverage or sampled coverage.

## Common Failure Modes

- Recording is black: DRM or protected playback may block capture; on Linux, a Wayland session.
  The post-recording check exits 3.
- Recording shows the wrong thing: another window was on top, or the player was partly covered.
  Measured on macOS: the user typed a question into the agent's window during the recording;
  exit 0, self-check `ok: true`, sound present, every frame showed the chat. Only the check
  frames reveal it.
- macOS, ffmpeg hangs with no output: Screen Recording permission is missing for the app that
  runs the command (see the macOS section). The recorder's screen-open test exits 4 instead.
- macOS, sound is recorded but nothing is heard: the speakers were muted before the Multi-Output
  Device was selected. Switch back to the speakers, unmute, switch again.
- Linux, `--window-id` fails: the id belongs to a window that no longer exists (ids change when
  the player window is re-created). Look it up again with `xwininfo`.
  Nothing detects this automatically - look at the check frames.
- Audio is doubled or garbled: two media elements were playing. Discard the audio.
- Linux audio is the room, not the video: a non-monitor source such as `default` was recorded.
- Audio is silent: wrong audio device, muted tab/system, or no loopback support.
- Browser missing from the Windows Volume mixer while a video plays: the tab is muted, so no
  audio session exists. Unmute the tab, then route the browser.
- No sound from the speakers right after installing VB-CABLE: the installer made `CABLE Input`
  the default output. Set the speakers back as default.
- Controls obscure frames: mouse moved over video, player controls stayed visible, or full-screen was not used.
- Timeline drift: playback stalled or skipped; process shorter chunks and align by visible timestamps or captions.
- macOS permission error: allow Screen Recording for the terminal or agent app, then restart that app before retrying.
- Windows error 5: the current process cannot access the interactive desktop; retry from the
  user's normal desktop session or use an authorized recorder that the session permits.
- Linux input error: confirm the X11 `DISPLAY`, requested video size, and PulseAudio/PipeWire source name.
