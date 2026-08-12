# syntax=docker/dockerfile:1

# Keep the JavaScript and media runtimes pinned independently. The media image is
# multi-architecture and is the production contract for the authoritative v7
# analyzer: its FFmpeg build includes both libvmaf and XPSNR.
FROM node:20-bookworm@sha256:8f693eaa7e0a8e71560c9a82b55fd54c2ae920a2ba5d2cde28bac7d1c01c9ba5 AS node-runtime

# The upstream media image enables libvmaf, but its release library predates the
# Speed-chroma extractor required by the frozen v1.0.16 3D/no-harm model. Build
# a checksum-pinned VMAF commit containing that extractor and replace only the
# ABI-compatible libvmaf shared library in the runtime.
FROM ubuntu:24.04@sha256:561618e2c15bf2397621dd04f96926663a3b5616c189cf7e38db7e82f5c538ea AS vmaf-builder
ARG VMAF_VERSION=3.2.0
ARG VMAF_SOURCE_SHA256=a28f93f3b4fa65601be324587072e32a6a704a304ba7b1aec9b70b3f709bc1dc
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential ca-certificates curl meson nasm ninja-build pkg-config python3 \
    && curl --fail --location --retry 3 \
      "https://codeload.github.com/Netflix/vmaf/tar.gz/refs/tags/v${VMAF_VERSION}" \
      --output /tmp/vmaf.tar.gz \
    && echo "${VMAF_SOURCE_SHA256}  /tmp/vmaf.tar.gz" | sha256sum -c - \
    && mkdir /tmp/vmaf \
    && tar -xzf /tmp/vmaf.tar.gz --strip-components=1 -C /tmp/vmaf \
    && meson setup /tmp/vmaf/libvmaf/build /tmp/vmaf/libvmaf \
      --buildtype=release --prefix=/usr/local --libdir=lib \
      -Denable_tests=false -Denable_docs=false -Denable_float=true -Dbuilt_in_models=true \
    && ninja -C /tmp/vmaf/libvmaf/build \
    && DESTDIR=/vmaf-install meson install -C /tmp/vmaf/libvmaf/build

# --- Builder ---
FROM node-runtime AS builder
WORKDIR /app

# Install deps
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

# Copy source
COPY tsconfig.json ./
COPY prisma ./prisma
COPY src ./src
COPY resources ./resources
COPY config ./config

# Generate Prisma client
RUN npx prisma generate

# Build TypeScript
RUN npm run build

# Prune dev dependencies; keep only production deps and generated client
RUN npm prune --omit=dev --no-audit --no-fund

# --- Runtime ---
FROM linuxserver/ffmpeg:7.1.1@sha256:aea59a11c54291ac456bb2d67000445e5a8994f70bc3d96cdc29f022fbbf89fb AS runtime
WORKDIR /app
ENV NODE_ENV=production

# The FFmpeg base does not contain Node. Copy the pinned Node distribution rather
# than installing an unpinned package at image-build time.
COPY --from=node-runtime /usr/local/ /usr/local/
COPY --from=vmaf-builder /vmaf-install/usr/local/lib/ /usr/local/lib/

# Fail the image build if the upstream media image ever loses a normative
# analyzer capability. A generic distro `ffmpeg` package is not sufficient.
RUN ffmpeg -hide_banner -filters 2>/dev/null | grep -Eq '[[:space:]]libvmaf[[:space:]]' \
    && ffmpeg -hide_banner -filters 2>/dev/null | grep -Eq '[[:space:]]xpsnr[[:space:]]' \
    && command -v ffprobe >/dev/null

# Copy production node_modules and app files from builder
COPY --from=builder /app/node_modules ./node_modules
COPY package.json package-lock.json* ./

# Copy build outputs and analyzer resources
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/resources ./resources
COPY --from=builder /app/config ./config
# Prisma client is in node_modules when using default output
COPY prisma ./prisma

# The model identity is part of the public PL-v7 evidence contract. Refuse to
# publish an image containing a different file under the canonical name.
RUN echo "e4cf8c147e1368b35497d772920bc92f98c1ad7853c1033d8a836947f427140e  /app/resources/vmaf/vmaf_v1.0.16_3d0h.json" \
    | sha256sum -c - \
    && test -f /app/resources/test_suite_v1/manifest.json \
    && node -e 'const fs=require("fs"),crypto=require("crypto"),path=require("path"); const root="/app/resources/test_suite_v1"; const manifest=JSON.parse(fs.readFileSync(path.join(root,"manifest.json"))); for(const clip of manifest.clips){const bytes=fs.readFileSync(path.join(root,"canonical",clip.fileName)); if(bytes.length!==clip.byteSize||crypto.createHash("sha256").update(bytes).digest("hex")!==clip.sha256) throw new Error(`invalid canonical source ${clip.id}`)}' \
    && test -f /app/config/reference-contexts/test-only.synthetic.encodingdb-test-suite-v1.vmaf-v1-sdr-sd.context.json \
    && ffmpeg -hide_banner -loglevel error \
      -f lavfi -i testsrc2=size=960x540:rate=2:duration=2 \
      -f lavfi -i testsrc2=size=960x540:rate=2:duration=2 \
      -lavfi "[0:v][1:v]libvmaf=model=path=/app/resources/vmaf/vmaf_v1.0.16_3d0h.json:n_threads=1:log_fmt=json:log_path=/tmp/vmaf-preflight.json" \
      -f null - \
    && test -s /tmp/vmaf-preflight.json \
    && grep -q '"vmaf"' /tmp/vmaf-preflight.json \
    && ffmpeg -hide_banner -loglevel error \
      -f lavfi -i testsrc2=size=64x64:rate=1:duration=1 \
      -f lavfi -i testsrc2=size=64x64:rate=1:duration=1 \
      -lavfi "[0:v][1:v]xpsnr" -f null -

EXPOSE 3001

# Default env (override at runtime)
ENV PORT=3001

ENTRYPOINT []
CMD ["node", "dist/index.js"]
