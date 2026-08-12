import unittest
from unittest import mock

from client import decode


class DecodeBenchmarkTests(unittest.TestCase):
    def test_build_ffmpeg_decode_cmd_is_pinned_for_software_decode(self) -> None:
        cmd = decode.build_ffmpeg_decode_cmd(input_path="artifact.mp4")

        self.assertIn("-hwaccel", cmd)
        self.assertIn("none", cmd)
        self.assertIn("-threads:v", cmd)
        self.assertIn("1", cmd)
        self.assertIn("-progress", cmd)
        self.assertIn("pipe:1", cmd)
        self.assertEqual(cmd[-2:], ["null", "-"])

    def test_parse_decode_cpu_time(self) -> None:
        stderr = "bench: utime=1.25s stime=0.75s rtime=2.50s\n"
        self.assertEqual(decode.parse_decode_cpu_time(stderr), 2.0)

    def test_run_decode_benchmark_returns_explicit_unsupported_when_source_fps_missing(self) -> None:
        with mock.patch.object(decode.os.path, "exists", return_value=True):
            result = decode.run_decode_benchmark(input_path="artifact.mp4", source_fps=None)

        self.assertFalse(result["supported"])
        self.assertEqual(result["reason"], "source_fps_unavailable")
        self.assertEqual(result["methodology"], "ffmpeg-software-decode-v1")

    def test_run_decode_benchmark_parses_progress_and_benchmark_output(self) -> None:
        completed = mock.Mock(
            returncode=0,
            stdout="frame=120\nprogress=end\n",
            stderr="bench: utime=1.25s stime=0.75s rtime=2.00s\n",
        )
        with mock.patch.object(decode.os.path, "exists", return_value=True), \
                mock.patch.object(decode.subprocess, "run", return_value=completed), \
                mock.patch.object(decode.time, "perf_counter", side_effect=[10.0, 12.0]):
            result = decode.run_decode_benchmark(input_path="artifact.mp4", source_fps=30.0)

        self.assertTrue(result["supported"])
        self.assertEqual(result["framesDecoded"], 120)
        self.assertEqual(result["cpuTimeSeconds"], 2.0)
        self.assertEqual(result["decodeFps"], 60.0)
        self.assertEqual(result["realtimeMultiple"], 2.0)


if __name__ == "__main__":
    unittest.main()
