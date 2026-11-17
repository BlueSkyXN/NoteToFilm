"""可切换的内封字幕与双音轨：旁白混音、原声及各自字幕。"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from notetofilm_local.compose import compose
from notetofilm_local.errors import NTFError
from test_text_overlay import FONT


def ffmpeg(*args):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', *args], check=True, capture_output=True)


def streams(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                          'stream=codec_type,codec_name:stream_tags=handler_name:stream_disposition=default',
                          '-of', 'json', str(path)], check=True, capture_output=True, text=True).stdout
    return [(s['codec_type'], s['codec_name'], s.get('tags', {}).get('handler_name'), s['disposition']['default'])
            for s in json.loads(out)['streams']]


def mean_volume(path, track, start, length):
    log = subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-ss', str(start), '-t', str(length), '-i', str(path),
                          '-map', f'0:a:{track}', '-af', 'volumedetect', '-f', 'null', '-'],
                         capture_output=True, text=True).stderr
    return float(log.split('mean_volume:')[1].split('dB')[0])


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class TrackTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='ntf-tracks-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        src = self.root / 'assets/src'
        src.mkdir(parents=True)
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=24:d=3', '-f', 'lavfi', '-i', 'sine=frequency=880:duration=3',
               '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(src / 'clip.mp4'))
        # PCM 固定旁白时长，避免不同 FFmpeg 版本计入 MP3 填充后越过转场边界。
        ffmpeg('-f', 'lavfi', '-i', 'sine=frequency=330:duration=2', '-c:a', 'pcm_s16le', str(src / 'voice.wav'))
        ffmpeg('-f', 'lavfi', '-i', 'color=c=navy:s=320x180', '-frames:v', '1', str(src / 'still.png'))
        (src / 'voice.srt').write_text('1\n00:00:00,100 --> 00:00:01,800\nNarration line\n')
        (src / 'native.srt').write_text('1\n00:00:00,500 --> 00:00:02,000\nNative dialogue\n')
        self.manifest = {
            'output': {'width': 320, 'height': 180, 'fps': 24, 'subtitles_mode': 'embed', 'audio_tracks': 'dual'},
            'scenes': [
                {'id': 's01', 'visuals': [{'path': 'assets/src/still.png'}], 'audio': {'path': 'assets/src/voice.wav'},
                 'audio_policy': 'edge_tts', 'subtitles_path': 'assets/src/voice.srt', 'duration_seconds': 2.5},
                {'id': 's02', 'visuals': [{'path': 'assets/src/clip.mp4', 'kind': 'video', 'duration_seconds': 2.5}],
                 'audio': {'path': 'assets/src/voice.wav'}, 'audio_policy': 'mix',
                 'native_subtitles_path': 'assets/src/native.srt',
                 'transition': {'type': 'fade', 'duration_seconds': 0.5}}]}

    def render(self, manifest, name):
        return Path(compose(self.root, manifest, self.root / name)['mp4_path'])

    def test_dual_audio_and_switchable_subtitles(self):
        result = compose(self.root, self.manifest, self.root / 'out')
        movie = Path(result['mp4_path'])
        self.assertEqual(streams(movie), [
            ('video', 'h264', 'VideoHandler', 1),
            ('audio', 'aac', '旁白混音', 1), ('audio', 'aac', '原声', 0),
            ('subtitle', 'mov_text', '旁白字幕', 1), ('subtitle', 'mov_text', '原声字幕', 0)])
        self.assertLess(mean_volume(movie, 1, .2, 1.5), -80)       # still picture: no original sound
        self.assertGreater(mean_volume(movie, 1, 3.0, 1.5), -40)   # video scene: original sound at full level
        self.assertGreater(mean_volume(movie, 0, .2, 1.5), -40)    # narration mix
        native = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(movie), '-map', '0:s:1', '-f', 'srt', '-'],
                                capture_output=True, text=True, check=True).stdout
        self.assertIn('00:00:02,500 --> 00:00:04,000', native)    # scene 2 starts at 2.0 s after the 0.5 s fade
        self.assertTrue(Path(result['native_subtitles_path']).is_file())
        self.assertEqual(result['audio_tracks'], 'dual')

    @unittest.skipUnless(FONT, 'Pillow font required')
    def test_text_burning_keeps_every_track(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest['output'].update(subtitle_renderer='pillow', subtitle_font_file=str(FONT))
        manifest['scenes'][0]['text_overlays'] = [{'text': 'Label', 'start_seconds': .2, 'end_seconds': 2}]
        kinds = [(kind, name) for kind, _, name, _ in streams(self.render(manifest, 'burned'))]
        self.assertEqual(kinds[1:], [('audio', '旁白混音'), ('audio', '原声'), ('subtitle', '旁白字幕'), ('subtitle', '原声字幕')])

    def test_single_track_default_and_invalid_values(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest['output'].update(subtitles_mode='sidecar', audio_tracks='single')
        layout = [(kind, codec) for kind, codec, _, _ in streams(self.render(manifest, 'single'))]
        self.assertEqual(layout, [('video', 'h264'), ('audio', 'aac')])
        for key, value in (('audio_tracks', 'triple'), ('subtitles_mode', 'soft')):
            bad = json.loads(json.dumps(self.manifest))
            bad['output'][key] = value
            with self.assertRaises(NTFError) as error:
                compose(self.root, bad, self.root / f'bad-{key}', render=False)
            self.assertEqual(error.exception.code, 'compose_invalid')
        late = json.loads(json.dumps(self.manifest))
        (self.root / 'assets/src/late.srt').write_text('1\n00:00:02,000 --> 00:00:03,000\nToo late\n')
        late['scenes'][1]['native_subtitles_path'] = 'assets/src/late.srt'
        with self.assertRaises(NTFError) as error:
            compose(self.root, late, self.root / 'late', render=False)
        self.assertEqual(error.exception.code, 'subtitle_out_of_range')


if __name__ == '__main__':
    unittest.main()
