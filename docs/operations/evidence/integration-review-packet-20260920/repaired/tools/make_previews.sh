#!/bin/bash
# Build browser-compatible LOSSLESS reference previews (H.264 qp=0, 1s GOP,
# faststart) from the original FFV1 canonical masters. Originals untouched.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p media/previews tools/evidence
for src in media/canonical/*.mkv; do
  name=$(basename "$src" .mkv)
  out="media/previews/${name}-lossless-h264-preview.mp4"
  echo "== $name"
  /usr/bin/time -p ffmpeg -y -hide_banner -loglevel warning \
    -i "$src" -map 0:v:0 -an \
    -c:v libx264 -preset veryfast -qp 0 -pix_fmt yuv420p \
    -g 24 -keyint_min 24 -sc_threshold 0 \
    -movflags +faststart \
    "$out" 2>&1 | sed -n 's/^/   /p'
  ls -l "$out" | awk '{print "   size:", $5}'
done
echo "== sha256"
shasum -a 256 media/previews/*.mp4 | tee tools/evidence/preview-sha256.txt
