# Optional Backends (all off by default)

**The default path is unchanged: you look at the extracted frames yourself.** Two optional
add-ons exist for users who explicitly configure them. Neither runs, uploads, or costs anything
unless the user supplies the backend, and everything they return is **second-hand**: an external
engine or model saw or heard it, you did not.

Even when one is configured, **the picture stays the primary evidence and OCR only assists**:
look at the frame first, use external text for dense passages you still need transcribed, and
take every character you use back to the image.

**External OCR or vision model per keyframe** - `scripts/analyze_keyframes.py`:

```bash
python scripts/analyze_keyframes.py --frames WORK/frames.json            # no backend: explains and exits 0
python scripts/analyze_keyframes.py --frames WORK/frames.json --backend tesseract --only 3,7,12
```

It runs only when a backend is chosen with `--backend` or `WVLH_KEYFRAME_BACKEND`: `tesseract`
(a Tesseract the user installed; frames stay local), `vlm` (an OpenAI-compatible endpoint from
`WVLH_VLM_API_KEY`, `WVLH_VLM_BASE_URL`, `WVLH_VLM_MODEL`; **frames are uploaded**), or `command`
(`WVLH_KEYFRAME_COMMAND="tool {image}"`). With nothing configured, or a backend whose
prerequisite is missing, it prints how to enable one and exits 0 - carry on by looking at the
frames. Never install an OCR engine or obtain a key on your own initiative, and tell the user
before frames leave the machine. Results go to `keyframe_analysis.json`.

**A-native: a native video model as an optional sub-route of Route A.** When Route A's download
is refused for a **public** YouTube video, a model with native video input (for example Gemini)
can be given the URL and will sample the picture, at roughly one frame per second by default,
and process the audio. Consider it only after Routes 0, A and B, only for public videos, only
with an API key the user provides themselves, and never to get around a login, paywall, region
lock or DRM. This skill ships no calling code for it. If the user runs it, save the model's
reply to a file and disclose the model, its sampling settings, and that this is not
frame-by-frame viewing. Budget on the order of 300 tokens per second of video at default
settings (about a third of that at low resolution); check the provider's current documentation.

**How second-hand evidence is rated - it never lifts a rating:**

- An external description is not a frame you inspected. `Visual: sampled` still requires frames
  you opened yourself; with none, Visual is `second-hand`.
- External OCR output is `external OCR text (second-hand)`, never `burned-in caption text`
  (which means you read the frame yourself).
- A native model's account of the audio is `Audio: second-hand`, never `transcribed` or `heard`.
- Register the files with `evidence_manifest.py add --kind keyframe-analysis` or
  `--kind native-model-report`; `verify` rejects a first-hand rating that rests on them, and
  `render` adds a `Second-hand evidence` line.
- In the answer, attribute it every time: "an external OCR pass read...", "the external model
  described...". Never "I saw", "the video shows" or "the speaker says" on second-hand evidence
  alone.

## Optional cloud speech recognition (off by default)

The normal order for speech is: captions that already exist, then a local Whisper. Both need no
key and upload nothing. `scripts/transcribe_cloud.py` is for the case where neither is available
and **the user has decided** to send the audio to a transcription service they have an account
with (Groq, OpenAI, or any OpenAI-compatible `/audio/transcriptions` endpoint).

```bash
python scripts/transcribe_cloud.py WORK/audio.wav --out WORK/transcript                       # off: explains, exits 0
python scripts/transcribe_cloud.py WORK/audio.wav --out WORK/transcript --backend groq         # prints the upload plan only
python scripts/transcribe_cloud.py WORK/audio.wav --out WORK/transcript --backend groq --confirm-upload
```

- It runs only when a backend is named (`--backend groq|openai|custom` or `WVLH_ASR_BACKEND`),
  the key is in the environment (`WVLH_ASR_API_KEY`, or `GROQ_API_KEY` / `OPENAI_API_KEY` for
  that same provider), **and** `--confirm-upload` is given. A key alone does nothing. `custom`
  also needs `WVLH_ASR_BASE_URL` and `WVLH_ASR_MODEL`.
- **The key is never typed into a command, never printed and never written to a file by this
  skill.** Do not ask the user to paste it into the chat. If it is not in the environment, say
  which variable is missing and stop.
- Without `--confirm-upload` the script prints how many bytes would go to which host and uploads
  nothing. Show that to the user and wait for a yes.
- Audio is sent as mono 16 kHz MP3. Above 24,000,000 bytes it is cut into chunks; each chunk's
  timestamps are shifted back onto the source clock.
- **A failed chunk is reported, not hidden.** Its time range goes into `failed_chunks`, the
  transcript is marked `complete: false`, and the exit code is 2. Say which ranges have no
  transcript. Do not retry them on another provider, and do not switch provider because one
  failed - report and ask.
- Register the result with `--transcript-source cloud-asr`. The audio rating is still
  `transcribed` (real audio was recognised), and the rendered disclosure states that a
  third-party service did the recognition and that the audio was uploaded. Failed ranges are
  added to Known gaps automatically.
- Uses the standard library only. Its temporary audio lives in a folder the run creates and
  removes; nothing else is deleted.

## No silent switching

When something optional or external fails - a cloud transcription, an external vision model, a
native video model, a download - **report the failure with its real reason and ask**. Never
quietly substitute another engine, provider or model, and never present one engine's output as
another's. A conclusion that came from a third-party model (for example Gemini given the whole
video) is always labelled with that model's name and rated `second-hand`.
