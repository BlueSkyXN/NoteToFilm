"""compose 附带的运动量测量脚本：纯计算部分和缺少 OpenCV 时的提示。真实光流需要 OpenCV，不在回归里跑。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / '.agents/skills/notetofilm-compose/scripts/measure_motion.py'
spec = importlib.util.spec_from_file_location('ntf_measure_motion_test', SCRIPT)
measure_motion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measure_motion)


def run_without_opencv(*args):
    code = ('import runpy, sys; sys.modules["cv2"] = None; '
            f'sys.argv = ["measure_motion.py", *{list(args)!r}]; runpy.run_path({str(SCRIPT)!r}, run_name="__main__")')
    return subprocess.run([sys.executable, '-I', '-c', code], capture_output=True, text=True, timeout=30)


class MeasureMotionTests(unittest.TestCase):
    def test_sample_size_keeps_display_aspect(self):
        self.assertEqual(measure_motion.scaled_size(1920, 1080), (320, 180))
        self.assertEqual(measure_motion.scaled_size(1080, 1920), (320, 568))
        self.assertEqual(measure_motion.scaled_size(1920, 1080, -90), (320, 568))

    def test_summary_skips_jumps_and_lists_long_still_runs(self):
        steps = [(.1, .2, 1)] * 20 + [(3, 3, 40)] + [(2, 1, 3)] * 10 + [(.1, .1, 1)] * 5
        summary = measure_motion.summarize(steps)
        self.assertEqual(summary['measured_seconds'], 3.6)
        self.assertEqual(summary['jump_steps'], 1)
        self.assertEqual(summary['still_share'], round(25 / 36, 3))
        self.assertEqual(summary['still_runs'], [{'start_seconds': 0.0, 'end_seconds': 2.0}])
        self.assertEqual(summary['still_runs_share'], round(2 / 3.6, 3))
        self.assertEqual(summary['camera_motion_median'], 0.1)
        self.assertEqual(summary['in_frame_motion_median'], 0.2)
        self.assertEqual(summary['in_frame_motion_p75'], 1.0)
        with self.assertRaises(measure_motion.MeasureError):
            measure_motion.summarize([])

    def test_help_and_missing_opencv_message(self):
        help_result = run_without_opencv('--help')
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn('pace', help_result.stdout)
        with tempfile.TemporaryDirectory(prefix='ntf-measure-motion-') as directory:
            film = Path(directory) / 'film.mp4'
            film.write_bytes(b'')
            result = run_without_opencv(str(film))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('opencv-python-headless', result.stderr)
        self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
