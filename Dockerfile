# watch-video-like-human - tools only (Route 0: a file you have, Route A: allowed yt-dlp retrieval).
#
# There is no agent in this image, no browser and no screen recorder: the agent runs on the host and
# calls these tools; Route B (browser) and Route C (recording) need the host itself.
# Every version below is fixed on purpose. To move one, change it here and let CI rebuild and re-test.

FROM mwader/static-ffmpeg:7.1.1 AS ffmpeg

FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="watch-video-like-human tools" \
      org.opencontainers.image.description="ffmpeg, yt-dlp, faster-whisper and the skill's scripts for Route 0 and Route A. No agent, no browser, no recorder." \
      org.opencontainers.image.source="https://github.com/HaleCapra/watch-video-like-human" \
      org.opencontainers.image.licenses="MIT"

COPY --from=ffmpeg /ffmpeg /ffprobe /usr/local/bin/

COPY docker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check -r /tmp/requirements.txt

# The scripts, minus the two that only make sense on the host (screen recording, installing tools).
COPY skills/watch-video-like-human/scripts/ /opt/watch-video-like-human/scripts/
COPY tools/route0_smoke.py /opt/watch-video-like-human/tools/route0_smoke.py
COPY docker/entrypoint.sh /usr/local/bin/wvlh
RUN rm /opt/watch-video-like-human/scripts/record_browser_playback.py /opt/watch-video-like-human/scripts/setup_tools.py \
    && chmod 755 /usr/local/bin/wvlh \
    && useradd --create-home --uid 1000 wvlh \
    && mkdir -p /work /cache && chmod 1777 /work /cache

# Speech models are not baked in: they are downloaded on first use into /cache - mount a volume there.
ENV WVLH_SCRIPTS=/opt/watch-video-like-human/scripts \
    HF_HOME=/cache/huggingface \
    XDG_CACHE_HOME=/cache \
    HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1

USER wvlh
WORKDIR /work
ENTRYPOINT ["wvlh"]
CMD ["help"]
