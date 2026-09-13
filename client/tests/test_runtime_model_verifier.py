import unittest
from scripts.verify_runtime_model import validate_metrics


class RuntimeModelVerifierTests(unittest.TestCase):
    def payload(self):
        return {'frames': [{'frameNum': 0, 'metrics': {'vmaf': 90.0}}, {'frameNum': 1, 'metrics': {'vmaf': 100.0}}], 'pooled_metrics': {'vmaf': {'mean': 95.0}}}

    def test_complete_finite_distribution(self):
        self.assertEqual(validate_metrics(self.payload(), 2), 95.0)

    def test_incomplete_or_misnumbered_frames_rejected(self):
        with self.assertRaises(ValueError):
            validate_metrics(self.payload(), 3)
        payload = self.payload()
        payload['frames'][1]['frameNum'] = 0
        with self.assertRaises(ValueError):
            validate_metrics(payload, 2)

    def test_invalid_frame_or_mean_rejected(self):
        for value in (None, float('nan'), float('inf'), -1, 101):
            for target in ('frame', 'mean'):
                payload = self.payload()
                if target == 'frame':
                    payload['frames'][0]['metrics']['vmaf'] = value
                else:
                    payload['pooled_metrics']['vmaf']['mean'] = value
                with self.subTest(value=value, target=target), self.assertRaises(ValueError):
                    validate_metrics(payload, 2)
