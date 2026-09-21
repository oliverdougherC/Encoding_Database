#!/bin/bash
# Pixel-equivalence check: per-frame MD5 hash of EVERY decoded frame of the
# original FFV1 master vs the lossless H.264 preview. Identical hash lists ==
# frame-by-frame pixel equivalence.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p tools/evidence
fail=0
for src in media/canonical/*.mkv; do
  name=$(basename "$src" .mkv)
  prev="media/previews/${name}-lossless-h264-preview.mp4"
  ffmpeg -y -v error -i "$src"  -f framehash -hash md5 "tools/evidence/${name}-original.hash"
  ffmpeg -y -v error -i "$prev" -f framehash -hash md5 "tools/evidence/${name}-preview.hash"
  a=$(grep -cv '^#' "tools/evidence/${name}-original.hash")
  b=$(grep -cv '^#' "tools/evidence/${name}-preview.hash")
  if cmp -s "tools/evidence/${name}-original.hash" "tools/evidence/${name}-preview.hash"; then
    echo "PASS $name: $a/$b frames, all per-frame MD5s identical"
  else
    echo "FAIL $name: original=$a preview=$b frames"; fail=1
  fi
done
exit $fail
