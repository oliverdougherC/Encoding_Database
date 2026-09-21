# Linux native acceptance at 939823e

Source: `939823ead2c052572f9deb5c9f91c85435d5661d`.
Executable SHA256:
`46a6dcad789f824909911455b19979a33e4053dae1440f09524da5142ca18dc3`.
The source, executable bytes, physical installation identity and prescribed recipes
were held fixed. All collection used the shared physical-host lock with candidate
analysis concurrency zero. No uploads or quality analysis belong to this phase.

## Preparation and instrumentation corrections

The candidate's actual API and frontend passed trusted TLS smoke on port 3094.
The first clean acquisition attempt failed before any encode because a custom CA
bundle containing only the candidate certificate replaced the public trust roots
needed for GitHub. Its help command passed, acquisition exited 3, and the original
logs and zero-attempt state were retained. The corrected attempt used the existing
certifi roots plus the candidate public certificate; verification was never disabled.

The separate instrumented smoke then passed: help exited 0 in 12.89 seconds, and
the no-submit quick campaign exited 0 in 332.11 seconds, including 281.16 seconds
of preparation. It retained one warmup and two measured attempts, with no timeout,
forced cleanup or survivors. It acquired the frozen pack from the advertised URL
into an empty cache. Execve traces and the frozen runtime receipt proved helpers
inside `/tmp/_MEI…/bin/linux/` with runtime fingerprint
`494132ca850dadf47226fbb267bcde9d454b37b4a68892d9759d48db3a89fe7b`.
Its timings are instrumented diagnostics, not ordinary performance or calibration.

The initial full software preparation also ran under that tracer. A two-second
observation at 02:32:12 UTC showed the tracer consuming 46.5% of one CPU while
ffprobe used 99%; the tracer did not use seccomp filtering. At that observation
there were zero attempts or manifests. A safety recheck before cancellation found
that warmups had begun, so it correctly sent no signal. The parent subsequently
authorized ending the entire instrumented attempt. By the actual stop at
02:37:15 UTC it had **seven warmups and eight measured records**; those original
records and flags were preserved and the whole attempt was explicitly excluded
from ordinary performance and calibration. The count must not be reported as zero.
The owned driver exited 130 through its supervisor cleanup. No traced NVENC phase
started. No owned survivors remained and the shared lock was free at 02:38:29 UTC.

The ordinary campaigns use a new directory, no tracer, the same software seed
`5058032615262009152`, unchanged recipes and the already verified download cache.
The first NVENC execution was declared with that same seed before it began.
Embedded-runtime receipts, saved executed commands and process checkpoints supply
ordinary-run identity evidence without instrumentation. Instrumented queues are
not authorized inputs for the subsequent publication phase.

## Ordinary software result

`libx264`, preset `medium`, CRF `24`, all seven final canonical clips:

- Exit 0; 986.24 seconds total, including 516.34 seconds of source preparation.
- 29 retained attempts: seven warmups and 22 measured attempts.
- All 29 attempts reported valid structural/environment checks.
- Three stable groups and four unstable groups, using the unchanged 3% threshold.
- Immutable manifest/completion/attempt/artifact ledger captured before publication.

| Clip | Counted measured runs | Relative timing spread | Stable |
| --- | ---: | ---: | --- |
| Athletic action | 4 | 3.0532% | No |
| Natural detail | 2 | 1.0243% | Yes |
| Film grain | 4 | 4.2307% | No |
| Dark gradients | 4 | 4.9624% | No |
| Animation | 4 | 3.7190% | No |
| Screen/text | 2 | 0.5169% | Yes |
| Talking head | 2 | 2.7781% | Yes |

No attempt was dropped or repeated beyond the protocol's own adaptive schedule.
In particular, the action result remains unstable despite being close to 3%.
Client validity and timing stability do not claim authoritative quality-analysis
completion, human review, calibration eligibility or PL availability.

## Ordinary NVENC result

`h264_nvenc`, preset `p4`, VBR `4000` kbps, device `0`, all seven final clips:

- Exit 0; 813.34 seconds total, including 511.77 seconds of source preparation.
- 25 retained attempts: seven warmups and 18 measured attempts.
- All 25 attempts reported valid structural/environment checks.
- Five stable groups and two unstable groups; no extra retries or removed records.
- Immutable manifest/completion/attempt/artifact ledger captured before publication.

| Clip | Counted measured runs | Relative timing spread | Stable |
| --- | ---: | ---: | --- |
| Athletic action | 2 | 1.2948% | Yes |
| Natural detail | 4 | 11.6768% | No |
| Film grain | 2 | 1.3638% | Yes |
| Dark gradients | 2 | 0.6372% | Yes |
| Animation | 2 | 0.0683% | Yes |
| Screen/text | 2 | 0.0730% | Yes |
| Talking head | 4 | 13.5933% | No |

The ordinary journal audit verified all 54 attempts' source/output frame counts
(192 for animation, 240 for the other clips), decodable output, and exact embedded
encode-helper path. Every NVENC command contains `-gpu 0 -rc vbr -b:v 4000k`,
`-preset p4` and `-c:v h264_nvenc`; every software command uses the declared
`libx264`/`medium`/CRF `24` recipe. The selected GPU is NVIDIA GeForce GTX 1070,
driver `580.173.02`, PCI bus `00000000:01:00.0`, and NVML device selection `nvenc:0`.
Client and helpers report native `x86_64` architecture. Host observations identify
Intel Xeon E5-2699 v4, Linux `6.8.0-139-generic`, and 135,025,184,768 physical RAM bytes.

All **40 measured attempts** have finite fresh background CPU readings and the
`cpu_psutil_thread_window_v1` source marker. All 40 also have positive FFmpeg
process-CPU utilization and `ffmpeg_psutil_process_window_v1`: software averages
range from 1198.70% to 2380.33%, and NVENC from 656.80% to 1330.45%. These process
percentages sum work across cores and can exceed 100%. CPU **seconds** remain null
in the protocol timing records; they are not inferred from utilization. All 18
measured NVENC snapshots have trustworthy GPU samples. Unsupported CPU RAPL energy
and unavailable battery telemetry remain explicitly missing.

## Handoff and remaining acceptance

Both ordinary campaigns completed under the unchanged source, binary and physical
installation ID. The driver and supervised children exited; the shared host lock
was verified free at `2026-09-20T03:12:07Z`. No upload or analysis had begun. Only
the two **untraced** queue paths below may feed the next coordinated upload/fault
recovery phase. The instrumented campaign uses the same software seed/campaign ID
but is excluded as a separate case; its files must never be merged or published.

- Software: `日本語 client trial/software-queue`, campaign `campaign-7fda61d90a423692`.
- NVENC: `日本語 client trial/nvenc-queue`, campaign `campaign-d1f98ff0e4f350a2`.

Remaining acceptance is actual upload/backpressure/lost-response replay, exact
retained object/database reconciliation, authoritative quality-analysis drain,
and a post-contribution backup/restore. The separate P910 capacity repeat still
misses its p95 gate; these client results do not change that result or establish
calibration, human review, production readiness or available PL scores.

Remote ordinary evidence root:
`/mnt/NVME/docker/encodingdb-operations/20260920-native-939823e-untraced`.
Original instrumented and CA-only failure roots remain alongside it under
`20260920-native-939823e-trusted-roots` and `20260920-native-939823e`.

The committed evidence directory is
[`evidence/native-linux-939823e`](evidence/native-linux-939823e).
`ordinary-summary.json` contains the audited group, command and provenance facts;
`execution.json` contains phase boundaries and supervisor results. The original
300 JSON/log/driver receipts are preserved byte-for-byte in
`native-metadata-receipts.tar.gz`, SHA256
`0ba3337fe9831ef578a75802671e020e81220084730a3ad04375cef39d9dc131`.
Every archived member was independently checked against its indexed byte count
and SHA256 after copying locally. The archive contains no encoded media; original
artifacts remain in their owned P910 campaign directories and their hashes are
bound by the immutable ledgers.
