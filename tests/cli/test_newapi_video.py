"""Unified gateway protocol and recovery checks; no network or paid calls."""

import base64
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from notetofilm_local.adapters import get_adapter
from notetofilm_local.capabilities import check_request
from notetofilm_local.config import default_config, load_config, resolve_route
from notetofilm_local.errors import NTFError
from notetofilm_local.project import init_project
from notetofilm_local.runner import run
from notetofilm_local.workflow import save_plan
from test_company_protocols import MockHTTP, PNG, VIDEO_CONTAINER_FIXTURE


ROOT = Path(__file__).resolve().parents[2]


class NewAPIVideoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "a.png").write_bytes(PNG)
        (self.root / "b.png").write_bytes(PNG + b"second")
        self.env = patch.dict(os.environ, {"NTF_UNIAPI_BASE_URL": "https://gateway.example",
                                         "NTF_UNIAPI_API_KEY": "local-test-secret"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.config = load_config(ROOT / "configs/uniapi.example.json")

    def adapter(self, *replies):
        adapter = get_adapter(resolve_route(self.config, None, "video"))
        adapter.opener = MockHTTP(*replies)
        return adapter

    def assert_code(self, code, operation):
        with self.assertRaises(NTFError) as failure:
            operation()
        self.assertEqual(failure.exception.code, code)

    def test_profile_selects_requested_models_and_keeps_evidence_separate(self):
        image = resolve_route(self.config, None, "image")
        video = resolve_route(self.config, None, "video")
        self.assertEqual(image["model"], "gpt-image-2")
        self.assertEqual(video["model"], "doubao-seedance-2-0-260128")
        self.assertEqual(default_config()["defaults"]["image_route"], "company-image-2")
        self.assertEqual(video["capabilities"]["evidence"]["runtime_connectivity"], "not_tested")
        self.assertEqual(video["capabilities"]["evidence"]["service_verified"]["reference_count"], 3)
        self.assertEqual(video["capabilities"]["modes"]["reference_to_video"]["max_reference_images"], 9)

    def test_reference_payload_poll_and_authenticated_content_download(self):
        adapter = self.adapter({"id": "task-1", "status": "queued"},
                               {"id": "task-1", "status": "in_progress"},
                               {"id": "task-1", "status": "completed"}, VIDEO_CONTAINER_FIXTURE)
        request = {"prompt": "keep both subjects", "mode": "reference_to_video",
                   "references": [{"path": "b.png", "position": 1}, {"path": "a.png", "position": 2}]}
        submitted = adapter.submit(request, self.root)
        sent = adapter.opener.requests[0]
        body = json.loads(sent.data)
        self.assertEqual(sent.full_url, "https://gateway.example/v1/videos")
        self.assertEqual(body["seconds"], 4)
        self.assertNotIn("duration", body)
        self.assertNotIn("content", body)
        self.assertNotIn("count", body["metadata"])
        self.assertEqual(body["metadata"]["ratio"], "16:9")
        self.assertIs(body["metadata"]["generate_audio"], False)
        refs = body["metadata"]["content"]
        self.assertEqual([r["role"] for r in refs], ["reference_image", "reference_image"])
        self.assertEqual(base64.b64decode(refs[0]["image_url"]["url"].split(",", 1)[1]), PNG + b"second")
        self.assertEqual(adapter.poll(submitted["job"])["status"], "submitted")
        completed = adapter.poll(submitted["job"])
        files = adapter.fetch(completed, self.root / "out")
        self.assertEqual(Path(files[0]["path"]).read_bytes(), VIDEO_CONTAINER_FIXTURE)
        self.assertEqual(adapter.opener.requests[-1].full_url, "https://gateway.example/v1/videos/task-1/content")
        self.assertEqual(adapter.opener.requests[-1].get_header("Authorization"), "Bearer local-test-secret")

    def test_first_last_roles_stay_distinct_from_ordinary_references(self):
        adapter = self.adapter({"id": "task-2"})
        adapter.submit({"prompt": "subtle motion", "mode": "first_last_to_video",
                        "start_frame": {"path": "a.png"}, "end_frame": {"path": "b.png"}}, self.root)
        body = json.loads(adapter.opener.requests[0].data)
        self.assertEqual([r["role"] for r in body["metadata"]["content"]], ["first_frame", "last_frame"])

    def test_seedance20_parameter_limits_reject_25_fields_before_submit(self):
        for params in ({"duration_seconds": 16}, {"draft": True}, {"omni_reference_task_type": "edit"},
                       {"output_format": "mov"}):
            adapter = self.adapter()
            with self.assertRaises(NTFError):
                adapter.submit({"prompt": "test", "parameters": params}, self.root)
            self.assertEqual(adapter.opener.requests, [])
        adapter = self.adapter({"id": "task-auto"})
        adapter.submit({"prompt": "test", "parameters": {"duration_seconds": -1}}, self.root)
        self.assertEqual(json.loads(adapter.opener.requests[0].data)["seconds"], -1)

    def test_reference_limit_and_unimplemented_parameters_stop_before_submit(self):
        adapter = self.adapter()
        self.assert_code("reference_limit", lambda: adapter.submit({"prompt": "test", "mode": "reference_to_video",
                         "references": [{"path": "a.png"}] * 10}, self.root))
        adapter.route["capabilities"]["modes"]["text_to_video"]["parameters"]["draft"] = {"type": "boolean"}
        self.assert_code("unsupported_parameter", lambda: adapter.submit({"prompt": "test", "parameters": {"draft": True}}, self.root))
        self.assertEqual(adapter.opener.requests, [])

    def test_declared_25_profile_uses_same_protocol_and_different_limits(self):
        adapter = self.adapter({"id": "task-25"})
        adapter.route = copy.deepcopy(adapter.route)
        adapter.route["model"] = "doubao-seedance-2-5"
        spec = adapter.route["capabilities"]["modes"]["first_last_to_video"]
        spec["parameters"]["duration_seconds"]["enum"] = [-1, *range(4, 31)]
        spec["parameters"]["resolution"]["enum"] = ["480p", "720p", "1080p"]
        spec["constraints"] = [{"when": {}, "require": {"aspect_ratio": ["adaptive"]}}]
        request = {"prompt": "move", "mode": "first_last_to_video", "start_frame": {"path": "a.png"},
                   "end_frame": {"path": "b.png"}, "parameters": {"duration_seconds": 30, "aspect_ratio": "adaptive"}}
        adapter.submit(request, self.root)
        self.assertEqual(json.loads(adapter.opener.requests[0].data)["model"], "doubao-seedance-2-5")
        request["parameters"]["aspect_ratio"] = "16:9"
        self.assert_code("parameter_combination", lambda: check_request(adapter.route, request))

    def test_business_error_and_failed_task_are_not_success(self):
        for reply in ({"code": "InvalidParameter", "message": "Bad parameter; local-test-secret", "data": None},
                      {"error": {"code": "invalid_request", "message": "Bad parameter; local-test-secret"}}):
            adapter = self.adapter(reply)
            result = adapter.submit({"prompt": "test"}, self.root)
            self.assertEqual(result["status"], "failed")
            self.assertNotIn("local-test-secret", json.dumps(result))
            diagnostic = result["error"]["details"]["diagnostic"]
            self.assertEqual(diagnostic["category"], "invalid_request")
            self.assertIn("Bad parameter", diagnostic["error"]["message"])
        adapter = self.adapter({"id": "task-1"}, {"id": "task-1", "status": "failed"})
        submitted = adapter.submit({"prompt": "test"}, self.root)
        self.assertEqual(adapter.poll(submitted["job"])["status"], "failed")

    def test_accepted_task_survives_malformed_status_and_rejects_wrong_poll_id(self):
        adapter = self.adapter({"id": "accepted", "status": {"unexpected": True}}, {"id": "other", "status": "completed"})
        result = adapter.submit({"prompt": "test"}, self.root)
        self.assertEqual(result["job"]["remote_id"], "accepted")
        self.assert_code("job_mismatch", lambda: adapter.poll(result["job"]))

    def test_timeout_is_unknown_and_never_posts_twice(self):
        adapter = self.adapter(URLError("maybe accepted"))
        self.assert_code("submission_unknown", lambda: adapter.submit({"prompt": "test"}, self.root))
        self.assertEqual(len(adapter.opener.requests), 1)

    def test_runner_resumes_original_route_and_refetches_without_post(self):
        project = init_project(self.root / "project")
        save_plan(project, {"actions": [{"id": "video.test", "kind": "video", "needs": [], "request": {"prompt": "test"}}]})
        adapter = self.adapter({"id": "task-resume"}, {"id": "task-resume", "status": "completed"},
                               URLError("download interrupted"), VIDEO_CONTAINER_FIXTURE)
        seen = []
        def factory(route):
            seen.append(route)
            return adapter
        with patch("notetofilm_local.adapters.get_adapter", side_effect=factory):
            self.assertEqual(run(project, self.config)["actions"][0]["status"], "submitted")
            self.assertEqual(run(project, self.config)["actions"][0]["status"], "waiting_download")
            with patch("notetofilm_local.media.probe", return_value={"kind": "video", "duration_seconds": 4.042,
                       "width": 864, "height": 496, "has_audio": False}):
                recovered = run(project, {"routes": {}, "connections": {}})
            self.assertTrue(recovered["complete"])
            self.assertEqual(recovered["asset_count"], 1)
        self.assertEqual([r.get_method() for r in adapter.opener.requests], ["POST", "GET", "GET", "GET"])
        self.assertEqual(seen[-1]["model"], "doubao-seedance-2-0-260128")
        self.assertEqual(seen[-1]["connection"]["base_url"], "https://gateway.example")


if __name__ == "__main__":
    unittest.main()
