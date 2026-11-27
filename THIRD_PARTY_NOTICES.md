# Third-party notices

The code in this repository is under the MIT License (see `LICENSE`).

The skill itself calls tools you install yourself (ffmpeg, yt-dlp, a speech recogniser); they keep
their own licenses and are not part of this repository.

The Docker image (`Dockerfile`, published as `ghcr.io/halecapra/watch-video-like-human`) bundles
the following. Their licenses apply to those parts of the image, not to the MIT-licensed code.

| Component | How it gets into the image | License |
|---|---|---|
| FFmpeg, ffprobe | static build from [wader/static-ffmpeg](https://github.com/wader/static-ffmpeg) 7.1.1 | **GPL-3.0-or-later** for this build (configured with `--enable-gpl --enable-version3`, includes x264 and x265). Source: <https://ffmpeg.org/download.html>, build recipe: wader/static-ffmpeg (MIT). See <https://ffmpeg.org/legal.html>. No `nonfree` parts are enabled. |
| Python 3.12 and Debian bookworm (base image `python:3.12-slim-bookworm`) | base image | PSF License (Python); Debian packages under their own licenses, listed in `/usr/share/doc/*/copyright` inside the image |
| yt-dlp | pip, `docker/requirements.txt` | Unlicense |
| faster-whisper | pip | MIT |
| CTranslate2 (pulled in by faster-whisper) | pip | MIT |
| PyAV (pulled in by faster-whisper) | pip | BSD-3-Clause; its wheels bundle FFmpeg libraries under LGPL |
| onnxruntime (pulled in by faster-whisper) | pip | MIT |
| huggingface_hub, tokenizers (pulled in by faster-whisper) | pip | Apache-2.0 |
| MCP Python SDK (`mcp`) | pip | MIT |

Every package the image installs, with its version, is printed by the `docker` workflow
("What is inside"). Speech recognition models are not in the image; they are downloaded on first use
under their own licenses (the Whisper models published by OpenAI are MIT).

If you redistribute the image, you redistribute GPL software (FFmpeg): keep this notice and make the
corresponding source available, as the GPL requires (the links above point to it).
