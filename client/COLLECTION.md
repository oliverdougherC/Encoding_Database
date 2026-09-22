# Corrected contribution client

`client/0.3.0` measures protocol `7.1` with `encodeTimerBoundary=ffmpeg-process-v1`.
The monotonic interval starts immediately before launching FFmpeg and ends when its
output pipes close after process completion. It includes startup and flush; it
excludes monitor setup/teardown, probing, validation, hashing, local metrics and uploads.
Historical protocol 7.0 timings are not converted or relabeled by this client.

```sh
python -m client --codec libx264 --presets fast --no-submit
python -m client --codec libx264 --presets fast --campaign full --submit
python -m client --codec h264_videotoolbox --presets default --target-bitrate-kbps 4000 --no-submit
python -m client --resume-campaign campaign-0123456789abcdef --submit
python -m client --upload-only
```

Replace the example campaign ID with the ID printed by your run. Quick runs use one
canonical clip; full runs use all seven with the selected recipe. Each recipe has
one warmup, two required measured repetitions and up to two adaptive repetitions.
The default limits are 100 attempts, 2048 MiB retained storage and 60 minutes per
measurement invocation; change them explicitly with `--max-attempts`,
`--max-storage-mb` and `--max-duration-minutes`. The time allowance starts with the
warmup/repetition schedule. Acquisition and preflight occur before it; uploads and
optional quality diagnostics occur afterward. Expiry cancels owned measurement
processes, writes a budget-exhaustion record and returns exit 11. An explicit
`--resume-campaign ID` starts a new allowance while reusing completed attempts.
Local metrics are optional, enabled by
`--local-metrics`, and run after every timed experiment finishes.

## Guided sweep contract (TUI and Windows GUI share one planner)

A sweep is an encoder x preset x native-quality grid over the frozen EncodingDB
Test Suite v1; the suite itself is never modified, and both surfaces derive the
grid from the same deterministic planner (`client/sweep_plan.py`,
`plannerVersion 1`) against the encoders actually detected as usable. Counts
below assume every supported family is usable; the app always recomputes from
the real encoder set. Quality values are per-family native: CRF for software
families, CQ for NVENC, ICQ for QSV, QP/CQP for AMF/VAAPI/V4L2/OMX and explicit
bitrate kbps only for VideoToolbox; no quality number is ever mapped across
families.

| Mode | Encoders | Presets | Quality points | Clips |
| --- | --- | --- | --- | --- |
| Small | first usable encoder per codec family | one medium-speed preset | 1 (CRF 24; CQ/ICQ/QP 23; 6000 kbps) | quick clip (1) |
| Medium | every usable encoder | same single medium-speed preset | 2 (CRF 22/26; native 20/27; 3000/10000 kbps) | one per content class (7) |
| Large | every usable encoder | three presets across the speed range | 3 (CRF 20/24/28; native 18/23/29; 2000/6000/15000 kbps) | all seven |
| Full | every usable encoder | every supported preset | 10 (CRF/CQ/ICQ/QP 12..30 step 2; 1000..18000 kbps, 7 points) | all seven |

Budget contract for all four modes: every measured group keeps one warmup, two
required stable repetitions and up to two adaptive repeats (3-5 encodes per
group; repetitions are never trimmed). The attempt cap is sized to the plan
unless `--max-attempts` is set explicitly. The default 60-minute allowance is a
checkpoint segment: the guided run saves progress and continues automatically
from the same campaign until the plan completes, is cancelled, or a checkpoint
makes no progress; a checkpoint is never reported as completion. Setting
`--max-duration-minutes` explicitly is honored strictly - one invocation, exit
11, campaign saved. `--max-storage-mb` (default 2048) is enforced in every
segment. Restarting the same mode continues the retained campaign
automatically when the planned tasks exactly match the saved plan (no campaign
ID entry needed in the normal flow); `--resume-campaign ID` remains the
explicit path. Neither surface claims wall-clock durations: absolute times
need measurement evidence, so previews show finite plan/group/encode counts
and hardware-dependent duration only.

CLI Single, menu Advanced and GUI Single keep the manual one-recipe flow: this
same authoritative artifact flow with `--campaign quick|full` clip coverage.
GUI sweep modes and TUI sweep modes use the planner above. `--v7-suite-clip ID`
selects one particular canonical clip. Explicit encoder names never fall back to a
different implementation; the GUI manual default starts on a software encoder
because a listed hardware name does not prove a usable GPU. `--crf` is a native
quality value; `--target-bitrate-kbps` requests a native bitrate mode.
`--legacy-diagnostic` is local-only and noncanonical.

The client checks `/v7/compatibility` before measuring a publishing campaign.
An offline user can collect with `--no-submit`, then publish its retained bytes via
`--resume-campaign ID --submit`. A completed campaign publishes without requiring
its source files, runtime or re-encoding. `--upload-only --resume-campaign ID` also
queues that campaign's prepared submissions; bare `--upload-only` retries the existing
queue. A persistent receipt prevents an already uploaded submission from being sent
again locally; lost responses reuse the exact immutable payload at the server.

Campaign files live under the queue's `campaigns/ID` directory. Per-process timing
checkpoints are committed before validation; completed warmup/measured/skipped
records and artifact hashes are committed before the next attempt. Resume verifies
owned artifacts, protocol, schedule, source identity, hardware and runtime. A crash
after encode can validate its completed artifact without re-encoding. Owned encoder
processes are cancelled on Stop; matching orphan process receipts are fenced before
resume after abrupt process death. The Windows GUI serializes the benchmark worker and
the upload-replay worker on the same spool and tracks both threads until they exit.
The window stays visible while an in-flight request finishes; replay checks its
25-entry/60-second budget between requests, so that budget is not a hard shutdown deadline.

Retries persist a seven-day deadline and a next-attempt time with exponential backoff,
jitter and `Retry-After`. Expired/rejected items remain in dead-letter storage for
inspection. One upload transaction is attempted per due entry; replay handles at
most 25 entries per invocation and stops starting new entries after 60 seconds. Individual
HTTP operations have finite timeouts. Timed experiments never overlap local uploads
or quality analysis in the client.

Exit 0 means locally completed or uploaded; upload alone does not mean accepted.
Exit 10 means uploads remain queued. Exit 1 reports invalid/skipped/rejected/failed work,
exit 5 a compatibility failure, exit 6 a retained campaign/storage/resume error, and
exit 130 cancellation. Exit 11 means the measurement allowance was exhausted and
the campaign is saved for resume. Server analysis and review still determine
suspect, accepted,
rejected, retention and scoring eligibility; upload receipts preserve server responses.

A random installation pseudonym is stored separately from cohorts and campaigns.
It contains no hostname, hardware serial or account identifier. Cloning/resetting an
installation is not proof of a new independent physical machine. Runtime provenance
includes executable/dependency hashes and observed architecture/translation.
NVENC explicitly selects device 0 for encoding and NVML telemetry. VideoToolbox
records system selection; ambiguous QSV/AMF or other devices remain unknown and
unverified. Unknown GPU driver identity is never replaced by an OS version.
Native platform/hardware certification and real human calibration reviews remain
separate release gates; passing unit tests does not certify those cells.

For retained-campaign failures, set `ENCODINGDB_DEBUG_TRACEBACK=1` to include the
original exception stack in diagnostic output. Exit codes and retention behavior remain unchanged.

Completed process checkpoints bind the executable and bundled dependency hashes.
A GUI or CLI relaunch can use a byte-identical helper in a new extraction directory
without re-encoding; meaningful command arguments and artifact checks stay strict.
A checkpoint missing this runtime binding cannot be trusted for process resume.
