"""用真实像素与音频验证剪辑时间和转场，不调用生成模型。"""

import copy
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from notetofilm_local.compose import compose
from notetofilm_local.errors import NTFError


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class VideoEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='ntf-editing-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / 'sequence.mp4'
        args = ['ffmpeg', '-v', 'error', '-nostdin', '-n']
        for color in ('red', 'green', 'blue', 'yellow'):
            args += ['-f', 'lavfi', '-i', f'color=c={color}:s=160x90:r=20:d=1']
        args += ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=4',
                 '-filter_complex', '[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0[v]',
                 '-map', '[v]', '-map', '4:a', '-c:v', 'libx264', '-preset', 'ultrafast',
                 '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-t', '4', str(cls.source)]
        subprocess.run(args, check=True, capture_output=True)

    def setUp(self):
        self.output = self.root / self._testMethodName
        self.manifest = {'output': {'width': 160, 'height': 90, 'fps': 20},
                         'scenes': [{'id': 'clip', 'audio_policy': 'native', 'duration_seconds': 1,
                                     'visuals': [{'path': 'sequence.mp4', 'trim_start': 1,
                                                  'source_duration_seconds': 2, 'speed': 'fit'}]}]}

    def pixel(self, path, seconds):
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(seconds), '-i', str(path),
                              '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                             check=True, capture_output=True).stdout
        return tuple(raw[(45 * 160 + 80) * 3:(45 * 160 + 80) * 3 + 3])

    def test_fit_uses_selected_range_and_preserves_native_pitch(self):
        original = hashlib.sha256(self.source.read_bytes()).hexdigest()
        result = compose(self.root, self.manifest, self.output)
        visual = result['scenes'][0]['visuals'][0]
        self.assertAlmostEqual(result['duration_seconds'], 1, delta=.05)
        self.assertEqual(visual['speed'], 2)
        self.assertEqual(visual['source_used_seconds'], 2)
        self.assertEqual(visual['source_end_seconds'], 3)
        green, blue = self.pixel(result['video_path'], .2), self.pixel(result['video_path'], .7)
        self.assertGreater(green[1], 90); self.assertLess(green[0], 40); self.assertLess(green[2], 40)
        self.assertGreater(blue[2], 180); self.assertLess(blue[0], 40); self.assertLess(blue[1], 40)
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', '0.1', '-i', result['video_path'],
                              '-t', '0.7', '-vn', '-ac', '1', '-ar', '48000', '-f', 's16le', '-'],
                             check=True, capture_output=True).stdout
        samples = struct.unpack('<' + 'h' * (len(raw) // 2), raw)
        crossings = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))
        frequency = crossings / (len(samples) / 48000)
        self.assertAlmostEqual(frequency, 440, delta=15)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), original)

    def test_numeric_speed_derives_output_duration(self):
        self.manifest['scenes'][0].pop('duration_seconds')
        self.manifest['scenes'][0]['visuals'][0]['speed'] = 4
        result = compose(self.root, self.manifest, self.output, render=False)
        self.assertEqual(result['duration_seconds'], .5)
        self.assertEqual(result['scenes'][0]['visuals'][0]['source_used_seconds'], 2)

    def test_fit_without_window_and_bad_ranges_are_rejected(self):
        missing = copy.deepcopy(self.manifest)
        missing['scenes'][0].pop('duration_seconds')
        with self.assertRaises(NTFError) as error:
            compose(self.root, missing, self.output, render=False)
        self.assertEqual(error.exception.code, 'duration_required')
        bad = copy.deepcopy(self.manifest)
        bad['scenes'][0]['visuals'][0]['source_duration_seconds'] = 4
        with self.assertRaises(NTFError) as error:
            compose(self.root, bad, self.output, render=False)
        self.assertEqual(error.exception.code, 'visual_trim_invalid')
        for speed in (0, -1, True, float('nan'), 'unknown'):
            with self.subTest(speed=speed):
                bad = copy.deepcopy(self.manifest)
                bad['scenes'][0]['visuals'][0]['speed'] = speed
                with self.assertRaises(NTFError):
                    compose(self.root, bad, self.output, render=False)

    def test_speed_does_not_implicitly_hold_or_truncate_narration(self):
        self.manifest['scenes'][0]['visuals'][0]['speed'] = 4
        with self.assertRaises(NTFError) as error:
            compose(self.root, self.manifest, self.output, render=False)
        self.assertEqual(error.exception.code, 'visual_too_short')
        scene = self.manifest['scenes'][0]
        scene.update(audio_policy='edge_tts', audio={'path': 'sequence.mp4'})
        with self.assertRaises(NTFError) as error:
            compose(self.root, self.manifest, self.output, render=False)
        self.assertEqual(error.exception.code, 'narration_would_be_truncated')

    def transition_manifest(self, kind='fade', overlap=.4):
        return {'output': {'width': 160, 'height': 90, 'fps': 20}, 'scenes': [
            {'id': 'red', 'audio_policy': 'native', 'duration_seconds': 1,
             'visuals': [{'path': 'sequence.mp4', 'trim_start': 0, 'source_duration_seconds': 1}]},
            {'id': 'blue', 'audio_policy': 'native', 'duration_seconds': 1,
             'visuals': [{'path': 'sequence.mp4', 'trim_start': 2, 'source_duration_seconds': 1}],
             'transition': {'type': kind, 'duration_seconds': overlap}}]}

    def test_fade_has_mixed_pixels_and_correct_subtitle_offsets(self):
        manifest = self.transition_manifest()
        (self.root / 'early.srt').write_text('1\n00:00:00,100 --> 00:00:00,400\nBefore\n')
        (self.root / 'late.srt').write_text('1\n00:00:00,500 --> 00:00:00,900\nAfter\n')
        manifest['scenes'][0]['subtitles_path'] = 'early.srt'
        manifest['scenes'][1]['subtitles_path'] = 'late.srt'
        result = compose(self.root, manifest, self.output)
        self.assertAlmostEqual(result['duration_seconds'], 1.6, delta=.05)
        before = self.pixel(result['video_path'], .3)
        overlap = self.pixel(result['video_path'], .8)
        after = self.pixel(result['video_path'], 1.3)
        self.assertGreater(before[0], 180); self.assertLess(before[2], 40)
        self.assertGreater(overlap[0], 60); self.assertGreater(overlap[2], 60)
        self.assertGreater(after[2], 180); self.assertLess(after[0], 40)
        timeline = json.loads(Path(result['timeline_path']).read_text())
        self.assertAlmostEqual(timeline['scenes'][1]['start_seconds'], .6)
        self.assertAlmostEqual(timeline['subtitles'][1]['start_seconds'], 1.1)
        self.assertAlmostEqual(timeline['subtitles'][1]['end_seconds'], 1.5)

    def test_mixed_wipe_and_cut_keep_total_duration(self):
        manifest = self.transition_manifest('wipeleft', .25)
        manifest['scenes'].append({'id': 'yellow', 'audio_policy': 'silent', 'duration_seconds': 1,
                                   'visuals': [{'path': 'sequence.mp4', 'trim_start': 3, 'source_duration_seconds': 1}]})
        result = compose(self.root, manifest, self.output)
        self.assertAlmostEqual(result['duration_seconds'], 2.75, delta=.05)
        blue = self.pixel(result['video_path'], 1.4)
        yellow = self.pixel(result['video_path'], 2.4)
        self.assertGreater(blue[2], 180); self.assertLess(blue[0], 40)
        self.assertGreater(yellow[0], 180); self.assertGreater(yellow[1], 180); self.assertLess(yellow[2], 40)

    def test_transition_rejects_spoken_overlap_and_allows_explicit_choice(self):
        manifest = self.transition_manifest(overlap=.6)
        for scene in manifest['scenes']:
            scene.update(duration_seconds=4.5, audio_policy='edge_tts', audio={'path': 'sequence.mp4', 'start_seconds': .15})
            scene['visuals'][0]['speed'] = 'fit'
        with self.assertRaises(NTFError) as error:
            compose(self.root, manifest, self.output, render=False)
        self.assertEqual(error.exception.code, 'transition_narration_overlap')
        manifest['scenes'][1]['transition']['allow_narration_overlap'] = True
        result = compose(self.root, manifest, self.output, render=False)
        self.assertAlmostEqual(result['duration_seconds'], 8.4)

    def test_transition_rejects_subtitle_collisions_and_excessive_overlap(self):
        manifest = self.transition_manifest()
        (self.root / 'full.srt').write_text('1\n00:00:00,100 --> 00:00:00,900\nSpoken caption\n')
        for scene in manifest['scenes']:
            scene['subtitles_path'] = 'full.srt'
        with self.assertRaises(NTFError) as error:
            compose(self.root, manifest, self.output, render=False)
        self.assertEqual(error.exception.code, 'transition_subtitle_overlap')
        manifest = self.transition_manifest(overlap=1)
        with self.assertRaises(NTFError) as error:
            compose(self.root, manifest, self.output, render=False)
        self.assertEqual(error.exception.code, 'transition_too_long')
        manifest = self.transition_manifest()
        manifest['scenes'][0]['transition'] = manifest['scenes'][1]['transition']
        with self.assertRaises(NTFError) as error:
            compose(self.root, manifest, self.output, render=False)
        self.assertEqual(error.exception.code, 'transition_invalid')

    def test_transition_rejects_same_position_text_collision(self):
        manifest=self.transition_manifest()
        for scene in manifest['scenes']:
            scene['text_overlays']=[{'text':scene['id'],'start_seconds':0,'end_seconds':1,'position':'top-left'}]
        with self.assertRaises(NTFError) as error:
            compose(self.root,manifest,self.output,render=False)
        self.assertEqual(error.exception.code,'transition_text_overlap')

    def test_measured_timing_and_workflow_keep_transition_windows(self):
        from notetofilm_local.project import init_project
        from notetofilm_local.timing import narration_timing
        from notetofilm_local.workflow import make_plan, action_request
        project=init_project(self.output/'project')
        asset=project.import_asset(self.source)
        scenes=[]
        for sid in ('a','b'):
            scenes.append({'id':sid,'audio_policy':'edge_tts','audio':{'asset_id':asset['id']},
                           'visuals':[{'asset_id':asset['id'],'speed':'fit'}]})
        scenes[1]['transition']={'type':'fade','duration_seconds':.4}
        project.put_storyboard({'scenes':scenes})
        result=narration_timing(project,apply=True,tail_seconds=.5)
        self.assertAlmostEqual(result['planned_total_seconds'],9.6)
        board=project.storyboard
        self.assertAlmostEqual(board['scenes'][1]['planned_window']['start'],4.6)
        plan=make_plan(project)
        action=next(a for a in plan['actions'] if a['kind']=='compose')
        manifest=action_request(project,action)['manifest']
        self.assertEqual(manifest['scenes'][1]['transition']['type'],'fade')


if __name__ == '__main__':
    unittest.main()
