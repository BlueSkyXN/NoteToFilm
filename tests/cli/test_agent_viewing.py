"""联系表、扫描提示与字幕断行：让 Agent 按时间查看实际成片。"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from notetofilm_local.errors import NTFError
from notetofilm_local.inspection import inspect_media
from notetofilm_local.sheet import contact_sheet
from notetofilm_local.text_overlay import _lines

ROOT = Path(__file__).resolve().parents[2]


def ffmpeg(*args):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', *args], check=True, capture_output=True)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class ContactSheetTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='ntf-sheet-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.movie = self.root / 'film.mp4'
        ffmpeg('-f', 'lavfi', '-i', 'color=c=red:s=160x90:r=10:d=2', '-f', 'lavfi', '-i', 'color=c=blue:s=160x90:r=10:d=2',
               '-filter_complex', '[0][1]concat=n=2:v=1[v]', '-map', '[v]', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(self.movie))
        self.timeline = self.root / 'timeline.json'
        self.timeline.write_text(json.dumps({
            'duration_seconds': 4,
            'scenes': [{'id': 'a', 'start_seconds': 0, 'end_seconds': 2},
                       {'id': 'b', 'start_seconds': 2, 'end_seconds': 4, 'transition': {'type': 'cut', 'duration_seconds': 0}}],
            'subtitles': [{'start_seconds': 2.2, 'end_seconds': 3.6, 'text': '第二段旁白'}]}))

    def cell_color(self, sheet_path, index, cell=(320, 180), columns=4):
        from PIL import Image
        x = 4 + (index % columns) * (cell[0] + 4) + cell[0] // 2
        y = 26 + (index // columns) * (cell[1] + 22 + 4) + cell[1] // 2
        with Image.open(sheet_path) as image:
            return image.convert('RGB').getpixel((x, y))

    def test_full_pass_labels_source_time_scene_and_subtitle(self):
        result = contact_sheet(self.movie, output=self.root / 'sheet', fps=2, timeline=self.timeline)
        frames = result['sheets'][0]['frames']
        self.assertEqual([f['time_seconds'] for f in frames], [0, .5, 1, 1.5, 2, 2.5, 3, 3.5])
        self.assertEqual([f['scene_ids'] for f in frames], [['a']] * 4 + [['b']] * 4)
        self.assertEqual(frames[5]['subtitle'], '第二段旁白')
        self.assertIsNone(frames[1]['subtitle'])
        red, blue = self.cell_color(result['sheets'][0]['path'], 1), self.cell_color(result['sheets'][0]['path'], 5)
        self.assertGreater(red[0], 150)
        self.assertLess(red[2], 100)
        self.assertGreater(blue[2], 150)
        self.assertLess(blue[0], 100)
        saved = json.loads((self.root / 'sheet/sheet.json').read_text())
        self.assertEqual(saved['windows'][0]['label'], 'full')
        self.assertEqual(sorted(p.name for p in (self.root / 'sheet').iterdir()), ['sheet.json', 'sheet_001.jpg'])

    def test_cut_windows_and_sheet_splitting(self):
        result = contact_sheet(self.movie, output=self.root / 'cuts', fps=4, timeline=self.timeline, cuts=True, max_cells=4)
        self.assertEqual([w['label'] for w in result['windows']], ['cut a>b'])
        window = result['windows'][0]
        self.assertEqual((window['start_seconds'], window['end_seconds']), (1.5, 2.5))
        frames = [f for sheet in result['sheets'] for f in sheet['frames']]
        self.assertEqual([f['time_seconds'] for f in frames], [1.5, 1.8, 2, 2.3])
        self.assertEqual(frames[2]['scene_ids'], ['b'])
        partial = contact_sheet(self.movie, output=self.root / 'split', fps=2, max_cells=4)
        self.assertEqual(len(partial['sheets']), 2)

    def test_rejected_requests_keep_existing_output(self):
        with self.assertRaises(NTFError) as error:
            contact_sheet(self.movie, output=self.root / 'x', cuts=True)
        self.assertEqual(error.exception.code, 'sheet_parameters')
        with mock.patch('notetofilm_local.sheet.MAX_FRAMES', 10), self.assertRaises(NTFError) as error:
            contact_sheet(self.movie, output=self.root / 'y', fps=4)
        self.assertEqual(error.exception.code, 'sheet_too_many_frames')
        self.assertFalse((self.root / 'y').exists())
        occupied = self.root / 'occupied'
        occupied.mkdir()
        (occupied / 'keep.txt').write_text('earlier')
        with self.assertRaises(NTFError) as error:
            contact_sheet(self.movie, output=occupied)
        self.assertEqual(error.exception.code, 'output_exists')
        self.assertEqual((occupied / 'keep.txt').read_text(), 'earlier')

    def test_cli_entry(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/ntf.py'), 'sheet', str(self.movie),
                                 '--output', str(self.root / 'cli'), '--timeline', str(self.timeline), '--cuts', '--fps', '4'],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['windows'][0]['label'], 'cut a>b')
        conflict = subprocess.run([sys.executable, str(ROOT / 'scripts/ntf.py'), 'sheet', str(self.movie),
                                   '--output', str(self.root / 'cli2'), '--cuts', '--start', '1'],
                                  capture_output=True, text=True, timeout=60)
        self.assertEqual(conflict.returncode, 2)
        self.assertIn('sheet_parameters', conflict.stderr)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class ScanTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='ntf-scan-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_freeze_black_and_silence_are_reported_with_scene_ids(self):
        movie = self.root / 'scan.mp4'
        ffmpeg('-f', 'lavfi', '-i', 'color=c=black:s=160x90:r=10:d=1', '-f', 'lavfi', '-i', 'testsrc=s=160x90:r=10:d=1',
               '-f', 'lavfi', '-i', 'color=c=blue:s=160x90:r=10:d=2',
               '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono:d=2',
               '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
               '-filter_complex', '[0][1][2]concat=n=3:v=1[v];[3][4][5]concat=n=3:v=0:a=1[a]',
               '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(movie))
        timeline = self.root / 'timeline.json'
        timeline.write_text(json.dumps({'duration_seconds': 4, 'scenes': [
            {'id': 'open', 'start_seconds': 0, 'end_seconds': 2}, {'id': 'hold', 'start_seconds': 2, 'end_seconds': 4}]}))
        result = inspect_media(movie, scan=True, timeline=timeline)
        scan = result['scan']
        self.assertEqual(scan['black'][0]['start_seconds'], 0)
        self.assertEqual(scan['black'][0]['scene_ids'], ['open'])
        self.assertTrue(any(item['start_seconds'] >= 1.9 and item['scene_ids'] == ['hold'] for item in scan['freeze']))
        self.assertEqual(len(scan['silence']), 1)
        self.assertAlmostEqual(scan['silence'][0]['start_seconds'], 1, delta=.15)
        self.assertAlmostEqual(scan['silence'][0]['end_seconds'], 3, delta=.15)
        self.assertIsNone(result['verification']['passed'])

    def test_low_motion_reports_still_picture_under_changing_caption(self):
        """字幕条一直在闪，冻结扫描不报；画面本身没动，低运动区间要报出来，剪点后持续运动的画面不算。"""
        still, moving, movie = self.root / 'still.mp4', self.root / 'moving.mp4', self.root / 'film.mp4'
        ffmpeg('-f', 'lavfi', '-i', 'color=c=gray:s=160x90:r=10:d=3',
               '-vf', "drawbox=x=40:y=70:w=60:h=6:color=white:t=fill:enable='lt(mod(t\\,0.6)\\,0.3)'",
               '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(still))
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=10:d=2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(moving))
        ffmpeg('-i', str(still), '-i', str(moving), '-filter_complex', '[0][1]concat=n=2:v=1[v]', '-map', '[v]',
               '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(movie))
        scan = inspect_media(movie, scan=True, holds=['0-3'])['scan']
        self.assertEqual(scan['freeze'], [])
        self.assertEqual(len(scan['low_motion']), 1)
        item = scan['low_motion'][0]
        self.assertLessEqual(item['start_seconds'], .3)
        self.assertGreaterEqual(item['end_seconds'], 2.5)
        self.assertLessEqual(item['end_seconds'], 3.05)
        self.assertTrue(item['intended'])
        pace = scan['pace']
        self.assertEqual(len(pace['cuts']), 1)
        self.assertAlmostEqual(pace['cuts'][0], 3, delta=.15)
        self.assertEqual(pace['shot_count'], 2)
        self.assertAlmostEqual(pace['longest_shot_seconds'], 3, delta=.15)
        self.assertGreater(pace['low_motion_share'], .4)
        self.assertLess(pace['low_motion_share'], .75)
        self.assertEqual(scan['thresholds']['low_motion_seconds'], 1.5)

    def test_scan_without_audio(self):
        movie = self.root / 'silent.mp4'
        ffmpeg('-f', 'lavfi', '-i', 'testsrc=s=160x90:r=10:d=2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(movie))
        scan = inspect_media(movie, scan=True)['scan']
        self.assertEqual((scan['freeze'], scan['black'], scan['silence']), ([], [], None))


class LineBreakTests(unittest.TestCase):
    class Draw:
        def textlength(self, text, font=None):
            return len(text) * 10

    def wrap(self, text, width=40):
        return _lines(self.Draw(), text, None, width)

    def test_closing_punctuation_stays_at_line_end(self):
        self.assertEqual(self.wrap('一二三四，五六'), ['一二三四，', '五六'])

    def test_latin_words_and_numbers_stay_whole(self):
        self.assertEqual(self.wrap('接入API网关'), ['接入', 'API网', '关'])
        self.assertEqual(self.wrap('ab cd ef'), ['ab', 'cd', 'ef'])
        self.assertEqual(self.wrap('ABCDEFG'), ['ABCD', 'EFG'])

    def test_opening_bracket_moves_with_following_text(self):
        self.assertEqual(self.wrap('一二三（四五'), ['一二三', '（四五'])

    def test_explicit_newlines_kept(self):
        self.assertEqual(self.wrap('一二\n三四'), ['一二', '三四'])


if __name__ == '__main__':
    unittest.main()
