"""Review helpers found missing in an end-to-end production: compare boards, digital-silence tagging, usage."""

import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))
from notetofilm_local.errors import NTFError
from notetofilm_local.inspection import scan_media
from notetofilm_local.media import probe, run_media_command


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and ffprobe required")
class ReviewToolTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ntf-review-tools-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_scan_separates_digital_silence_from_quiet_room_tone(self):
        clip = self.root / "pauses.mp4"
        # tone 0–0.6 s, digital zeros 0.6–1.5 s, tone, quiet tone around -57 dBFS 2.1–3.0 s, tone.
        sound = ("if(lt(t,0.6),0.5*sin(2*PI*440*t),if(lt(t,1.5),0,if(lt(t,2.1),0.5*sin(2*PI*440*t),"
                 "if(lt(t,3.0),0.0014*sin(2*PI*440*t),0.5*sin(2*PI*440*t)))))")
        ffmpeg("-f", "lavfi", "-i", "color=c=gray:s=160x90:d=3.6", "-f", "lavfi", "-i", f"aevalsrc='{sound}':s=48000:d=3.6",
               "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", clip)
        found = scan_media(clip, probe(clip), silence_seconds=.5)
        silences = found["silence"]
        self.assertEqual(len(silences), 2, silences)
        self.assertGreater(silences[0]["digital_silence_seconds"], .6)
        self.assertLess(silences[1]["digital_silence_seconds"], .1)
        self.assertEqual(found["thresholds"]["near_silence_db"], -70)
        self.assertEqual(found["thresholds"]["digital_silence_min_seconds"], .001)

    def test_scan_distinguishes_nonzero_audio_and_short_all_channel_dropout(self):
        clip = self.root / "stereo.mkv"
        # One silent channel throughout. The other contains a -80 dBFS tone, then a 100 ms dropout.
        amplitude = "if(lt(t,0.3),0.3,if(lt(t,1.2),0.0001,if(lt(t,1.6),0.3,if(lt(t,2.5),if(between(t,2,2.1),0,0.001),0.3))))"
        ffmpeg("-f", "lavfi", "-i", "color=gray:s=160x90:r=10:d=3", "-f", "lavfi", "-i",
               f"aevalsrc='0|{amplitude}*cos(2*PI*440*t)':s=48000:d=3", "-c:v", "libx264", "-c:a", "pcm_f32le", clip)
        info = probe(clip)
        scan = scan_media(clip, info)
        first, second = scan["silence"]
        self.assertEqual((first["near_silence_seconds"], first["digital_silence_seconds"]), (.9, 0))
        self.assertEqual((second["near_silence_seconds"], second["digital_silence_seconds"]), (0, .1))

        def log_without_filter_instances(*args, **kwargs):
            result = run_media_command(*args, **kwargs)
            if isinstance(result.stderr, str):   # 低运动扫描读原始帧，那一次是字节输出
                result.stderr = re.sub(r'\[silencedetect@\w+ @', '[silencedetect @', result.stderr)
            return result

        # Reproduce the FFmpeg 6 log format on newer builds as well.
        with patch("notetofilm_local.inspection.run_media_command", side_effect=log_without_filter_instances):
            self.assertEqual(scan_media(clip, info)["silence"], scan["silence"])

    def test_compare_board_grid_overlay_and_crop(self):
        from PIL import Image
        from notetofilm_local.compare import compare_board
        a, b = self.root / "a.png", self.root / "b.png"
        Image.new("RGB", (320, 180), (200, 40, 40)).save(a)
        Image.new("RGB", (320, 180), (40, 40, 200)).save(b)
        video = self.root / "v.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=2", "-pix_fmt", "yuv420p", video)

        grid = compare_board([a, b], output=self.root / "grid")
        self.assertTrue(Path(grid["board"]).is_file())
        self.assertEqual([i["times"] for i in grid["inputs"]], [[None], [None]])

        board = compare_board([video, a], output=self.root / "board", at=[0.5, 1.5])
        self.assertEqual(board["inputs"][0]["times"], [0.5, 1.5])
        self.assertEqual(board["inputs"][1]["times"], [None])

        overlay = compare_board([f"{video}@1.0", a], output=self.root / "overlay", overlay=True)
        with Image.open(overlay["board"]) as image:
            self.assertGreater(image.width, 600)

        crop = compare_board([a, b], output=self.root / "crop", crop="0.25,0.25,0.5,0.5")
        self.assertEqual(crop["crop"], (0.25, 0.25, 0.5, 0.5))
        saved = json.loads((self.root / "crop/compare.json").read_text())
        self.assertEqual(saved["crop"], [0.25, 0.25, 0.5, 0.5])

        with self.assertRaises(NTFError) as missing_time:
            compare_board([video], output=self.root / "no-time")
        self.assertEqual(missing_time.exception.code, "compare_parameters")
        with self.assertRaises(NTFError) as reused:
            compare_board([a], output=self.root / "grid")
        self.assertEqual(reused.exception.code, "output_exists")
        with self.assertRaises(NTFError):
            compare_board([a, b], output=self.root / "bad-crop", crop="0.8,0.8,0.5,0.5")

    def test_compare_displays_the_frame_covering_each_time(self):
        from PIL import Image
        from notetofilm_local.compare import compare_board
        video = self.root / "cut.mp4"
        ffmpeg("-f", "lavfi", "-i", "color=red:s=160x90:r=10:d=0.5", "-f", "lavfi", "-i",
               "color=blue:s=160x90:r=10:d=0.5", "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
               "-c:v", "libx264", video)
        moments = [.5, .49, .99, .49]
        board = compare_board([video], output=self.root / "cut", at=moments, cell_width=160)
        self.assertEqual(board["inputs"][0]["times"], moments)
        self.assertEqual(board["inputs"][0]["frame_times"], [.5, .4, .9, .4])
        with Image.open(board["board"]) as image:
            colors = [image.getpixel((170 + i * 166, 40)) for i in range(4)]
        self.assertEqual([r > b for r, _, b in colors], [False, True, False, True])
        for at in (1, 99):
            with self.subTest(at=at), self.assertRaises(NTFError) as error:
                compare_board([f"{video}@{at}"], output=self.root / f"past-{at}")
            self.assertEqual(error.exception.code, "compare_parameters")

    def test_compare_uses_variable_presentation_intervals_from_first_frame(self):
        from notetofilm_local.compare import compare_board
        video = self.root / "variable.mkv"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=s=160x90:r=10:d=1", "-vf",
               "setpts=PTS+2/TB+if(gte(N\\,5)\\,0.7/TB\\,0)", "-fps_mode", "vfr", "-c:v", "libx264", video)
        board = compare_board([video], output=self.root / "variable", at=[.49, .8, 1.19, 1.2])
        self.assertEqual(board["inputs"][0]["frame_times"], [.4, .4, .4, 1.2])

    def test_compare_preserves_geometry_in_grid_and_overlay_and_checks_pixel_crop(self):
        from PIL import Image, ImageDraw
        from notetofilm_local.compare import compare_board
        wide, tall = self.root / "wide.png", self.root / "tall.png"
        Image.new("RGB", (320, 180)).save(wide)
        shape = Image.new("RGB", (180, 320))
        ImageDraw.Draw(shape).ellipse((60, 130, 120, 190), fill="white")
        shape.save(tall)
        for overlay in (False, True):
            with self.subTest(overlay=overlay):
                result = compare_board([wide, tall], output=self.root / f"geometry-{overlay}", overlay=overlay)
                with Image.open(result["board"]) as board:
                    region = (0, 30, 640, 390) if overlay else (332, 6, 652, 186)
                    bounds = board.crop(region).convert("L").point(lambda p: 255 if p > 95 else 0).getbbox()
                    self.assertIsNotNone(bounds)
                    self.assertLessEqual(abs((bounds[2] - bounds[0]) - (bounds[3] - bounds[1])), 2)
        with self.assertRaises(NTFError) as error:
            compare_board([wide], output=self.root / "subpixel", crop="0,0,0.0001,0.5")
        self.assertEqual(error.exception.code, "compare_parameters")

    def test_usage_counts_attempts_media_seconds_and_adoption(self):
        from notetofilm_local.project import Project, init_project
        from notetofilm_local.workflow import usage
        root = self.root / "project"
        init_project(root, "usage fixture")
        state_path = root / "state.json"
        state = json.loads(state_path.read_text())
        (root / "work/a1").mkdir(parents=True)
        (root / "work/a1/route.json").write_text(json.dumps({"id": "video-route", "model": "video-model"}))
        state["attempts"] = {
            "a1": {"id": "a1", "kind": "video", "status": "complete", "outputs": ["v1", "f1"], "route_path": "work/a1/route.json"},
            "a2": {"id": "a2", "kind": "video", "status": "failed", "outputs": [], "route_path": "work/a1/route.json"},
            "a3": {"id": "a3", "kind": "audio", "status": "complete", "outputs": []}}
        state["assets"].update({
            "v1": {"kind": "video", "path": "assets/videos/v1.mp4", "metadata": {"duration_seconds": 4.04, "width": 1280, "height": 720}},
            "f1": {"kind": "image", "path": "assets/videos/f1.jpg", "metadata": {"width": 1280, "height": 720}}})
        state["renders"] = {"r1": {"video_path": "renders/r1/video.mp4"}}
        (root / "renders/r1").mkdir(parents=True)
        (root / "renders/r1/inputs.json").write_text(json.dumps({"manifest": {"scenes": [{"visuals": [{"asset_id": "v1"}]}]}}))
        state_path.write_text(json.dumps(state))
        report = usage(Project(root))
        self.assertEqual(len(report["routes"]), 1)
        row = report["routes"][0]
        self.assertEqual((row["route"], row["attempts"], row["by_status"]), ("video-route", 2, {"complete": 1, "failed": 1}))
        self.assertEqual((row["outputs"], row["used_in_renders"], row["video_seconds"]), (1, 1, 4.04))
        self.assertEqual(row["sizes"], {"1280x720": 1})

    def test_usage_tracks_transport_registration_and_completed_path_references(self):
        from PIL import Image
        from test_company_protocols import MockHTTP, route
        from notetofilm_local.cli import add_request
        from notetofilm_local.project import init_project
        from notetofilm_local.runner import compose_project, run
        from notetofilm_local.workflow import usage
        project = init_project(self.root / "film")
        fixture_route = route("openai-images", "image")
        fixture_route["connection"]["auth"] = {"type": "none"}
        config = {"routes": {"pictures": fixture_route}, "defaults": {"image_route": "pictures"}}
        picture = self.root / "fixture.png"
        Image.new("RGB", (160, 90), "green").save(picture)
        result = {"data": [{"b64_json": base64.b64encode(picture.read_bytes()).decode()}]}
        http = MockHTTP(result, TimeoutError(), {"error": {"code": "bad_request", "message": "invalid input"}})
        with patch("notetofilm_local.adapters.base.build_opener", return_value=http):
            for aid, options in (("invalid", {"output": {"count": 9}}),
                                 ("registered", {"select_index": 1}), ("uncertain", {}), ("rejected", {})):
                add_request(project, {"action_id": aid, "kind": "image", "prompt": "paper boat", **options})
                run(project, config, action_id=aid)
        self.assertEqual(len(http.requests), 3)
        attempts = {a["action_id"]: a for a in project.state["attempts"].values()}
        self.assertFalse(attempts["invalid"]["submission_started"])
        self.assertTrue(attempts["registered"]["submission_started"])
        self.assertEqual(attempts["registered"]["outputs"], [])
        self.assertEqual(len(project.state["assets"]), 1)
        asset = next(iter(project.state["assets"].values()))
        scene = {"id": "s1", "duration_seconds": .2, "audio_policy": "silent", "visuals": [{"asset_id": asset["id"]}]}
        manifest = {"output": {"width": 160, "height": 90, "fps": 10}, "scenes": [scene]}
        planned = compose_project(project, manifest, render=False)
        self.assertIsNone(planned["video_path"])
        row = usage(project)["routes"][0]
        self.assertEqual(row["route"], "pictures")
        self.assertEqual(row["submissions"], {"not_sent": 1, "accepted": 1, "unknown": 1, "rejected": 1})
        self.assertEqual((row["outputs"], row["used_in_renders"]), (1, 0))
        copy_path = project.root / "assets/images/copy.png"
        shutil.copyfile(picture, copy_path)
        scene["visuals"] = [{"path": str(copy_path)}]
        manifest["unused_candidate"] = {"asset_id": asset["id"]}
        compose_project(project, manifest)
        self.assertEqual(usage(project)["routes"][0]["used_in_renders"], 0)
        del manifest["unused_candidate"]
        original_path = project.path(asset["path"])
        Image.new("RGB", (160, 90), "orange").save(original_path)
        scene["visuals"] = [{"path": asset["path"], "sha256": asset["sha256"]}]
        compose_project(project, manifest)
        self.assertEqual(usage(project)["routes"][0]["used_in_renders"], 0)
        shutil.copyfile(picture, original_path)
        scene["visuals"] = [{"path": asset["path"]}]
        compose_project(project, manifest)
        self.assertEqual(usage(project)["routes"][0]["used_in_renders"], 1)
        scene["visuals"] = [{"asset_id": asset["id"]}]
        compose_project(project, manifest)
        cli = Path(__file__).resolve().parents[2] / "scripts/ntf.py"
        status = subprocess.check_output([sys.executable, "-B", cli, "status", project.root, "--usage"], text=True)
        self.assertEqual(json.loads(status)["usage"]["routes"][0]["used_in_renders"], 1)

    def test_usage_preserves_route_history_and_unknown_legacy_evidence(self):
        from notetofilm_local.io import atomic_json
        from notetofilm_local.project import init_project
        from notetofilm_local.workflow import usage
        project = init_project(self.root / "history")
        with project.transaction() as state:
            for tid, kind, model in (("old", "image", "first"), ("new", "image", "second"), ("clip", "video", "second")):
                atomic_json(project.root / "work" / tid / "route.json", {"id": "shared", "model": model})
                state["attempts"][tid] = {"id": tid, "kind": kind, "status": "complete", "outputs": [tid]}
                state["assets"][tid] = {"kind": kind, "metadata": {"width": 160, "height": 90, "duration_seconds": 4}}
            for tid, error in (("local", "parameter_conflict"), ("other", "unclassified_error")):
                state["attempts"][tid] = {"id": tid, "kind": "video", "status": "failed", "error": {"code": error}}
                atomic_json(project.root / "work" / tid / "request.json", {"route": "unresolved"})
        rows = {(r["route"], r["model"], r["kind"]): r for r in usage(project)["routes"]}
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows["shared", "second", "video"]["video_seconds"], 4)
        self.assertEqual(rows["shared", "first", "image"]["outputs"], 1)
        self.assertEqual(rows["unresolved", None, "video"]["submissions"],
                         {"accepted": 0, "unknown": 1, "not_sent": 1, "rejected": 0})


if __name__ == "__main__":
    unittest.main()
