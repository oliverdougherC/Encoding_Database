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
  2. This build is ad-hoc signed only: no Developer ID signature, and it is
     not notarized, so macOS will block the very first launch. Double-click the
     app once, then open System Settings → Privacy & Security and press
     "Open Anyway" for EncodingDB (Apple's current guidance, updated
     2026-05-27: https://support.apple.com/en-us/102445). The prompt shows the
     app identity and its developer/build origin; the checksums below let you
     confirm you are trusting exactly the published bytes. We never disable
     Gatekeeper or remove the quarantine flag for you behind your back — this
     approval is your explicit choice, made once.

Everyday launch:
  • Double-click EncodingDB.app in Applications. Terminal opens with the
    guided EncodingDB interface — pick an encoder sweep, review the plan, and
    submit with one consent. If the window closes unexpectedly, the CLI path
    below shows the exact error.

Power users (same binary, your own terminal):
  /Applications/EncodingDB.app/Contents/Resources/encodingdb

State lives in ~/Library/Application Support/EncodingDB and results cache in
~/Library/Caches/EncodingDB; nothing is written inside the app bundle.

Verification:
  • The published release page lists the SHA-256 for this DMG. Alongside it you
    get EncodingDB-macOS-arm64.dmg.SHA256SUMS and .package-info.json.
    From the download folder run:
      shasum -a 256 -c EncodingDB-macOS-arm64.dmg.SHA256SUMS
    .package-info.json also records the exact embedded CLI hash inside the app,
    so the DMG, the app, and the release manifest chain to one identity.

Support scope: this package exercises software encoders and VideoToolbox on the
tested Apple Silicon machine. Calibration-backed quality scores are a server-side
concern; the client collects and submits evidence, it does not certify scores
locally.
