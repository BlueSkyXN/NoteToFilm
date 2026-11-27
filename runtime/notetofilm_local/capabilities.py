"""Request semantics plus company-declared capability checks, with no model inference."""
from __future__ import annotations

import math
from .errors import NTFError

IMAGE_MODES = {"text_to_image", "reference_to_image"}
VIDEO_MODES = {"text_to_video", "image_to_video", "reference_to_video", "first_last_to_video"}
ALIASES = {"n": "count", "duration": "duration_seconds", "ratio": "aspect_ratio", "format": "output_format"}
META = {"action_id", "scene_id", "route", "kind", "mode", "prompt", "visual_prompt", "video_prompt", "references", "start_frame", "end_frame", "mask", "parameters", "output", "duration_seconds", "model", "selection_slot"}


def request_mode(route: dict, request: dict) -> str:
    if request.get("mode"):
        return request["mode"]
    if route.get("modality") == "image":
        return "reference_to_image" if request.get("references") else "text_to_image"
    if request.get("end_frame"):
        return "first_last_to_video"
    if request.get("start_frame"):
        return "image_to_video"
    return "reference_to_video" if request.get("references") else "text_to_video"


def request_parameters(request: dict, defaults: dict | None = None) -> dict:
    """Merge route defaults with the request; explicit values replace defaults, and two
    different explicit values for the same parameter (parameters, output, top-level
    duration_seconds) are a conflict."""
    def merge(target, items):
        if not isinstance(items, dict):
            raise NTFError("request_invalid", "parameters and output must be objects.")
        for key, value in items.items():
            canonical = ALIASES.get(key, key)
            if canonical in target and target[canonical] != value:
                raise NTFError("parameter_conflict", "The same generation parameter has conflicting values.", {"parameter": canonical})
            target[canonical] = value

    params, explicit = {}, {}
    merge(params, defaults or {})
    merge(explicit, request.get("parameters", {}))
    output = request.get("output", {})
    if not isinstance(output, dict):
        raise NTFError("request_invalid", "output must be an object.")
    output = output.copy()
    if "width" in output or "height" in output:
        if any(type(output.get(k)) is not int or output[k] <= 0 for k in ("width", "height")):
            raise NTFError("request_invalid", "Output width and height must both be positive integers.")
        merge(explicit, {"size": f'{output.pop("width")}x{output.pop("height")}'})
    merge(explicit, output)
    if "duration_seconds" in request:
        merge(explicit, {"duration_seconds": request["duration_seconds"]})
    return {**params, **explicit}


def _value_matches(value, rule: dict) -> bool:
    if not isinstance(rule, dict):
        return False
    expected = rule.get("type")
    types = {"string": str, "integer": int, "number": (int, float), "boolean": bool}
    if expected in types and (not isinstance(value, types[expected]) or (expected in ("integer", "number") and isinstance(value, bool))):
        return False
    if isinstance(value, (int, float)) and (isinstance(value, float) and not math.isfinite(value)):
        return False
    if "enum" in rule and value not in rule["enum"]:
        return False
    if "minimum" in rule and (not isinstance(value, (int, float)) or value < rule["minimum"]):
        return False
    if "maximum" in rule and (not isinstance(value, (int, float)) or value > rule["maximum"]):
        return False
    return True


def _suggest_sizes(width, height, rule) -> list[str]:
    """Nearest sizes that keep the exact aspect ratio and satisfy the rule (one below, one above); falls back to
    rounding each edge when the ratio cannot be kept."""
    multiple, edge = rule.get("multiple_of", 1), rule.get("max_edge")
    low, high = rule.get("min_pixels", 0), rule.get("max_pixels")
    def fits(w, h):
        return (w > 0 and h > 0 and not w % multiple and not h % multiple and (not edge or max(w, h) <= edge)
                and low <= w * h and (high is None or w * h <= high)
                and ("max_ratio" not in rule or max(w, h) / min(w, h) <= rule["max_ratio"]))
    g = math.gcd(width, height)
    rw, rh = width // g, height // g
    step = math.lcm(multiple // math.gcd(multiple, rw), multiple // math.gcd(multiple, rh))
    found = []
    if rw * step <= 4 * 8192:
        target = width / rw
        below = math.floor(target / step) * step
        for m in (below, below + step):
            if m > 0 and fits(rw * m, rh * m):
                found.append(f"{rw * m}x{rh * m}")
    if not found:
        w, h = max(multiple, round(width / multiple) * multiple), max(multiple, round(height / multiple) * multiple)
        if fits(w, h):
            found.append(f"{w}x{h}")
    return found


def _check_custom_size(size, rule) -> None:
    """Apply a route-declared WIDTHxHEIGHT rule (multiple, longest edge, pixel range, aspect ratio)."""
    if not isinstance(rule, dict) or not isinstance(size, str) or size == "auto":
        return
    try:
        width, height = (int(part) for part in size.lower().split("x"))
    except ValueError:
        raise NTFError("unsupported_parameter", "size must be auto or WIDTHxHEIGHT.", {"size": size}) from None
    multiple, edge = rule.get("multiple_of", 1), rule.get("max_edge")
    pixels, ratio = width * height, max(width, height) / max(1, min(width, height))
    problems = []
    if width <= 0 or height <= 0 or width % multiple or height % multiple:
        problems.append(f"both edges must be positive multiples of {multiple}")
    if edge and max(width, height) > edge:
        problems.append(f"longest edge must be at most {edge}")
    if pixels < rule.get("min_pixels", 0) or ("max_pixels" in rule and pixels > rule["max_pixels"]):
        problems.append(f"total pixels must be between {rule.get('min_pixels', 0)} and {rule.get('max_pixels')}")
    if "max_ratio" in rule and ratio > rule["max_ratio"]:
        problems.append(f"aspect ratio must be within 1:{rule['max_ratio']} and {rule['max_ratio']}:1")
    if problems:
        suggested = _suggest_sizes(width, height, rule) if width > 0 and height > 0 else []
        hint = f" Try {' or '.join(suggested)}." if suggested else ""
        raise NTFError("unsupported_parameter", "size is outside the route's custom size rule: " + "; ".join(problems) + "." + hint,
                       {"size": size, "rule": rule, "suggested_sizes": suggested})


def check_request(route: dict, request: dict) -> None:
    if not isinstance(request, dict):
        raise NTFError("request_invalid", "Generation request must be an object.")
    unknown = sorted(set(request) - META)
    if unknown:
        raise NTFError("unsupported_parameter", "Unknown request fields were not sent to the company API.", {"fields": unknown})
    if request.get("model") not in (None, route.get("model")):
        raise NTFError("model_conflict", "Select another route to change models; request.model cannot override the route.")
    if request.get("kind") not in (None, route.get("modality")):
        raise NTFError("route_modality", "Request kind differs from the route modality.")
    mode = request_mode(route, request)
    modes = IMAGE_MODES if route.get("modality") == "image" else VIDEO_MODES
    if mode not in modes:
        raise NTFError("unsupported_mode", "This mode belongs to a different or unimplemented modality.", {"mode": mode})
    prompts = [request[k] for k in ("prompt", "visual_prompt", "video_prompt") if k in request]
    if not prompts or any(not isinstance(p, str) or not p.strip() for p in prompts) or len(set(prompts)) != 1:
        raise NTFError("request_invalid", "Provide one non-empty, unambiguous prompt.")
    refs = request.get("references", [])
    if not isinstance(refs, list):
        raise NTFError("request_invalid", "references must be an ordered list.")
    for i, ref in enumerate(refs, 1):
        if not isinstance(ref, dict) or ref.get("position", i) != i:
            raise NTFError("reference_order", "Reference positions must match their list order; no automatic reordering is performed.")
        if ref.get("role") in {"first_frame", "last_frame", "start_frame", "end_frame"}:
            raise NTFError("reference_role", "Use start_frame/end_frame fields for endpoint frames, not ordinary references.")
    start, end = request.get("start_frame"), request.get("end_frame")
    expected = {
        "text_to_image": (False, False, False), "reference_to_image": (True, False, False),
        "text_to_video": (False, False, False), "image_to_video": (False, True, False),
        "reference_to_video": (True, False, False), "first_last_to_video": (False, True, True),
    }[mode]
    if (bool(refs), bool(start), bool(end)) != expected:
        raise NTFError("mode_inputs", "References and endpoint frames do not match the selected mode; they are not interchangeable.", {"mode": mode})
    mask = request.get("mask")
    if mask is not None and (mode != "reference_to_image" or not isinstance(mask, dict)):
        raise NTFError("mode_inputs", "mask applies to reference_to_image and marks the editable area of the first reference.", {"mode": mode})
    cap = route.get("capabilities", {})
    if not isinstance(cap, dict) or cap.get("status") != "confirmed":
        raise NTFError("capability_unknown", "Company route capabilities are not confirmed; configure them from the company's contract before generation.", {"route": route.get("id")})
    spec = cap.get("modes", {}).get(mode)
    if not isinstance(spec, dict) or spec.get("supported") is not True:
        code = "unsupported_mode" if isinstance(spec, dict) and spec.get("supported") is False else "capability_unknown"
        raise NTFError(code, "The selected company route does not declare this mode available.", {"route": route.get("id"), "mode": mode})
    if refs:
        limit = spec.get("max_reference_images")
        if type(limit) is not int:
            raise NTFError("capability_unknown", "Confirm max_reference_images for this company route.")
        if len(refs) > limit:
            raise NTFError("reference_limit", "The request exceeds the configured company reference limit.", {"requested": len(refs), "maximum": limit})
    if mask is not None and spec.get("supports_mask") is not True:
        raise NTFError("capability_unknown", "Confirm supports_mask for this route before sending a mask.", {"route": route.get("id")})
    params = request_parameters(request, route.get("defaults", {}))
    _check_custom_size(params.get("size"), spec.get("custom_size"))
    rules = spec.get("parameters", {})
    for name, value in params.items():
        if name not in rules:
            raise NTFError("capability_unknown", "A requested parameter is not declared for this company mode.", {"parameter": name, "mode": mode})
        if not _value_matches(value, rules[name]):
            raise NTFError("unsupported_parameter", "A parameter value is outside the configured company capability.", {"parameter": name, "mode": mode})
    missing = [key for key in spec.get("required_parameters", []) if key not in params]
    if missing:
        raise NTFError("parameter_missing", "The company mode requires explicit parameters.", {"parameters": missing})
    for combination in spec.get("constraints", []):
        if all(params.get(k) == v for k, v in combination.get("when", {}).items()):
            for key, allowed in combination.get("require", {}).items():
                if params.get(key) not in allowed:
                    raise NTFError("parameter_combination", "This parameter combination is not supported by the configured company mode.", {"parameter": key, "when": combination.get("when", {})})
