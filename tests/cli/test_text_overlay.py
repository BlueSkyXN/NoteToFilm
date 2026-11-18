"""Offline text rendering with real codecs and synthetic media only."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from notetofilm_local.compose import compose
from notetofilm_local.errors import NTFError
from notetofilm_local.media import read_subtitles
from notetofilm_local.text_overlay import prepare_text_renderer, render_support

PLUGIN = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('text_fixture', PLUGIN / 'examples/create_media_fixture.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
FONT = next((str(p) for p in [Path('/System/Library/Fonts/STHeiti Light.ttc'),
    Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'), Path('C:/Windows/Fonts/arial.ttf')] if p.is_file()), None)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class TextOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='ntf-text-tests-')
        cls.root = Path(cls.tmp.name)
        fixture.create_fixture(cls.root, render=False)
        (cls.root / 'captions.srt').write_text('1\n00:00:00,200 --> 00:00:00,700\nFIXTURE caption\n\n')
        cls.manifest = {'output': {'width':320, 'height':180, 'fps':10, 'subtitles_mode':'burn',
            'subtitle_renderer':'pillow', 'subtitle_font_file':FONT, 'subtitle_font_size':20},
            'scenes':[{'id':'fixture', 'duration_seconds':1.2,
                'visuals':[{'path':'assets/fixture-image.png'}], 'audio_policy':'edge_tts',
                'audio':{'path':'assets/fixture-tone-a.wav'}, 'subtitles_path':'captions.srt',
                'text_overlays':[{'text':'FIXTURE label','start_seconds':.8,'end_seconds':1.1,'position':'top-left'}]}]}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_real_filter_probe(self):
        support = render_support()
        self.assertIsInstance(support['ffmpeg_subtitles'], bool)
        self.assertTrue(support['ffmpeg_overlay'])

    def test_missing_libass_stops_before_scene_encoding(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['output']['subtitle_renderer'] = 'libass'
        manifest['scenes'][0].pop('text_overlays')
        with patch('notetofilm_local.text_overlay.render_support', return_value={'ffmpeg_subtitles':False}), patch('notetofilm_local.compose._render_scene') as render:
            with self.assertRaises(NTFError) as failure:
                compose(self.root, manifest, self.root/'missing-filter')
        self.assertEqual(failure.exception.code, 'subtitle_filter_missing')
        self.assertEqual(json.loads((self.root/'missing-filter/timeline.json').read_text())['status'], 'failed')
        render.assert_not_called()

    def test_invalid_overlay_window_rejected(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['scenes'][0]['text_overlays'][0]['end_seconds'] = 2
        with self.assertRaises(NTFError) as failure:
            compose(self.root, manifest, self.root/'overflow', render=False)
        self.assertEqual(failure.exception.code, 'overlay_out_of_range')

    @unittest.skipUnless(importlib.util.find_spec('PIL') and FONT, 'Pillow and font required')
    def test_font_index_selects_collection_face_and_is_validated(self):
        from notetofilm_local.text_overlay import _font
        from notetofilm_local.compose import compose
        settings = {'subtitle_font_file': FONT, 'subtitle_font_size': 13, 'height': 720}
        with patch('PIL.ImageFont.truetype', return_value='face') as truetype:
            _font(self.root, dict(settings, subtitle_font_index=2))
        self.assertEqual(truetype.call_args.kwargs.get('index'), 2)
        with self.assertRaises(NTFError) as missing:
            _font(self.root, dict(settings, subtitle_font_index=999))
        self.assertEqual(missing.exception.code, 'text_font_invalid')
        manifest = {'output': dict(self.manifest['output'], subtitle_font_index=-1), 'scenes': self.manifest['scenes']}
        with self.assertRaises(NTFError) as invalid:
            compose(self.root, manifest, self.root / 'bad-index', render=False)
        self.assertEqual(invalid.exception.code, 'compose_invalid')

    @unittest.skipUnless(importlib.util.find_spec('PIL') and FONT, 'Pillow and font required')
    def test_missing_font_preflight(self):
        settings = dict(self.manifest['output'], subtitle_font_file=None, subtitle_renderer='auto')
        with patch('notetofilm_local.text_overlay.render_support', return_value={'ffmpeg_subtitles':False,'ffmpeg_overlay':True}):
            with self.assertRaises(NTFError) as failure:
                prepare_text_renderer(self.root, settings, [{'text':'fixture'}], [])
        self.assertEqual(failure.exception.code, 'text_font_required')

    @unittest.skipUnless(importlib.util.find_spec('PIL') and FONT, 'Pillow and font required')
    def test_pillow_captions_labels_timing_and_audio_packets(self):
        from PIL import Image, ImageChops, ImageStat
        manifest = copy.deepcopy(self.manifest)
        manifest['output']['subtitle_renderer'] = 'auto'
        with patch('notetofilm_local.text_overlay.render_support', return_value={'ffmpeg_subtitles':False,'ffmpeg_overlay':True}):
            result = compose(self.root, manifest, self.root/'pillow-real')
        timeline = json.loads(Path(result['timeline_path']).read_text())
        self.assertEqual(timeline['output']['selected_text_renderer'], 'pillow')
        cues = read_subtitles(result['subtitles_path'])
        self.assertEqual((cues[0]['start_seconds'],cues[0]['end_seconds']),(.2,.7))
        def frame(t):
            raw = subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-i',result['video_path'],
                '-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],check=True,capture_output=True).stdout
            return Image.frombytes('RGB',(320,180),raw)
        base, caption, label = frame(.1), frame(.4), frame(.9)
        def difference(a,b,box):
            return sum(ImageStat.Stat(ImageChops.difference(a.crop(box),b.crop(box))).mean)/3
        self.assertGreater(difference(base,caption,(0,125,320,180)),.5)
        self.assertGreater(difference(base,label,(0,0,250,65)),.5)
        # Text burn copies composed AAC packets, preserving the existing sound.
        def packets(path):
            return subprocess.run(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0',
                '-c:a','copy','-f','adts','-'],check=True,capture_output=True).stdout
        self.assertEqual(packets(self.root/'pillow-real/video.partial.mp4'),packets(result['video_path']))
        self.assertTrue(result['media']['has_audio'])
        self.assertAlmostEqual(result['duration_seconds'],1.2,delta=.05)


if __name__ == '__main__':
    unittest.main()
