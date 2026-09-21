# Process CPU diagnostic evidence

On source `d0a97322c5fccb6186ff433a769b32f45dbdcb83`, the actual locked macOS ARM64 FFmpeg helper encoded five seconds of paced synthetic 1080p input to the null muxer. It exited 0, produced ten fresh process CPU samples, and reported 56.51% average and 137.3% maximum with `ffmpeg_psutil_process_window_v1`. One fully busy CPU remains 100%; values above 100% are valid for a multithreaded process. The exact command, helper SHA, timestamps, all samples, and telemetry are in `actual-ffmpeg.json`; the native output is in `ffmpeg-stderr.txt`.

`probe.py` preserves the execution procedure (the durable log filename replaces the temporary `.log` filename). This is a source-client diagnostic probe using the locked native helper, not execution of a final packaged client. Pacing and synthetic input make it unsuitable as calibration or encoding-speed evidence.

The focused regression command passed 52 tests in 1.42 seconds:

```sh
/Users/ofhd/Developer/Encoding_Database/.venv-release/bin/python -m pytest -q client/tests/test_process_cpu_windows.py client/tests/test_cpu_sampler_baseline.py client/tests/test_cpu_window_provenance.py client/tests/test_telemetry_monitor.py client/tests/test_agx_telemetry.py
```

The tests exercise real psutil process-delta calculation with deterministic OS counters, including the original first-read-zero failure, PID creation-time changes, unknown/failed counters, cold children, too-short windows, partial discovery, and valid zero samples. Existing corrected system/background CPU provenance and AGX tests continue to pass.

Earlier all-zero process CPU diagnostics from the disposable-object collector cannot be interpreted as observed idle CPU or repaired retrospectively. This change does not relabel old records or alter their independently observed timing/background CPU evidence.
