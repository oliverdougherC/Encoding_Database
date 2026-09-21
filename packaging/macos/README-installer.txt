EncodingDB for macOS — how to install and run
=============================================

Requirements (honest, per the accepted build manifests and load commands):
  • Apple Silicon (arm64) Mac.
  • macOS 27 or later. The complete embedded runtime requires macOS 27.0
    (libpcre2/libharfbuzz load commands); older macOS versions are unverified.
  • ~150 MB free disk space for the app plus its working cache.

First install:
  1. Drag "EncodingDB.app" into the "Applications" folder shortcut next to it.
     (Running directly from this read-only DMG works, but Applications is faster
     and avoids the randomized read-only mount macOS applies to downloads.)
  2. This build is ad-hoc signed. It is not Developer ID signed and it is
     not notarized, so macOS will warn on the first launch. Right-click
     EncodingDB.app → Open → Open to approve it once. We never remove the
     quarantine flag for you behind your back; this approval is your choice.

Everyday launch:
  • Double-click EncodingDB.app. Terminal opens with the guided EncodingDB
    interface — pick an encoder sweep, review the plan, and submit with one
    consent. If the window closes unexpectedly, the CLI path below shows the
    exact error.

Power users (same binary, your own terminal):
  /Applications/EncodingDB.app/Contents/Resources/encodingdb

Verification:
  • The published release page lists the SHA-256 for this DMG. Alongside it you
    get EncodingDB-macOS-arm64.dmg.SHA256SUMS and .package-info.json.
    From the download folder run:
      shasum -a 256 -c EncodingDB-macOS-arm64.dmg.SHA256SUMS

Support scope: this package exercises software encoders and VideoToolbox on the
tested Apple Silicon machine. Calibration-backed quality scores are a server-side
concern; the client collects and submits evidence, it does not certify scores
locally.
