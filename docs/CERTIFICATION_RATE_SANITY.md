# Canonical rate-sanity grid

Executed 2026-09-10T01:47:03.908282+00:00; source checkout `735c7c8e50ee4d52eaa71c1d766d93ffe0c440d3`.

**Result: six of six tested points across three classes pass the existing server metric-disagreement check. Choose CRF12, the less extreme of the two predeclared quality settings, for the next all-seven packaged-client acceptance attempt.** This local rate-sanity grid does not itself certify packaged-client submission, retained server analysis, or public acceptance.

The bounded grid was fixed in advance: libx264, preset fast, CRF12 and CRF8 on each of film grain, dark gradients, and talking head. All six points executed; no additional search or threshold/status changes were made. Existing CRF24 SUSPECT records remain untouched and must remain visible as disagreement evidence. This is not PL calibration or holdout validation.

| Reference | CRF | Encoded bytes | VMAF mean | XPSNR | SSIM | PSNR | Spread | Flag |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| film-grain | 12 | 164197802 | 99.663376 | 44.3855 | 0.986288 | 47.030056 | 1 | False |
| dark-gradients | 12 | 156726533 | 96.882499 | 44.409 | 0.987556 | 48.237416 | 1 | False |
| talking-head | 12 | 56568428 | 98.909745 | 43.0682 | 0.989818 | 47.447244 | 1 | False |
| film-grain | 8 | 233946488 | 99.978534 | 48.2779 | 0.994322 | 50.901705 | 0 | False |
| dark-gradients | 8 | 224944399 | 98.734603 | 48.1258 | 0.994668 | 51.939315 | 0 | False |
| talking-head | 8 | 104806475 | 99.795264 | 47.088 | 0.995101 | 50.818366 | 0 | False |

Every point has 240 analyzed frames. CRF12 bands are excellent for VMAF/XPSNR/PSNR and strong for SSIM (spread 1); CRF8 bands are all excellent (spread 0). The exported server `diagnoseMetricDisagreement` returned an empty reasons list for every point. Neither setting is lossless; CRF8 increases upload size materially.

Runtime SHA256: `11e22f179237b2b03888f789c5bf43e8a52d2e2636394498ab28b825a923fdfe`. Model SHA256: `e4cf8c147e1368b35497d772920bc92f98c1ad7853c1033d8a836947f427140e`.

The unchanged `client.ffmpeg.canonical_quality_filter(24, metric)` generates the authoritative cadence/timebase/frame-index alignment. VMAF uses 10-bit analysis; XPSNR, SSIM, and PSNR retain native 8-bit inputs. The exact server exported parsers (`parseXpsnrReport`, `parseSsimReport`, `parsePsnrReport`) and `diagnoseMetricDisagreement` process the real logs. All encoding/metric commands exited zero.

Representative command templates (run from each point output directory with the pinned model copied to `model.json`):

```text
ffmpeg -hide_banner -y -i REFERENCE -map 0:v:0 -an -c:v libx264 -preset fast -crf CRF -threads 2 encoded.mp4
ffmpeg -hide_banner -threads 2 -i encoded.mp4 -threads 2 -i REFERENCE -filter_complex_threads 2 -lavfi GRAPH -f null -
GRAPH(VMAF)=[0:v]fps=24,settb=AVTB,setpts=N/(24*TB),format=pix_fmts=yuv420p10le[distorted];[1:v]fps=24,settb=AVTB,setpts=N/(24*TB),format=pix_fmts=yuv420p10le[reference];[distorted][reference]libvmaf=model=path=model.json:n_threads=2:log_fmt=json:log_path=vmaf.json
GRAPH(diagnostic)=[0:v]fps=24,settb=AVTB,setpts=N/(24*TB)[distorted];[1:v]fps=24,settb=AVTB,setpts=N/(24*TB)[reference];[distorted][reference]METRIC
METRIC=xpsnr, ssim, or psnr (separate executions)
```

Exact per-point commands, full frame metrics, raw FFmpeg logs, encoded files, and result JSON are retained locally under `.build/certification-rate-sanity/<class>-crf<CRF>/`; these are local execution evidence, not a published candidate artifact location. This checked-in summary preserves the executed outcome and identities.

| Reference | Reference SHA256 |
|---|---|
| film-grain | `67d3d2f5a4f8c617f223077e7071aaee625f014950126e0e93a16b27e578d603` |
| dark-gradients | `3377e6927fdd256633961520ace19f6b5b1494f689841ed3a29831e48e0d27c3` |
| talking-head | `ac85d1350e5e668d5c0798b25fd7de16f8da05e831f396680a8f0f0ab05bcaf3` |

| Point | Encoded SHA256 | VMAF JSON SHA256 |
|---|---|---|
| film-grain CRF12 | `80046ea861fadded4f52eb1a2ec036fab5b3dce61c06dd11834f839df70be070` | `16909bd4d922496368ad1c1d50e49c43d0687368a38e45e3b74a97f32d6a892b` |
| dark-gradients CRF12 | `68fd744f640ea0d5136c414266f7c2fec8814d3cc6dfd3f317586c5c1c53bb5f` | `62b2ac580ac520f6dde9380148ce6e3859ec50300770089c2674da0cfdfd19c5` |
| talking-head CRF12 | `e1c458ed27c54e3e342df601ec103c5a500709c451e76fcb7e1b8703c747392c` | `b3fecee443f34567c26dcbf68c8328e324d17561e15e14858bc674e8d1ada167` |
| film-grain CRF8 | `e41b1b361ed28cb1889cc5a5c87053ecf169317f6b9924e60c349df7218cde5f` | `747a8c7e97e1a3b653a146e42453918a9858171cc6a95fd98607d6d448f2bee1` |
| dark-gradients CRF8 | `5f631852b23a6b1c079e32c338c4b93745a14bca5ea03c72fad4c34bac029934` | `7486cc548579a0f44070140e8b34519b2c8fe4e89ed5876bfe64f56cbfb5cc6d` |
| talking-head CRF8 | `f09d7ae08414417aa13a189da21fe4337b142b1967b3a5f3dd93364c85540367` | `4b14acd960a1e8e298abdb243e07249c5715ecbf6821f7cc3aca71903f0b6847` |
