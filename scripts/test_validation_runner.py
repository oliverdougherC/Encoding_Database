import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('validation_runner', Path(__file__).with_name('run-validation-campaign.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

class NativeRecipeTest(unittest.TestCase):
    def test_software_choices_remain_native_crf(self):
        self.assertEqual(runner.validation_recipe('libx264', 'fast', 18, None), ('fast', 18, None))
        self.assertEqual(runner.validation_recipe('libsvtav1', '6', 36, None), ('6', 36, None))

    def test_hardware_targets_use_canonical_vbr(self):
        for encoder, preset in [('h264_nvenc', 'p4'), ('h264_videotoolbox', 'default')]:
            for target in (4000, 8000):
                selected, crf, native = runner.validation_recipe(encoder, preset, None, target)
                self.assertEqual(selected, preset)
                self.assertIsNone(crf)
                self.assertEqual(native.mode, 'vbr')
                self.assertEqual(native.targetBitrateKbps, target)
                self.assertIsNone(native.qualityValue)

    def test_rejects_implicit_or_substituted_hardware_choices(self):
        for args in [('h264_nvenc', 'p4', 23, 4000), ('h264_nvenc', 'p4', None, None),
                     ('h264_videotoolbox', 'fast', None, 4000), ('h264_nvenc', 'p4', None, 0),
                     ('libx264', 'fast', None, 4000), ('libx264', 'fast', 80, None)]:
            with self.assertRaises(ValueError): runner.validation_recipe(*args)

if __name__ == '__main__': unittest.main()
