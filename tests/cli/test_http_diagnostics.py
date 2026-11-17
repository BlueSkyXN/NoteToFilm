"""Error evidence, outcome and credential handling; entirely offline."""

import io
import json
import os
from pathlib import Path
import socket
import ssl
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from notetofilm_local.adapters import get_adapter
from notetofilm_local.errors import NTFError
from notetofilm_local.http_diagnostics import business_error, diagnose_error, redact_text
from notetofilm_local.project import init_project
from notetofilm_local.runner import run
from notetofilm_local.workflow import save_plan
from test_company_protocols import MockHTTP, route


class DiagnosticTests(unittest.TestCase):
    def test_codex_account_model_rejection_is_not_an_image_shape_error(self):
        message="The 'gpt-image-2.5' model is not supported when using Codex with a ChatGPT account."
        result=diagnose_error(status=400,body={"error":{"type":"invalid_request_error","message":message}})
        self.assertEqual(result["category"],"model_unavailable")
        self.assertEqual(result["submission_outcome"],"rejected")
        shape=diagnose_error(status=400,body={"error":{"type":"invalid_request_error","message":"Invalid type for images[0]: expected an object, but got a string"}})
        self.assertEqual(shape["category"],"invalid_request")

    def test_auth_pool_503_retains_inner_model_rejection_and_unknown_outcome(self):
        message="auth_unavailable: no auth available; last upstream error: The 'gpt-image-2.5' model is not supported when using Codex with a ChatGPT account."
        result=diagnose_error(status=503,body={"error":{"code":"internal_server_error","message":message}},headers={"Retry-After":"42572"})
        self.assertEqual(result["category"],"model_unavailable")
        self.assertEqual(result["http_status"],503)
        self.assertEqual(result["submission_outcome"],"unknown")
        self.assertEqual(result["retry_after_seconds"],42572)
        self.assertFalse(result["automatic_retry"])

    def test_http_categories_and_post_outcomes(self):
        cases = [(401, "authentication"), (403, "permission"), (402, "quota"), (429, "rate_limit"),
                 (400, "invalid_request"), (422, "invalid_request"), (413, "invalid_request"),
                 (404, "resource_not_found"), (405, "unsupported_operation"), (415, "unsupported_operation"),
                 (500, "upstream_failure"), (502, "upstream_failure"), (503, "upstream_failure"),
                 (504, "request_timeout"), (408, "request_timeout"), (307, "redirect")]
        for status, category in cases:
            with self.subTest(status=status):
                result = diagnose_error(status=status)
                self.assertEqual(result["category"], category)
                expected = "unknown" if status >= 500 or status in (408, 307) else "rejected"
                self.assertEqual(result["submission_outcome"], expected)
                self.assertFalse(result["automatic_retry"])

    def test_upstream_404_keeps_evidence_without_claiming_a_root_cause(self):
        result = diagnose_error(status=404, body={"error": {"code": "404", "type": "upstream_error", "message": "Resource not found"}},
                                headers={"X-Request-Id": "req-404", "Content-Type": "application/json"})
        self.assertEqual(result["category"], "resource_not_found")
        self.assertEqual(result["reported_layer"], "upstream_reported_by_gateway")
        self.assertEqual(result["request_id"], "req-404")
        self.assertEqual(result["error"]["message"], "Resource not found")
        self.assertFalse(result["root_cause_confirmed"])
        self.assertNotIn("reported_resource", result)

    def test_html_404_has_unknown_layer_and_a_bounded_excerpt(self):
        result = diagnose_error(status=404, raw=b"<html><title>404 Not Found</title></html>", headers={"Server": "nginx"})
        self.assertEqual(result["response_format"], "html")
        self.assertEqual(result["reported_layer"], "unknown")
        self.assertEqual(result["category"], "resource_not_found")
        self.assertIn("404 Not Found", result["body_excerpt"])

    def test_newapi_top_level_error_is_recognized_under_http_200(self):
        body = {"code": "InvalidParameter", "message": "Bad resolution", "data": None}
        self.assertTrue(business_error(body))
        result = diagnose_error(status=200, body=body)
        self.assertEqual(result["category"], "invalid_request")
        self.assertEqual(result["submission_outcome"], "rejected")

    def test_wrapped_provider_503_is_unknown_even_with_outer_http_200(self):
        body = {"code": "503", "message": "Upstream unavailable"}
        result = diagnose_error(status=200, body=body)
        self.assertEqual(result["http_status"], 200)
        self.assertEqual(result["reported_error_status"], 503)
        self.assertEqual(result["category"], "upstream_failure")
        self.assertEqual(result["submission_outcome"], "unknown")

    def test_nested_provider_error_in_gateway_message_is_retained(self):
        body = {"error": {"code": "bad_response_status_code", "type": "upstream_error", "message":
                'Provider returned: {"error":{"code":"DeploymentNotFound","message":"Deployment not found"}}'}}
        result = diagnose_error(status=400, body=body)
        self.assertEqual(result["category"], "resource_not_found")
        self.assertEqual(result["reported_resource"], "deployment")
        self.assertEqual(result["nested_error"]["code"], "DeploymentNotFound")
        self.assertFalse(result["root_cause_confirmed"])

    def test_quota_and_content_errors_take_precedence_over_generic_status(self):
        result = diagnose_error(status=429, body={"error": {"code": "insufficient_quota", "message": "quota exceeded"}})
        self.assertEqual(result["category"], "quota")
        result = diagnose_error(status=403, body={"error": {"code": "content_policy_violation"}})
        self.assertEqual(result["category"], "content_rejected")
        result = diagnose_error(status=429, body={"message": "当前余额不足"})
        self.assertEqual(result["category"], "quota")

    def test_retry_after_is_advice_and_does_not_enable_automatic_posts(self):
        result = diagnose_error(status=429, headers={"Retry-After": "17"})
        self.assertEqual(result["retry_after_seconds"], 17)
        self.assertFalse(result["automatic_retry"])
        result = diagnose_error(status=503, method="GET", phase="download")
        self.assertEqual(result["submission_outcome"], "not_applicable")
        self.assertEqual(result["retry_policy"], "resume_existing_task")

    def test_transport_failures_keep_connection_and_submission_outcomes_separate(self):
        cases = [(URLError(socket.gaierror(-2, "fixture DNS error")), "dns_error", "not_sent"),
                 (ConnectionRefusedError("fixture refusal"), "connection_error", "not_sent"),
                 (URLError(ssl.SSLCertVerificationError(1, "fixture cert error")), "tls_error", "not_sent"),
                 (URLError(TimeoutError("fixture timeout")), "request_timeout", "unknown"),
                 (URLError("timed out"), "request_timeout", "unknown"),
                 (ConnectionResetError("fixture reset"), "connection_error", "unknown")]
        for exc, category, outcome in cases:
            with self.subTest(exception=type(exc).__name__, category=category):
                result = diagnose_error(exception=exc)
                self.assertEqual(result["category"], category)
                self.assertEqual(result["submission_outcome"], outcome)
                self.assertFalse(result["automatic_retry"])

    def test_invalid_media_and_local_save_do_not_suggest_new_generation(self):
        result = diagnose_error(status=200, reason="invalid_media", accepted_result=True)
        self.assertEqual(result["submission_outcome"], "result_returned")
        self.assertEqual(result["retry_policy"], "recover_existing_result")
        result = diagnose_error(status=200, phase="output_save", exception=PermissionError(), accepted_result=True)
        self.assertEqual(result["category"], "local_io")
        self.assertEqual(result["submission_outcome"], "result_returned")

    def test_error_with_existing_media_is_a_conflict_not_a_clean_rejection(self):
        result = diagnose_error(status=200, body={"error": {"code": "invalid_request"}, "data": [{"b64_json": "fixture"}]})
        self.assertEqual(result["submission_outcome"], "result_returned")
        self.assertFalse(result["automatic_retry"])

    def test_plain_404_is_distinct_from_explicit_model_unavailable(self):
        self.assertEqual(diagnose_error(status=404)["category"], "resource_not_found")
        result = diagnose_error(status=404, body={"error": {"code": "model_not_found"}})
        self.assertEqual(result["category"], "model_unavailable")

    def test_redaction_covers_headers_embedded_secrets_urls_and_long_payloads(self):
        secret = "fixture-opaque-credential"
        message = f'{secret} Bearer abcdefg; api_key="another-hidden-value" https://storage.example/x?signature=private'
        result = diagnose_error(status=404, body={"error": {"message": message}},
                                headers={"X-Request-Id": "safe-id", "Set-Cookie": "private-cookie", "Authorization": secret},
                                secrets=(secret,))
        output = json.dumps(result)
        for value in (secret, "abcdefg", "another-hidden-value", "signature=private", "private-cookie"):
            self.assertNotIn(value, output)
        self.assertEqual(result["request_id"], "safe-id")
        self.assertNotIn("A" * 256, redact_text("A" * 3000))

    def test_ordinary_success_payload_is_not_a_business_error(self):
        for body in ({"data": [{"b64_json": "fixture"}]}, {"code": 200, "message": "ok", "data": []}, {"code": 0}):
            self.assertFalse(business_error(body))


class AdapterDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"NTF_TEST_TOKEN": "fixture-secret-never-output"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def adapter(self, name, *replies):
        obj = get_adapter(route(name, "image" if name == "openai-images" else "video"))
        obj.opener = MockHTTP(*replies)
        return obj

    def test_transport_404_preserves_request_id_and_safe_body(self):
        raw = json.dumps({"error": {"code": "404", "type": "upstream_error", "message": "Resource not found fixture-secret-never-output"}}).encode()
        error = HTTPError("https://company.example", 404, "not found", {"X-Request-Id": "request-1"}, io.BytesIO(raw))
        adapter = self.adapter("openai-images", error)
        with self.assertRaises(NTFError) as failure:
            adapter.submit({"prompt": "fixture"}, Path("."))
        self.assertEqual(failure.exception.code, "upstream_http")
        diagnostic = failure.exception.details["diagnostic"]
        self.assertEqual(diagnostic["request_id"], "request-1")
        self.assertEqual(diagnostic["category"], "resource_not_found")
        self.assertNotIn("fixture-secret-never-output", json.dumps(failure.exception.as_dict()))
        self.assertEqual(len(adapter.opener.requests), 1)

    def test_image_http200_gateway_error_keeps_diagnostic(self):
        adapter = self.adapter("openai-images", {"code": "InvalidParameter", "message": "Bad size"})
        result = adapter.submit({"prompt": "fixture"}, Path("."))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["details"]["diagnostic"]["category"], "invalid_request")

    def test_image_wrapped_503_and_bad_json_are_unknown_without_resubmit(self):
        for reply in ({"error": {"code": "503", "message": "Unavailable"}}, b"<html>proxy response</html>"):
            adapter = self.adapter("openai-images", reply)
            with self.assertRaises(NTFError) as failure:
                adapter.submit({"prompt": "fixture"}, Path("."))
            self.assertEqual(failure.exception.code, "submission_unknown")
            self.assertFalse(failure.exception.details["diagnostic"]["automatic_retry"])
            self.assertEqual(len(adapter.opener.requests), 1)

    def test_video_error_without_handle_is_unknown_but_existing_handle_is_resumed(self):
        adapter = self.adapter("newapi-video", {"code": "503", "message": "Unavailable"})
        with self.assertRaises(NTFError) as failure:
            adapter.submit({"prompt": "fixture"}, Path("."))
        self.assertEqual(failure.exception.code, "submission_unknown")
        adapter = self.adapter("newapi-video", {"id": "accepted-task", "status": "queued", "error": {"code": "503"}},
                               {"id": "accepted-task", "status": "completed"})
        result = adapter.submit({"prompt": "fixture"}, Path("."))
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["job"]["remote_id"], "accepted-task")
        self.assertEqual(adapter.poll(result["job"])["status"], "succeeded")
        self.assertEqual([x.get_method() for x in adapter.opener.requests], ["POST", "GET"])

    def test_runner_persists_business_diagnostic_at_the_documented_location(self):
        with tempfile.TemporaryDirectory() as directory:
            project = init_project(Path(directory) / "project")
            save_plan(project, {"actions": [{"id": "image.fixture", "kind": "image", "needs": [], "request": {"prompt": "fixture"}}]})
            configured = route("openai-images", "image")
            config = {"routes": {"fixture": configured}, "connections": {}, "defaults": {"image_route": "fixture"}}
            adapter = self.adapter("openai-images", {"error": {"code": "invalid_request", "message": "Bad size"}})
            with patch("notetofilm_local.adapters.get_adapter", return_value=adapter):
                result = run(project, config)
                diagnostic = result["actions"][0]["error"]["details"]["diagnostic"]
                self.assertEqual(diagnostic["category"], "invalid_request")
                self.assertEqual(project.state["actions"]["image.fixture"]["error"]["details"]["diagnostic"], diagnostic)
                run(project, config)
            self.assertEqual(len(adapter.opener.requests), 1)


if __name__ == "__main__":
    unittest.main()
