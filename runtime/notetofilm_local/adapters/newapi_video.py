"""New API unified video tasks on an explicitly configured company gateway."""

import base64
import re
from pathlib import Path

from ..errors import NTFError
from ..http_diagnostics import business_error
from .base import BaseAdapter, local_image


class NewAPIVideoAdapter(BaseAdapter):
    protocol = "newapi-video"
    modality = "video"
    PARAMS = {"count", "duration_seconds", "aspect_ratio", "resolution", "generate_audio", "watermark"}

    def _error(self, response, method="POST"):
        error = response.get("error")
        code = error.get("code") if isinstance(error, dict) else response.get("code")
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", code):
            code = "generation_failed"
        diagnostic = self.diagnostic(response, method=method,
                                     reason="task_failed" if response.get("status") == "failed" and not business_error(response) else None,
                                     accepted_task=bool(response.get("id")))
        return {"code": code, "message": diagnostic["summary"], "details": {"diagnostic": diagnostic}}

    def submit(self, request: dict, project_root: Path) -> dict:
        mode, prompt, params = self._prepare(request, self.PARAMS)
        if params.get("count", 1) != 1:
            raise NTFError("unsupported_parameter", "Unified video tasks produce one video per action.")
        payload = {"model": self.route["model"], "prompt": prompt}
        metadata = {}
        for name, value in params.items():
            if name == "duration_seconds":
                payload["seconds"] = value
            elif name != "count":
                metadata["ratio" if name == "aspect_ratio" else name] = value
        inputs = []
        if mode == "reference_to_video":
            inputs = [(ref, "reference_image") for ref in request["references"]]
        elif mode == "image_to_video":
            inputs = [(request["start_frame"], "first_frame")]
        elif mode == "first_last_to_video":
            inputs = [(request["start_frame"], "first_frame"), (request["end_frame"], "last_frame")]
        if inputs:
            content = []
            for ref, role in inputs:
                raw, mime = local_image(ref, project_root, int(self.connection.get("max_input_image_bytes", 30 * 1024 * 1024)))
                content.append({"type": "image_url", "image_url": {
                    "url": f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")}, "role": role})
            metadata["content"] = content
        if metadata:
            payload["metadata"] = metadata
        response = self._json("POST", self.endpoint("submit", "videos"), payload)
        remote_id = response.get("id")
        if not isinstance(remote_id, str) or not remote_id:
            if response.get("error") or response.get("code") not in (None, 0, "0"):
                error = self._error(response)
                if error["details"]["diagnostic"]["submission_outcome"] == "unknown":
                    raise NTFError("submission_unknown", error["message"], error["details"])
                return {"status": "failed", "outputs": [], "error": error}
            raise NTFError("submission_unknown", "Video submission returned no task ID; do not resubmit automatically.")
        job = self._job(remote_id, self.endpoint("poll", "videos/{task_id}", task_id=remote_id))
        try:
            return self._normalize(response, job, method="POST")
        except NTFError as exc:
            # Keep the accepted handle even if optional response fields are malformed.
            return {"status": "submitted", "job": job, "outputs": [], "observation": exc.as_dict()}

    def poll(self, job: dict) -> dict:
        response = self._json("GET", self._poll_url(job))
        if response.get("id") not in (None, job["remote_id"]):
            raise NTFError("job_mismatch", "The query returned a different task ID.")
        return self._normalize(response, job)

    def _normalize(self, response: dict, job: dict, method="GET") -> dict:
        status = response.get("status", "queued")
        result = {"job": job, "outputs": [], "remote_status": status}
        if response.get("error") or response.get("code") not in (None, 0, "0"):
            if method == "POST" and status not in ("failed", "cancelled", "canceled", "expired"):
                return {**result, "status": "submitted", "observation": self._error(response, method)["details"]}
            return {**result, "status": "failed", "error": self._error(response, method)}
        if status in ("queued", "in_progress"):
            return {**result, "status": "submitted"}
        if status in ("failed", "cancelled", "canceled", "expired"):
            return {**result, "status": "failed", "error": self._error(response, method)}
        if status != "completed":
            raise NTFError("upstream_status", "The unified video endpoint returned an unknown task status.")
        content_url = self.endpoint("content", "videos/{task_id}/content", task_id=job["remote_id"])
        return {**result, "status": "succeeded", "outputs": [{"kind": "video", "url": content_url}],
                "model": response.get("model")}
