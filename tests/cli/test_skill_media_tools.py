"""技能辅助工具的本机媒体和 HTTP 行为验证；不调用模型或安装依赖。"""

from __future__ import annotations

from functools import partial
import hashlib
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'runtime'))
from notetofilm_local import review_server as review


class ReviewServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ntf-review-test-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'review'
        self.directory.mkdir()
        self.payload = bytes(range(256)) * 16
        (self.directory / 'film.mp4').write_bytes(self.payload)
        (self.directory / 'review.html').write_text('<video src="film.mp4" controls></video>')
        (self.directory / 'empty.mp4').write_bytes(b'')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(review.ReviewHandler, directory=str(self.directory)))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, method='GET', path='/film.mp4', headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_full_file_and_head(self):
        status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(body, self.payload)
        self.assertEqual(headers['Accept-Ranges'], 'bytes')
        self.assertEqual(headers['Content-Type'], 'video/mp4')
        status, headers, body = self.request('HEAD', headers={'Range': 'bytes=100-199'})
        self.assertEqual(status, 200)
        self.assertEqual(int(headers['Content-Length']), len(self.payload))
        self.assertEqual(body, b'')

    def test_seek_ranges_have_exact_payload_and_lengths(self):
        cases = [('bytes=100-199', 100, 199), ('bytes=-53', len(self.payload) - 53, len(self.payload) - 1),
                 ('bytes=4000-', 4000, len(self.payload) - 1), ('bytes=4000-9999', 4000, len(self.payload) - 1),
                 ('bytes=-99999', 0, len(self.payload) - 1)]
        for value, first, last in cases:
            with self.subTest(range=value):
                status, headers, body = self.request(headers={'Range': value})
                self.assertEqual(status, 206)
                self.assertEqual(headers['Content-Range'], f'bytes {first}-{last}/{len(self.payload)}')
                self.assertEqual(body, self.payload[first:last + 1])
                self.assertEqual(int(headers['Content-Length']), len(body))

    def test_bad_ranges_empty_file_and_if_range_fallback(self):
        for value in ('bytes=99999-', 'bytes=200-100', 'bytes=-0', 'bytes=0-1,4-5', 'bytes=-', 'items=0-3'):
            with self.subTest(range=value):
                status, headers, body = self.request(headers={'Range': value})
                self.assertEqual(status, 416)
                self.assertEqual(headers['Content-Range'], f'bytes */{len(self.payload)}')
                self.assertEqual(body, b'')
        self.assertEqual(self.request(path='/empty.mp4')[0], 200)
        status, headers, body = self.request(path='/empty.mp4', headers={'Range': 'bytes=0-'})
        self.assertEqual((status, headers['Content-Range'], body), (416, 'bytes */0', b''))
        status, _, body = self.request(headers={'Range': 'bytes=10-20', 'If-Range': 'old-validator'})
        self.assertEqual((status, body), (200, self.payload))

    def test_review_entry_without_listing_or_external_symlinks(self):
        self.assertEqual(self.request(path='/')[2], (self.directory / 'review.html').read_bytes())
        (self.directory / 'unlisted').mkdir()
        self.assertEqual(self.request(path='/unlisted/')[0], 404)
        outside = self.directory.parent / 'private.txt'
        outside.write_text('LOCAL_ONLY_TEST_DATA')
        (self.directory / 'link.txt').symlink_to(outside)
        for path in ('/link.txt', '/../private.txt', '/%2e%2e/private.txt'):
            with self.subTest(path=path):
                status, _, body = self.request(path=path)
                self.assertEqual(status, 403)
                self.assertNotIn(b'LOCAL_ONLY_TEST_DATA', body)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), '需要现有 FFmpeg/ffprobe')
class LoudnessToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='ntf-loudness-test-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        cls.source = cls.directory / 'source with spaces.mp4'
        cls.ffmpeg('-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=24', '-f', 'lavfi', '-i',
                   'sine=frequency=440:sample_rate=48000', '-t', '8', '-af', 'volume=0.15',
                   '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                   '-c:a', 'aac', '-b:a', '128k', str(cls.source))

    @classmethod
    def ffmpeg(cls, *args):
        completed = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-n', *args],
                                   capture_output=True, text=True, timeout=30)
        if completed.returncode:
            raise AssertionError(completed.stderr)
        return completed.stdout

    def cli(self, *args):
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/ntf.py'), 'normalize', *map(str, args)],
                                   capture_output=True, text=True, timeout=60)
        result = json.loads(completed.stdout or completed.stderr)
        if 'error' in result:
            result = {'status': 'error', **result['error']}
        return completed.returncode, result

    def test_two_pass_measures_encoded_output_and_preserves_video(self):
        original_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        output, report = self.directory / 'final with spaces.mp4', self.directory / 'loudness.json'
        code, result = self.cli(self.source, '--output', output, '--lufs', '-17',
                                '--true-peak', '-2', '--lra', '11', '--report', report)
        self.assertEqual(code, 0, result)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), original_hash)
        self.assertEqual(json.loads(report.read_text()), result)
        self.assertLess(abs(result['final_measurement']['integrated_lufs'] + 17), 0.6)
        self.assertLessEqual(result['final_measurement']['true_peak_dbtp'], -1.5)
        self.assertGreater(abs(result['source_measurement']['input_i'] + 17), 5)
        packet_hashes = [self.ffmpeg('-i', str(path), '-map', '0:v:0', '-c', 'copy',
                                     '-f', 'hash', '-hash', 'sha256', '-') for path in (self.source, output)]
        self.assertEqual(packet_hashes[0], packet_hashes[1])
        self.ffmpeg('-i', str(output), '-f', 'null', '-')

    def test_refuses_existing_output_source_and_report(self):
        marker = self.directory / 'do-not-overwrite.mp4'
        marker.write_bytes(b'KEEP')
        source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        for path in (self.source, marker):
            with self.subTest(output=path.name):
                code, result = self.cli(self.source, '--output', path)
                self.assertNotEqual(code, 0)
                self.assertEqual(result['status'], 'error')
        output = self.directory / 'unused.mp4'
        code, _ = self.cli(self.source, '--output', output, '--report', marker)
        self.assertNotEqual(code, 0)
        self.assertFalse(output.exists())
        self.assertEqual(marker.read_bytes(), b'KEEP')
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), source_hash)

    def test_missing_audio_fails_without_output(self):
        source, output = self.directory / 'no-audio.mp4', self.directory / 'no-audio-final.mp4'
        self.ffmpeg('-i', str(self.source), '-an', '-c:v', 'copy', str(source))
        code, result = self.cli(source, '--output', output)
        self.assertNotEqual(code, 0)
        self.assertEqual(result['status'], 'error')
        self.assertIn('音轨', result['message'])
        self.assertFalse(output.exists())

    def test_silence_fails_without_output(self):
        source, output = self.directory / 'silent.mp4', self.directory / 'silent-final.mp4'
        self.ffmpeg('-i', str(self.source), '-c:v', 'copy', '-af', 'volume=0', '-c:a', 'aac', str(source))
        code, result = self.cli(source, '--output', output)
        self.assertNotEqual(code, 0)
        self.assertIn('静音', result['message'])
        self.assertFalse(output.exists())

    def test_invalid_targets_fail_before_processing(self):
        for flag, value in (('--lufs', 'nan'), ('--lufs', '-1'), ('--true-peak', '1'), ('--lra', '0')):
            with self.subTest(parameter=flag, value=value):
                output = self.directory / 'invalid.mp4'
                code, result = self.cli(self.source, '--output', output, flag, value)
                self.assertNotEqual(code, 0)
                self.assertEqual(result['status'], 'error')
                self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
