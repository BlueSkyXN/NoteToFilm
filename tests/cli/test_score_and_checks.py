"""Code-synthesised score (`ntf score`) and the review hints added with it: intended holds, dark-but-not-empty
frames, octave balance and the breath before a drop."""

import hashlib
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))
from notetofilm_local import synth
from notetofilm_local.errors import NTFError
from notetofilm_local.inspection import inspect_media, scan_media
from notetofilm_local.media import probe
from notetofilm_local.project import init_project

SCORE = """
DUR = 3
def score(S):
    S.tempo(120)
    drums = S.bus('drums', gain=0.9)
    music = S.bus('music', gain=0.5, reverb=0.3, highpass=160, duck=0.6)
    for b in range(4):
        drums.add(S.kick(), S.beat(b)); S.duck(S.beat(b), 0.8)
        drums.add(S.hat(), S.beat(b + 0.5), gain=0.5, pan=0.3)
    music.add(S.pad(S.chord('D3', 'm9'), 1.8), 0)
    music.add(S.pluck('A4', 0.5), 0.25)
    music.add(S.mallet('D5', 0.8, material='glock'), 2.2)
    S.gap(1.95, 2.2)
    drums.add(S.impact(size=0.5), 2.2)
"""


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True)


def window_db(path, start, end):
    with wave.open(str(path)) as w:
        rate, channels = w.getframerate(), w.getnchannels()
        w.setpos(int(start * rate))
        data = array('h')
        data.frombytes(w.readframes(int((end - start) * rate)))
    power = sum(v * v for v in data) / max(1, len(data))
    return 10 * math.log10(power / 32768 ** 2) if power else -120.0


class HarmonyTests(unittest.TestCase):
    def test_note_names_chords_scales_and_steps(self):
        self.assertEqual(synth.midi('A4'), 69)
        self.assertEqual(synth.midi('C#4'), 61)
        self.assertEqual(synth.midi('Eb2'), 39)
        self.assertAlmostEqual(synth.hz('A4'), 440)
        self.assertEqual(synth.chord('C4', 'maj7'), [60, 64, 67, 71])
        self.assertEqual(synth.chord('C4', 'maj', 1), [64, 67, 72])
        self.assertEqual([synth.scale('C4', 'gong')(d) for d in range(6)], [60, 62, 64, 67, 69, 72])
        self.assertEqual(synth.steps('x..x | x...'), [0, 0.75, 1.0])
        with self.assertRaises(NTFError):
            synth.midi('H2')
        with self.assertRaises(NTFError):
            synth.chord('C4', 'nope')

    def test_block_reverb_matches_the_sample_recursion(self):
        x = array('f', [1.0] + [0.0] * 50)
        comb = synth._comb(x, 7, 0.5)
        self.assertAlmostEqual(comb[14], 0.25, places=5)
        allpass, y = synth._allpass(x, 5, 0.5), []
        for n in range(len(x)):   # y[n] = −g·x[n] + x[n−D] + g·y[n−D]
            y.append(-0.5 * x[n] + (x[n - 5] if n >= 5 else 0) + (0.5 * y[n - 5] if n >= 5 else 0))
        for a, b in zip(allpass, y):
            self.assertAlmostEqual(a, b, places=5)

    def test_instruments_are_deterministic_and_bounded(self):
        for make in (lambda: synth.kick(), lambda: synth.pluck('E4', 0.3), lambda: synth.noise(0.1, 3)):
            a, b = make(), make()
            self.assertEqual(a.tobytes(), b.tobytes())
            self.assertLess(max(abs(v) for v in a), 4)
        self.assertEqual(set(synth.pad(['C4', 'E4'], 0.2)), {'L', 'R'})


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and ffprobe required")
class ScoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ntf-score-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.project = init_project(self.root / "proj", "score")
        (self.project.root / "animation").mkdir()
        self.file = self.project.root / "animation" / "score.py"
        self.file.write_text(SCORE, encoding="utf-8")

    def test_score_renders_selects_reuses_and_keeps_the_gap_quiet(self):
        first = synth.score_project(self.project, "animation/score.py", select="film.background", stems=True)
        self.assertEqual(first["status"], "rendered")
        self.assertEqual([Path(s).name for s in first["stems"]], ["01-drums.wav", "02-music.wav", "03-reverb.wav"])
        path = self.project.root / first["path"]
        info = probe(path)
        self.assertEqual(info["kind"], "audio")
        self.assertAlmostEqual(info["duration_seconds"], 3, delta=.05)
        self.assertEqual(self.project.state["selection"]["film.background"], first["asset_id"])
        self.assertLess(window_db(path, 2.0, 2.15), window_db(path, 0.2, 1.8) - 30)   # S.gap: a real breath
        reused = synth.score_project(self.project, "animation/score.py", select="film.background")
        self.assertEqual(reused["status"], "reused")
        self.assertEqual(reused["asset_id"], first["asset_id"])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        forced = synth.score_project(self.project, "animation/score.py", force=True)
        self.assertEqual(hashlib.sha256((self.project.root / forced["path"]).read_bytes()).hexdigest(), digest)

    def test_score_errors_name_the_problem(self):
        outside = self.root / "outside.py"
        outside.write_text(SCORE, encoding="utf-8")
        with self.assertRaises(NTFError) as error:
            synth.score_project(self.project, str(outside))
        self.assertEqual(error.exception.code, "score_parameters")
        self.file.write_text("DUR = 2\n", encoding="utf-8")
        with self.assertRaises(NTFError) as error:
            synth.score_project(self.project, "animation/score.py")
        self.assertIn("score(S)", str(error.exception))
        self.file.write_text("DUR = 2\ndef score(S):\n    S.bus('a').add(S.kick(), 0)\n    1 / 0\n", encoding="utf-8")
        with self.assertRaises(NTFError) as error:
            synth.score_project(self.project, "animation/score.py")
        self.assertEqual(error.exception.code, "score_failed")
        self.assertIn("ZeroDivisionError", str(error.exception))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and ffprobe required")
class ReviewHintTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ntf-hints-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_freezes_inside_declared_holds_are_marked_intended(self):
        clip = self.root / "still.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=2", "-f", "lavfi", "-i", "color=gray:s=160x90:r=10:d=2.5",
               "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-pix_fmt", "yuv420p", clip)
        info = probe(clip)
        plain = scan_media(clip, info)
        self.assertTrue(plain["freeze"])
        self.assertNotIn("intended", plain["freeze"][0])
        held = scan_media(clip, info, holds=["2-4.5"])
        self.assertTrue(all(item["intended"] for item in held["freeze"]))
        self.assertFalse(scan_media(clip, info, holds=["0-1"])["freeze"][0]["intended"])
        with self.assertRaises(NTFError):
            scan_media(clip, info, holds=["4-2"])

    def test_dark_frame_with_a_small_bright_mark_is_not_empty(self):
        dark = self.root / "dark.mp4"
        ffmpeg("-f", "lavfi", "-i", "color=black:s=160x90:r=10:d=1",
               "-vf", "drawbox=x=70:y=40:w=10:h=10:color=white:t=fill", "-pix_fmt", "yuv420p", dark)
        empty = self.root / "empty.mp4"
        ffmpeg("-f", "lavfi", "-i", "color=black:s=160x90:r=10:d=1", "-pix_fmt", "yuv420p", empty)
        marked = scan_media(dark, probe(dark))["black"]
        self.assertTrue(marked and marked[0]["has_content"])
        blank = scan_media(empty, probe(empty))["black"]
        self.assertTrue(blank and not blank[0]["has_content"])

    def test_audio_check_reports_octave_balance_drops_and_pictures(self):
        tone = self.root / "tone.wav"
        # a quiet half-beat before 2 s, then a loud hit
        ffmpeg("-f", "lavfi", "-i", "aevalsrc='if(between(t,1.75,2),0,if(gte(t,2),0.8,0.2))*sin(2*PI*120*t)':s=48000:d=3", tone)
        result = inspect_media(tone, audio_check=True, drops=[2.0], output=self.root / "qa")
        balance = result["audio_balance"]
        self.assertEqual(balance["octave_db_re_1k"]["1000"], 0.0)
        self.assertGreater(balance["octave_db_re_1k"]["125"], 10)
        self.assertTrue(any("低频" in note for note in balance["notes"]))
        drop = result["audio_drops"][0]
        self.assertLess(drop["breath_db_vs_bar"], -20)
        self.assertGreater(drop["hit_db_vs_bar"], 6)
        self.assertEqual(drop["notes"], [])
        self.assertEqual(sorted(Path(p).name for p in result["audio_images"]), ["audio_spectrum.png", "audio_wave.png"])
        with self.assertRaises(NTFError):
            inspect_media(tone, drops=[2.0])


if __name__ == "__main__":
    unittest.main()
