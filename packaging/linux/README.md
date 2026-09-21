# EncodingDB for Linux

Contributor client for the EncodingDB benchmark: it measures your machine's real
encoding behavior against the canonical test suite and submits the evidence with
your consent.

## Requirements (honest scope)

- x86_64 Linux built on the Ubuntu CI runner image; older glibc releases are
  unverified. No GPU vendor SDK installation is required; NVENC and software
  encoders come from the bundled locked FFmpeg runtime and are probed at startup.
- The unsigned ELF binary is what it is: verify the published SHA-256 before
  first run (`sha256sum -c encodingdb-client-linux.tar.gz.SHA256SUMS`).

## Run it

Extract with plain `tar -xzf` (executable bits are preserved; no chmod needed):

```sh
tar -xzf encodingdb-client-linux.tar.gz
cd encodingdb-client-linux
./start.sh
```

`./start.sh` with no arguments starts the **guided menu**: it detects usable
encoders, walks the sweep you pick, shows the real plan and progress, and
submits only after one explicit consent. Advanced flags pass straight through,
e.g. `./start.sh --help`.

State lives in `$XDG_STATE_HOME/EncodingDB` (default `~/.local/state/EncodingDB`)
and cache in `$XDG_CACHE_HOME/encodingdb` (default `~/.cache/encodingdb`). The
archive can live anywhere, including read-only locations.

## Contents

- `encodingdb-client-linux` — the packaged client (advanced users may run it directly)
- `start.sh` — default launch path (guided menu)
- `README.md` — this file
