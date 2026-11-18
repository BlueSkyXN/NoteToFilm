"""网页动画渲染的入口检查；真实浏览器渲染另行验证，这里不依赖 Playwright。"""
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from notetofilm_local.errors import NTFError
from notetofilm_local.project import init_project
from notetofilm_local import web_render
from notetofilm_local.web_render import PageHandler, TEXT_HOOK, _difference, _fingerprint, _page, analyze_text

ROOT = Path(__file__).resolve().parents[2]
STARTER = ROOT / '.agents/skills/notetofilm-compose/assets/code-animation'


class WebRenderEntryTests(unittest.TestCase):
    def test_pages_that_assign_ready_wait_for_ready_true(self):
        from notetofilm_local import web_render as wr
        with tempfile.TemporaryDirectory(prefix='ntf-ready-') as tmp:
            page = Path(tmp) / 'index.html'
            page.write_text('<script type="module">import { r } from "./scene.js"; window.render = r;</script>')
            (Path(tmp) / 'scene.js').write_text('export const r = t => {}; // window.READY === true is checked elsewhere\n')
            self.assertFalse(wr._declares_ready(page))
            (Path(tmp) / 'scene.js').write_text('export const r = t => {};\nwindow.READY = false;\n')
            self.assertTrue(wr._declares_ready(page))
        self.assertTrue(wr._declares_ready(STARTER / 'index.html'))
        self.assertIn('window.READY === true', wr.READY_STRICT)
        self.assertNotIn('undefined', wr.READY_STRICT)

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


if __name__ == '__main__':
    unittest.main()
