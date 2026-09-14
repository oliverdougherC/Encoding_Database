# Apple system GPU observations

For a VideoToolbox encoder on a Mac with one observed system-selected adapter,
HardwareMonitor reads `/usr/sbin/ioreg -a -r -c AGXAccelerator -d 1` without
privileges. The single AGX node must match the model already resolved by the
VideoToolbox selected-device identity. The collector accepts only a numeric,
finite `PerformanceStatistics["Device Utilization %"]` between 0 and 100. Zero is
an observed value; missing, malformed, oversized, failed, mismatched or ambiguous
results remain unknown. Reads have a one-second deadline and a 256 KiB response
budget; timeout/failure uses the existing collector backoff. The child is reaped
on timeout or oversized output.

The source marker is `gpu_ioreg_agx_system_utilization_v1`. This is the driver's
system GPU utilization observation, **not** VideoToolbox media-engine occupancy,
per-process utilization, GPU temperature, power, or an inferred driver version.
It can reveal background system-GPU load on the inspected single-adapter Apple
Silicon topology. It does not prove that every source of media-engine contention
has been observed. Unavailable temperature remains explicitly unavailable.

`HardwareMetrics.gpu_sample_count` continues to count all GPU observations.
`gpu_util_sample_count` counts only valid utilization observations; protocol
snapshots use this count and a finite utilization average for GPU-load trust.
Temperature-only, memory-only, invalid or nonfinite samples cannot establish
load trust. Existing background-load thresholds are unchanged: obtaining telemetry
can expose a busy host and make its measurements suspect or invalid.

The initial read-only discovery was macOS 27.0 / build 26A428 on Apple M4 Pro.
This driver property is a best-effort observed capability, not a cross-version
API guarantee. Missing or different future properties fail closed. No privileged
helper, sudo invocation or service configuration is installed. No newly collected
observation retroactively qualifies attempts that lacked telemetry at measurement
time. The focused fixture preserves only the relevant fields from the actual
single-adapter read-only receipt.

At source `d4b1a26`, actual nonprivileged HardwareMonitor collection produced six
valid utilization samples averaging 60.5%. A subsequent protocol snapshot had two
valid samples averaging 65.5%, and the unchanged 35% suspect threshold correctly
returned `background-gpu-suspect`. Temperature stayed unknown. These observations
prove source attribution and the fail-closed readiness behavior, not that this
busy host was ready for qualified hardware measurements. The exact samples,
snapshot, tests and environmental fixture failure are retained in
`evidence/mac-agx-collector/`.
