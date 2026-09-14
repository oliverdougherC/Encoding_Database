import dataclasses
import unittest
from client import ffmpeg, recipe

class NvencVbrTest(unittest.TestCase):
    def test_explicit_native_targets_and_optional_limits(self):
        for encoder in ('h264_nvenc', 'hevc_nvenc', 'av1_nvenc'):
            rc = recipe.build_rate_control_config(encoder=encoder, mode='vbr', target_bitrate_kbps=4000, max_bitrate_kbps=6000, buffer_size_kbits=8000)
            self.assertEqual(ffmpeg._build_rate_control_args(encoder=encoder, rate_control=rc), ['-rc', 'vbr', '-b:v', '4000k', '-maxrate:v', '6000k', '-bufsize:v', '8000k'])
            cmd = ffmpeg.build_ffmpeg_encode_cmd(input_path='source.mkv', output_path='output.mp4', encoder=encoder, preset_name='p4', rate_control=rc)
            self.assertEqual(cmd[cmd.index('-c:v') + 1], encoder)
            self.assertEqual(cmd[cmd.index('-preset') + 1], 'p4')
            self.assertNotIn('-cq', cmd)
            self.assertNotIn('-qp', cmd)
            self.assertNotIn('libx264', cmd)

    def test_rejects_missing_nonpositive_limits_and_unsupported_modes(self):
        for values in ({'targetBitrateKbps': None}, {'targetBitrateKbps': 0}, {'targetBitrateKbps': -1},
                       {'targetBitrateKbps': 4000, 'maxBitrateKbps': 0}, {'targetBitrateKbps': 4000, 'bufferSizeKbits': -1},
                       {'targetBitrateKbps': 4000, 'maxBitrateKbps': 2000}):
            with self.assertRaises(ValueError): ffmpeg._build_rate_control_args(encoder='h264_nvenc', rate_control=recipe.RateControlConfig(mode='vbr', **values))
        for mode in ('cbr', 'abr', 'crf', 'other'):
            with self.assertRaises(ValueError): ffmpeg._build_rate_control_args(encoder='h264_nvenc', rate_control=recipe.RateControlConfig(mode=mode, targetBitrateKbps=4000))

    def test_native_choice_identity_and_quality_modes_remain_distinct(self):
        fingerprints = set()
        for target in (1500, 3000, 4000, 6000, 8000, 12000):
            rc = recipe.build_rate_control_config(encoder='h264_nvenc', mode='vbr', target_bitrate_kbps=target)
            fingerprints.add(recipe.sha256_fingerprint(dataclasses.asdict(rc)))
            self.assertEqual(ffmpeg._build_rate_control_args(encoder='h264_nvenc', rate_control=rc), ['-rc', 'vbr', '-b:v', f'{target}k'])
        self.assertEqual(len(fingerprints), 6)
        for mode, flag in [('cq', '-cq'), ('qp', '-qp')]:
            rc = recipe.build_rate_control_config(encoder='h264_nvenc', mode=mode, quality_value=23)
            self.assertEqual(ffmpeg._build_rate_control_args(encoder='h264_nvenc', rate_control=rc), [flag, '23'])

if __name__ == '__main__': unittest.main()
