"""Mock Edge service events plus a real MP3 fixture; no network synthesis."""

import json
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))
from notetofilm_local.adapters.edge_tts import synthesize
from notetofilm_local.errors import NTFError
from notetofilm_local.media import read_subtitles


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and ffprobe required")
class EdgeAudioTests(unittest.TestCase):
    def test_real_audio_metadata_and_boundary_times_are_preserved(self):
        with tempfile.TemporaryDirectory(prefix="ntf-audio-test-") as tmp:
            root = Path(tmp)
            fixture = root / "tone.mp3"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.8",
                            "-c:a", "libmp3lame", str(fixture)], check=True)
            audio = fixture.read_bytes()
            class Communicate:
                def __init__(self, text, voice, rate, volume, pitch, boundary=None):
                    self.text = text
                async def stream(self):
                    yield {"type": "SentenceBoundary", "offset": 1000000, "duration": 4000000,
                           "text": "FIXTURE boundary"}
                    yield {"type": "audio", "data": audio}
            fake = types.SimpleNamespace(__version__="fixture", Communicate=Communicate)
            with patch("notetofilm_local.adapters.edge_tts._load_edge_tts", return_value=fake):
                result = synthesize("Fixture only", root / "generated")
            cues = read_subtitles(result["subtitles_path"])
            self.assertEqual(cues[0]["start_seconds"], 0.1)
            self.assertEqual(cues[0]["end_seconds"], 0.5)
            self.assertGreater(result["duration_seconds"], 0.79)
            boundaries = json.loads(Path(result["boundaries_path"]).read_text())
            self.assertEqual(boundaries[0]["offset"], 1000000)
            self.assertEqual(Path(result["audio_path"]).read_bytes(), audio)

    def test_word_boundaries_become_short_punctuated_cues(self):
        from notetofilm_local.adapters.edge_tts import _boundary_cues, _subtitles_with_source
        spoken = "清晨，纸船缓缓漂过木桥：让 Pip 在岸边画一颗星。"
        tokens = ["清晨", "纸船", "缓缓", "漂过", "木桥", "让", "Pip", "在", "岸边", "画", "一颗", "星"]
        events = [{"type": "WordBoundary", "offset": i * 5_000_000, "duration": 3_000_000, "text": token}
                  for i, token in enumerate(tokens)]
        cues, source = _subtitles_with_source(events, spoken)
        self.assertEqual(source, "spoken text aligned to service word boundaries")
        self.assertEqual([c["text"] for c in cues], ["清晨，纸船缓缓漂过木桥：", "让 Pip 在岸边画一颗星。"])
        self.assertEqual(cues[0]["start_seconds"], 0)
        self.assertEqual(cues[0]["end_seconds"], 2.5)
        self.assertAlmostEqual(cues[1]["end_seconds"], 5.8)
        # Words that cannot be matched in order fall back to service text without punctuation recovery.
        fallback, source = _subtitles_with_source(events, "完全不同的文本")
        self.assertTrue(fallback and "，" not in fallback[0]["text"])
        self.assertEqual(source, "service boundary text")
        incomplete, source = _subtitles_with_source(events[:1], "清晨。纸船已经出发。")
        self.assertEqual([cue["text"] for cue in incomplete], ["清晨"])
        self.assertEqual(source, "service boundary text")
        self.assertEqual(_boundary_cues(events[:1], "清晨。纸船已经出发。"), incomplete)

    def test_overlong_clause_breaks_at_last_mark_instead_of_mid_phrase(self):
        from notetofilm_local.adapters.edge_tts import _subtitles_with_source
        def cues_for(spoken, tokens):
            events = [{"type": "WordBoundary", "offset": i * 3_000_000, "duration": 2_000_000, "text": token}
                      for i, token in enumerate(tokens)]
            return [c["text"] for c in _subtitles_with_source(events, spoken)[0]]
        # The first comma comes too early to end a cue; the overflow goes back to the last enumeration mark.
        self.assertEqual(
            cues_for("做退款功能，先定谁能退、退多少、重复申请怎么算，再定逻辑放在哪个模块。",
                     ["做", "退款", "功能", "先定", "谁", "能", "退", "退", "多少", "重复", "申请", "怎么", "算",
                      "再定", "逻辑", "放在", "哪个", "模块"]),
            ["做退款功能，先定谁能退、退多少、", "重复申请怎么算，", "再定逻辑放在哪个模块。"])
        # Without clause marks, the space after a Latin name is the next best place.
        self.assertEqual(
            cues_for("Planner 也只在你把整件任务交给它的时候才会启动。",
                     ["Planner", "也", "只", "在", "你", "把", "整件", "任务", "交给", "它", "的", "时候", "才", "会", "启动"]),
            ["Planner", "也只在你把整件任务交给它的时候才会启动。"])
        # No mark or space at all: the cue still closes before the word that would overflow it.
        plain = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥天地。"
        self.assertEqual(cues_for(plain, list(plain[:-1])), [plain[:22], plain[22:]])

    def test_provider_error_does_not_expose_query_token(self):
        class Communicate:
            def __init__(self, *args, **kwargs):
                pass
            async def stream(self):
                raise RuntimeError("https://provider.invalid/?secret=never-print-this")
                yield {}
        fake = types.SimpleNamespace(__version__="fixture", Communicate=Communicate)
        with tempfile.TemporaryDirectory(prefix="ntf-audio-fail-") as tmp:
            with patch("notetofilm_local.adapters.edge_tts._load_edge_tts", return_value=fake):
                with self.assertRaises(NTFError) as failure:
                    synthesize("Fixture", Path(tmp) / "audio")
            self.assertNotIn("never-print", json.dumps(failure.exception.as_dict()))
            self.assertFalse((Path(tmp) / "audio/audio.mp3").exists())


if __name__ == "__main__":
    unittest.main()
