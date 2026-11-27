"""视频片段加代码动画的成片工具：抽帧、逐词时间表、骨架模块。"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from notetofilm_local.errors import NTFError
from notetofilm_local.frames import extract_frames
from notetofilm_local.project import init_project
from notetofilm_local.timing import export_timing_js

ROOT = Path(__file__).resolve().parents[2]
STARTER = ROOT / '.agents/skills/notetofilm-compose/assets/code-animation'


def ffmpeg(*args):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', *args], check=True, capture_output=True)


class HybridKitTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='ntf-hybrid-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.project = init_project(self.root / 'project')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_frames_are_numbered_from_zero_at_the_requested_rate(self):
        clip = self.root / 'clip.mp4'
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=30:d=2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(clip))
        self.project.import_asset(clip, 'video', 's01.video')
        result = extract_frames(self.project, select='s01.video', output='animation/film/media/s01', fps=12,
                                width=160, height=90)
        folder = self.project.root / 'animation/film/media/s01'
        self.assertEqual(result['frames'], 24)
        self.assertTrue((folder / '000.jpg').is_file())
        self.assertTrue((folder / '023.jpg').is_file())
        from PIL import Image
        self.assertEqual(Image.open(folder / '000.jpg').size, (160, 90))
        with self.assertRaises(NTFError) as error:   # 已有帧的目录不悄悄覆盖
            extract_frames(self.project, select='s01.video', output='animation/film/media/s01')
        self.assertEqual(error.exception.code, 'output_exists')
        again = extract_frames(self.project, select='s01.video', output='animation/film/media/s01', fps=6,
                               width=160, height=90, force=True)
        self.assertEqual(again['frames'], 12)
        self.assertEqual(len(list(folder.glob('*.jpg'))), 12)

    def test_frames_need_exactly_one_source(self):
        with self.assertRaises(NTFError) as error:
            extract_frames(self.project, output='animation/film/media/x')
        self.assertEqual(error.exception.code, 'frames_parameters')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_timing_js_places_words_on_the_film_clock(self):
        audio = self.root / 'a.wav'
        ffmpeg('-f', 'lavfi', '-i', 'sine=frequency=300:duration=1.5', str(audio))
        asset = self.project.import_asset(audio, 'audio', 'b.audio')
        boundaries = self.project.root / 'assets/audio/b-boundaries.json'
        boundaries.write_text(json.dumps([{'type': 'WordBoundary', 'offset': 2_000_000, 'duration': 3_000_000, 'text': '这个'},
                                          {'type': 'WordBoundary', 'offset': 6_000_000, 'duration': 3_000_000, 'text': '问题'}],
                                         ensure_ascii=False), encoding='utf-8')
        state = json.loads((self.project.root / 'state.json').read_text())
        state['assets'][asset['id']]['metadata']['boundaries_path'] = 'assets/audio/b-boundaries.json'
        (self.project.root / 'state.json').write_text(json.dumps(state, ensure_ascii=False))
        self.project.put_storyboard({'schema_version': 1, 'planned_total_seconds': 6, 'scenes': [
            {'id': 'a', 'narration': '', 'planned_window': {'start': 0, 'end': 3}},
            {'id': 'b', 'narration': '这个问题', 'narration_start_seconds': .5, 'planned_window': {'start': 3, 'end': 6}}]})
        from notetofilm_local.project import Project
        result = export_timing_js(Project(self.project.root), 'animation/film/timing.js')
        self.assertEqual((result['scenes'], result['words'], result['scenes_without_words']), (2, 2, []))
        text = (self.project.root / 'animation/film/timing.js').read_text(encoding='utf-8')
        timeline = json.loads(re.search(r'export const TL = (\{.*\});', text).group(1))
        b = timeline['scenes'][1]
        self.assertEqual((b['start'], b['voice']), (3.0, 3.5))
        self.assertEqual(b['words'], [['这个', 3.7], ['问题', 4.1]])
        self.assertIsNone(timeline['scenes'][0]['voice'])
        self.assertIn('export function W(id, word, n = 1)', text)
        self.assertIn('export function P(id, phrase, n = 1)', text)
        with self.assertRaises(NTFError):
            export_timing_js(Project(self.project.root), 'animation/film/timing.txt')

    def test_timing_js_needs_applied_windows(self):
        self.project.put_storyboard({'schema_version': 1, 'scenes': [{'id': 'a', 'narration': ''}]})
        with self.assertRaises(NTFError) as error:
            export_timing_js(self.project, 'animation/film/timing.js')
        self.assertEqual(error.exception.code, 'timing_windows_missing')

    def test_starter_ships_clip_and_transition_modules(self):
        clips = (STARTER / 'clips.js').read_text(encoding='utf-8')
        for name in ('export function clipLibrary', 'export function view', 'export function drawFrame',
                     'export function overlay', 'export function shotAt'):
            self.assertIn(name, clips)
        self.assertIn('frame.time', clips)
        transitions = (STARTER / 'transitions.js').read_text(encoding='utf-8')
        for name in ('export const across', 'export async function whipPan', 'export async function pushThrough',
                     'export async function wipeBy'):
            self.assertIn(name, transitions)
        page = (STARTER / 'hybrid.html').read_text(encoding='utf-8')
        self.assertIn("import { start } from './hybrid.js'", page)
        self.assertIn('window.render = ', (STARTER / 'hybrid.js').read_text(encoding='utf-8'))
        sample = (STARTER / 'film-timing.js').read_text(encoding='utf-8')
        self.assertIn('export function W(', sample)
        from notetofilm_local.timing import _TIMING_JS_HELPERS
        self.assertTrue(sample.endswith(_TIMING_JS_HELPERS), '骨架里的时间表示例要和 timing --js 导出的函数一致')

    def test_phrase_times_start_at_a_word(self):
        from notetofilm_local.timing import _TIMING_JS_HELPERS
        module = ('export const TL = {"dur": 4, "scenes": [{"id": "a", "start": 0, "dur": 4, "voice": 0, "words": '
                  '[["功能", 0.2], ["齐全", 0.6], ["能", 1.0], ["用", 1.2], ["取件", 2.0], ["码", 2.4], ["120 个", 3.0]]}]};\n'
                  + _TIMING_JS_HELPERS)
        self.assertIn('joined.startsWith(want)', module)
        node = shutil.which('node')
        if not node:   # 没有 Node 时只核对导出的函数；装了 Node 的环境（含 CI）实际运行
            return
        script = self.root / 'timing.mjs'
        script.write_text(module + "\nconst r = [P('a', '能'), P('a', '取件码'), P('a', '120'), P('a', '能用')];\n"
                          "let missing = ''; try { P('a', '选表'); } catch (e) { missing = 'thrown'; }\n"
                          "console.log(JSON.stringify([...r, missing]));\n", encoding='utf-8')
        out = subprocess.run([node, str(script)], capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(out), [1.0, 2.0, 3.0, 1.0, 'thrown'])


if __name__ == '__main__':
    unittest.main()
