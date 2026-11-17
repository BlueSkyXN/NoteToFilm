"""OpenAI Images wire protocol on an explicitly configured company endpoint."""
from pathlib import Path

from ..errors import NTFError
from ..http_diagnostics import business_error
from .base import BaseAdapter, local_image, multipart


def _png_size(raw: bytes) -> tuple[int, int]:
    return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")


class OpenAIImagesAdapter(BaseAdapter):
    protocol = "openai-images"
    modality = "image"
    PARAMS = {"size", "quality", "count", "output_format", "background", "output_compression", "input_fidelity", "moderation", "user", "safety_identifier"}

    def submit(self, request: dict, project_root: Path) -> dict:
        mode, prompt, params = self._prepare(request, self.PARAMS)
        payload = {"model": self.route["model"], "prompt": prompt}
        payload.update({("n" if k == "count" else k): v for k, v in params.items()})
        if "input_fidelity" in params and mode == "text_to_image":
            raise NTFError("unsupported_parameter", "input_fidelity applies to image editing, not text-only generation.")
        if mode == "reference_to_image":
            limit = int(self.connection.get("max_input_image_bytes", 50 * 1024 * 1024))
            images = [local_image(ref, project_root, limit) for ref in request["references"]]
            files = {}
            if request.get("mask"):
                raw, mime = local_image(request["mask"], project_root, limit)
                if mime != "image/png":
                    raise NTFError("mask_invalid", "The mask must be a PNG whose transparent area marks what to change.")
                first = images[0]
                if first[1] == "image/png" and _png_size(first[0]) != _png_size(raw):
                    raise NTFError("mask_invalid", "The mask must have the same pixel size as the first reference image.",
                                   {"mask": _png_size(raw), "first_reference": _png_size(first[0])})
                files["mask"] = (raw, mime)
            body, content_type = multipart(payload, images, files)
            response = self._json("POST", self.endpoint("edits", "images/edits"), body=body, content_type=content_type)
        else:
            response = self._json("POST", self.endpoint("generations", "images/generations"), payload)
        if business_error(response):
            diagnostic = self.diagnostic(response)
            if diagnostic["submission_outcome"] == "unknown":
                raise NTFError("submission_unknown", diagnostic["summary"], {"diagnostic": diagnostic})
            return {"status": "failed", "error": {"code": "generation_failed", "message": diagnostic["summary"],
                    "details": {"diagnostic": diagnostic}}, "outputs": []}
        data = response.get("data")
        if not isinstance(data, list) or not data:
            raise NTFError("submission_unknown", "Image submit returned no expected media result; do not resubmit automatically.")
        outputs = []
        for item in data:
            if not isinstance(item, dict) or not (item.get("b64_json") or item.get("url")):
                raise NTFError("submission_unknown", "An image response item has neither bytes nor URL; the request was not retried.")
            out = {"kind": "image"}
            if item.get("b64_json"):
                out["base64"] = item["b64_json"]
            else:
                out["url"] = item["url"]
            outputs.append(out)
        return {"status": "succeeded", "outputs": outputs, "model": response.get("model"),
                "requested_count": params.get("count", 1), "returned_count": len(outputs)}
