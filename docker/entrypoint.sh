#!/bin/sh
# wvlh NAME [ARGS...] runs one of the skill's scripts; a few tools can be called directly.
set -e
scripts="${WVLH_SCRIPTS:-/opt/watch-video-like-human/scripts}"
case "${1:-help}" in
  help|-h|--help)
    echo "watch-video-like-human tools (Route 0 and Route A only; no agent, no browser, no recorder)"
    echo "usage: wvlh SCRIPT [ARGS...]     for example: wvlh extract_media_assets /work/video.mp4 --out-dir /work/out"
    echo "       wvlh smoke VIDEO --work DIR   Route 0 from end to end, as a self-check"
    echo "       wvlh mcp [--root DIR]         the same tools as an MCP server on stdin/stdout (work root: /work)"
    echo "       wvlh ffmpeg|ffprobe|yt-dlp ARGS..."
    echo "scripts:"
    for f in "$scripts"/*.py; do echo "  $(basename "$f" .py)"; done
    ;;
  smoke)
    shift
    exec python -I -B /opt/watch-video-like-human/tools/route0_smoke.py "$@"
    ;;
  mcp)
    shift
    exec python -B /opt/watch-video-like-human/server/mcp_server.py --root /work "$@"
    ;;
  ffmpeg|ffprobe|yt-dlp)
    exec "$@"
    ;;
  *)
    name="${1%.py}"
    shift
    if [ ! -f "$scripts/$name.py" ]; then
      echo "wvlh: no such script: $name (try: wvlh help)" >&2
      exit 2
    fi
    exec python -I -B "$scripts/$name.py" "$@"
    ;;
esac
