"""网页动画渲染的入口检查；真实浏览器渲染另行验证，这里不依赖 Playwright。"""
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from notetofilm_local.errors import NTFError
from notetofilm_local.project import init_project
from notetofilm_local import web_render
from notetofilm_local.web_render import PageHandler, TEXT_HOOK, _difference, _fingerprint, _merge_spans, _page, analyze_text

ROOT = Path(__file__).resolve().parents[2]
STARTER = ROOT / '.agents/skills/notetofilm-compose/assets/code-animation'


class WebRenderEntryTests(unittest.TestCase):
    def test_readiness_uses_the_open_document_with_unloaded_sibling_scripts(self):
        (self.page_dir / 'alternate.js').write_text('window.READY = true;')
        api = mock.MagicMock()
        with mock.patch.dict(sys.modules, {'playwright.sync_api': api}):
            session = web_render._Session(self.project, self.page_dir / 'index.html',
                                          {'width': 160, 'height': 90, 'fps': 10}, 1, 1)
            try:
                view = session.open()
                view.wait_for_function.assert_called_once_with(web_render.READY, timeout=120000)
            finally:
                session.close()

    def test_render_receives_the_nominal_frame_time(self):
        api = mock.MagicMock()
        with mock.patch.dict(sys.modules, {'playwright.sync_api': api}):
            session = web_render._Session(self.project, self.page_dir / 'index.html',
                                          {'width': 160, 'height': 90, 'fps': 10}, 1, 1)
            try:
                view = session.open()
                session.frame(view, 1.0125, 1.0)   # 子帧围绕 1.0 秒取样
                view.evaluate.assert_called_with(web_render.RENDER, [1.0125, {'time': 1.0, 'fps': 10}])
                session.frame(view, .5)
                view.evaluate.assert_called_with(web_render.RENDER, [.5, {'time': .5, 'fps': 10}])
            finally:
                session.close()

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='ntf-web-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.project = init_project(self.root / 'project')
        self.page_dir = self.project.root / 'animation/s01'
        self.page_dir.mkdir(parents=True)
        (self.page_dir / 'index.html').write_text('<script>window.render=t=>{}</script>')

    def code(self, **kwargs):
        with self.assertRaises(NTFError) as error:
            web_render.web_render(self.project, **kwargs)
        return error.exception.code

    def test_page_failure_while_drawing_a_frame_names_the_time(self):
        api = mock.MagicMock()
        with mock.patch.dict(sys.modules, {'playwright.sync_api': api}):
            session = web_render._Session(self.project, self.page_dir / 'index.html',
                                          {'width': 160, 'height': 90, 'fps': 10}, 1, 1)
            try:
                view = session.open()
                view.evaluate.side_effect = RuntimeError('Page.evaluate: Event')
                with self.assertRaises(NTFError) as error:
                    session.frame(view, 2.5)
            finally:
                session.close()
        self.assertEqual((error.exception.code, error.exception.details['time_seconds']), ('web_page_error', 2.5))

    def test_page_must_live_inside_project(self):
        outside = self.root / 'outside.html'
        outside.write_text('<p>x</p>')
        self.assertEqual(self.code(page=str(outside), scene_id='s01'), 'web_page_invalid')
        empty = self.project.root / 'animation/empty'
        empty.mkdir()
        self.assertEqual(self.code(page='animation/empty', scene_id='s01'), 'web_page_invalid')
        self.assertEqual(_page(self.project, 'animation/s01'), (self.page_dir / 'index.html').resolve())

    def test_parameters_are_checked_before_starting_a_browser(self):
        with mock.patch.object(web_render, '_Session') as session:
            self.assertEqual(self.code(page='animation/s01', scene_id='s01', duration=0), 'web_render_parameters')
            self.assertEqual(self.code(page='animation/s01', scene_id='s01', preview_times=[-1]), 'web_render_parameters')
            self.assertEqual(self.code(page='animation/s01', scene_id='bad id'), 'invalid_id')
            self.assertEqual(self.code(page='animation/s01', scene_id='s01', width=641), 'compose_invalid')
            session.assert_not_called()

    def test_render_options_are_checked_before_starting_a_browser(self):
        with mock.patch.object(web_render, '_Session') as session:
            for options in ({'dpr': 4}, {'subframes': 0}, {'subframes': 9}, {'shutter': 0}, {'grain': 50},
                            {'text_check': True}):
                with self.subTest(options=options):
                    self.assertEqual(self.code(page='animation/s01', scene_id='s01', duration=1, **options), 'web_render_parameters')
            session.assert_not_called()

    def test_scan_and_range_options_are_checked_before_starting_a_browser(self):
        with mock.patch.object(web_render, '_Session') as session:
            for options in ({'text_scan': 0}, {'text_scan': 20}, {'text_scan': True},
                            {'text_scan': .25, 'preview_times': [1]}, {'time_range': '5'}, {'time_range': '4-2'},
                            {'time_range': '1-2', 'preview_times': [1]}, {'time_range': '1-2', 'grain': 8}):
                with self.subTest(options=options):
                    self.assertEqual(self.code(page='animation/s01', scene_id='s01', duration=3, **options), 'web_render_parameters')
            session.assert_not_called()

    def test_scan_spans_merge_consecutive_samples(self):
        hits = {('CUT', 'title'): [[1.0, [0, 0, 1, 1], 'a.png'], [1.25, [0, 0, 1, 1], None], [1.5, [0, 0, 1, 1], None],
                                   [4.0, [0, 0, 1, 1], 'b.png']],
                ('TINY', 'note'): [[2.0, [0, 0, 1, 1], None]]}
        spans = _merge_spans(hits, .25)
        self.assertEqual([(s['type'], s['start_seconds'], s['end_seconds'], s['samples']) for s in spans],
                         [('CUT', 1.0, 1.5, 3), ('TINY', 2.0, 2.0, 1), ('CUT', 4.0, 4.0, 1)])
        self.assertEqual((spans[0]['marked_path'], spans[2]['marked_path']), ('a.png', 'b.png'))

    def fake_session(self, png_for_time=None, boxes_for_time=None, duration=2.0):
        test = self

        class View:
            def evaluate(self, script, args=None):
                if 'window.DUR' in script:
                    return duration
                self.t = args[0]
                return boxes_for_time(args[0]) if boxes_for_time else []

            def screenshot(self, **_):
                return png_for_time(getattr(self, 't', 0))

            def close(self):
                pass

        class Session:
            def __init__(self, project, page, settings, duration, dpr=1, text_check=False):
                self.size = {'width': settings['width'], 'height': settings['height']}
                self.fps = settings['fps']
                self.engine = 'fake'
                test.text_check = text_check

            def open(self):
                return View()

            def check(self):
                pass

            def frame_info(self, t):
                return {'time': t, 'fps': self.fps}

            def evaluate(self, view, script, t, frame_time=None):
                return view.evaluate(script, [t, self.frame_info(t if frame_time is None else frame_time)])

            def frame(self, view, t, frame_time=None):
                view.t = t
                return png_for_time(t)

            def close(self):
                pass
        return Session

    @staticmethod
    def png(color, size=(160, 90)):
        from PIL import Image
        buffer = io.BytesIO()
        Image.new('RGB', size, color).save(buffer, 'PNG')
        return buffer.getvalue()

    def test_text_scan_reports_spans_over_the_film(self):
        box = {'text': 'edge', 'x0': -20, 'y0': 10, 'x1': 60, 'y1': 30, 'size': 5, 'alpha': 1}
        session = self.fake_session(png_for_time=lambda t: self.png((200, 200, 200)),
                                    boxes_for_time=lambda t: [box] if .5 <= t < 1.0 else [])
        with mock.patch.object(web_render, '_Session', session):
            result = web_render.web_render(self.project, 'animation/s01', scene_id='s01', text_scan=.25, width=160, height=90, fps=10)
        self.assertTrue(self.text_check)
        self.assertEqual((result['status'], result['samples'], result['counts']), ('text_scanned', 8, {'CUT': 1}))
        span = result['spans'][0]
        self.assertEqual((span['text'], span['start_seconds'], span['end_seconds'], span['samples']), ('edge', .5, .75, 2))
        self.assertTrue((self.project.root / span['marked_path']).is_file())

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_range_rerenders_only_those_frames_into_the_adopted_video(self):
        output = {'width': 160, 'height': 90, 'fps': 10}
        source = self.root / 'base.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=160x90:r=10:d=2',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], check=True)
        session = self.fake_session(png_for_time=lambda t: self.png((250, 30, 30)))
        with mock.patch.object(web_render, '_Session', session):
            with self.assertRaises(NTFError) as error:
                web_render.web_render(self.project, 'animation/s01', scene_id='s01', time_range='0.5-1', **output)
            self.assertEqual(error.exception.code, 'web_patch_base')
            target = self.project.root / 'assets/videos/base.mp4'
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(source, target)
            base = self.project.register_file(target, 'video', {'type': 'web', 'scene_id': 's01', 'page': 'animation/s01/index.html'}, 'web.s01')
            result = web_render.web_render(self.project, 'animation/s01', scene_id='s01', time_range='0.5-1', **output)
        self.assertEqual((result['status'], result['frames_rendered'], result['base_asset_id']), ('patched', 5, base['id']))
        state = json.loads((self.project.root / 'state.json').read_text())
        self.assertEqual(state['selection']['web.s01'], result['asset_id'])

        def red_share(at):
            raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(at), '-i', str(self.project.root / result['path']),
                                  '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True).stdout
            return raw[0], raw[2]
        self.assertGreater(red_share(.75)[0], 200)   # 范围内是新画的红色
        self.assertGreater(red_share(1.5)[1], 200)   # 范围外保留原来的蓝色

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_range_adds_the_base_grain_to_new_frames_only(self):
        output = {'width': 160, 'height': 90, 'fps': 10}
        target = self.project.root / 'assets/videos/base.mp4'
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=gray:s=160x90:r=10:d=2',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(target)], check=True)
        self.project.register_file(target, 'video', {'type': 'web', 'scene_id': 's01', 'page': 'animation/s01/index.html',
                                                     'grain': 30}, 'web.s01')
        session = self.fake_session(png_for_time=lambda t: self.png((128, 128, 128)))
        with mock.patch.object(web_render, '_Session', session):
            with self.assertRaises(NTFError) as error:
                web_render.web_render(self.project, 'animation/s01', scene_id='s01', time_range='0.5-1', grain=10, **output)
            self.assertEqual(error.exception.code, 'web_render_parameters')
            result = web_render.web_render(self.project, 'animation/s01', scene_id='s01', time_range='0.5-1', **output)
        state = json.loads((self.project.root / 'state.json').read_text())
        self.assertEqual(state['assets'][result['asset_id']]['source']['grain'], 30)

        def spread(at):
            raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(at), '-i', str(self.project.root / result['path']),
                                  '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], capture_output=True, check=True).stdout
            return max(raw) - min(raw)
        self.assertGreater(spread(.75), 20)   # 新画的帧补上整片的颗粒
        self.assertLess(spread(1.5), 8)       # 拼回的旧帧不再叠一层

    def test_text_analysis_flags_cut_bleed_overlap_and_tiny_text(self):
        box = lambda text, x0, y0, x1, y1, size=30, **extra: {'text': text, 'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1,
                                                             'size': size, 'alpha': 1, **extra}
        issues = analyze_text([
            box('clean title', 100, 100, 400, 140),
            box('runs off', 1200, 100, 1400, 140),
            box('HUGE', -40, 300, 900, 500, size=200),
            box('masked word', -10, 600, 200, 640, clip=True),
            box('label one', 100, 200, 260, 230), box('label two', 120, 205, 280, 235),
            box('footnote', 100, 690, 160, 700, size=9),
            box('faded', 1250, 0, 1400, 40, alpha=.1)], 1280, 720)
        found = {(i['type'], i['text'] if isinstance(i['text'], str) else tuple(i['text'])) for i in issues}
        self.assertEqual(found, {('CUT', 'runs off'), ('BLEED', 'HUGE'), ('OVERLAP', ('label one', 'label two')),
                                 ('TINY', 'footnote')})

    def test_text_wholly_outside_the_frame_is_not_reported(self):
        box = lambda text, x0, x1: {'text': text, 'x0': x0, 'y0': 100, 'x1': x1, 'y1': 130, 'size': 30, 'alpha': 1}
        issues = analyze_text([box('left behind', -400, -200), box('crossing', -50, 120), box('ahead', 1400, 1600)], 1280, 720)
        self.assertEqual([(i['type'], i['text']) for i in issues], [('CUT', 'crossing')])

    def test_text_hook_skips_decorative_text(self):
        hook = TEXT_HOOK.read_text(encoding='utf-8')
        self.assertIn('this.ntfDecorative', hook)

    def test_text_hook_ships_with_the_runtime(self):
        script = TEXT_HOOK.read_text(encoding='utf-8')
        self.assertIn('self.__ntfText', script)
        self.assertIn('fillText', script)

    def test_missing_playwright_reports_how_to_install(self):
        with mock.patch.dict(sys.modules, {'playwright': None, 'playwright.sync_api': None}):
            with self.assertRaises(NTFError) as error:
                web_render.web_render(self.project, 'animation/s01', scene_id='s01', duration=1)
        self.assertEqual(error.exception.code, 'web_dependency_missing')
        self.assertIn('playwright', str(error.exception))

    def test_fingerprint_follows_page_files_and_settings(self):
        page = _page(self.project, 'animation/s01')
        settings = {'width': 640, 'height': 360, 'fps': 24.0, 'fps_expression': '24'}
        first = _fingerprint(page, settings, 2)
        self.assertEqual(first, _fingerprint(page, settings, 2))
        (self.page_dir / 'timing.js').write_text('export const DUR = 2;')
        self.assertNotEqual(first, _fingerprint(page, settings, 2))
        self.assertNotEqual(_fingerprint(page, settings, 2), _fingerprint(page, settings, 3))

    def test_pixel_difference_tolerates_small_edge_changes(self):
        from PIL import Image

        def png(color, patch=None):
            image = Image.new('RGB', (100, 100), color)
            if patch:
                image.paste(patch[0], patch[1])
            buffer = io.BytesIO()
            image.save(buffer, 'PNG')
            return buffer.getvalue()
        base = png((200, 200, 200))
        self.assertEqual(_difference(base, base), 0)
        self.assertEqual(_difference(base, png((210, 200, 200))), 0)
        self.assertGreater(_difference(base, png((200, 200, 200), ((0, 0, 0), (0, 0, 10, 10)))), .005)

    def test_module_scripts_get_javascript_type(self):
        self.assertEqual(PageHandler.extensions_map['.js'], 'text/javascript')
        self.assertEqual(PageHandler.extensions_map['.mjs'], 'text/javascript')

    def test_starter_follows_the_render_contract(self):
        page = (STARTER / 'index.html').read_text(encoding='utf-8')
        for marker in ('window.render = t =>', 'window.READY = true', 'window.DUR = DUR', "from './timing.js'"):
            self.assertIn(marker, page)
        helpers = (STARTER / 'motion.js').read_text(encoding='utf-8')
        for name in ('export function spring', 'export function wrapText', 'export function scrubAnimations',
                     'export function renderInfo', 'export const countUp'):
            self.assertIn(name, helpers)
        self.assertNotIn('Math.random()', helpers.replace('no Math.random()', '').replace('没有状态、计时器或 Math.random()', ''))
        kit = (STARTER / 'kit.js').read_text(encoding='utf-8')
        self.assertIn("from './kit.js'", page)
        for name in ('export function base', 'export function faded', 'export function text', 'export function wipeText', 'export function box', 'export function decorative'):
            self.assertIn(name, kit)
        # 只有 base() 把透明度重置为 1，其余绘制都与外层透明度相乘，整组淡出才不会被内层覆盖
        self.assertEqual(kit.count('globalAlpha = '), 1)
        self.assertIn('globalAlpha *=', kit)
        self.assertNotIn('Math.random()', kit)


if __name__ == '__main__':
    unittest.main()
