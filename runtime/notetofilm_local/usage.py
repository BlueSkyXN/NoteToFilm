"""Summarize recorded image/video generation and direct references in completed renders."""
from collections import defaultdict

from .errors import NTFError
from .io import read_json


def _snapshot(project, path):
    try:
        value = read_json(project.path(path))
    except NTFError:
        return {}
    return value if isinstance(value, dict) else {}


def _submission(attempt, outputs):
    if outputs or attempt.get("job") or attempt.get("response_path") or attempt.get("status") in (
            "complete", "submitted", "waiting_download"):
        return "accepted"
    error = attempt.get("error") or {}
    details = error.get("details") or {}
    diagnostic = details.get("diagnostic") or {}
    outcome = diagnostic.get("submission_outcome")
    if outcome in ("not_sent", "rejected", "unknown"):
        return outcome
    if outcome in ("result_returned", "task_accepted"):
        return "accepted"
    code = error.get("code")
    if code == "generation_failed":
        return "rejected"
    if code == "submission_unknown":
        return "unknown"
    # Older attempts have no transport marker. Only attribute known local errors.
    if attempt.get("submission_started") is False or code in (
            "parameter_conflict", "unsupported_parameter", "request_invalid", "unsupported_mode",
            "capability_unknown", "route_missing", "route_modality", "credential_missing"):
        return "not_sent"
    return "unknown"


def _media_references(manifest):
    for scene in manifest.get("scenes", []):
        yield from scene.get("visuals", [])
        yield scene.get("audio")
    yield manifest.get("background_audio")


def _rendered_assets(project, state):
    by_file = defaultdict(set)
    for aid, asset in state["assets"].items():
        if asset.get("sha256"):
            by_file[asset["path"], asset["sha256"]].add(aid)
    used, missing = set(), []
    for rid, record in state.get("renders", {}).items():
        video = record.get("video_path") or record.get("mp4_path")
        if not video or record.get("rendered") is False:
            continue
        output = project.path(video)
        manifest = _snapshot(project, output.parent / "inputs.json").get("manifest")
        if not isinstance(manifest, dict) or not isinstance(manifest.get("scenes"), list):
            missing.append(rid)
            continue
        for ref in _media_references(manifest):
            if not isinstance(ref, dict):
                continue
            if ref.get("asset_id"):
                used.add(ref["asset_id"])
            else:
                matches = by_file.get((ref.get("path"), ref.get("sha256")))
                if matches and len(matches) == 1:
                    used.update(matches)
    return used, missing


def usage(project):
    state = project.state
    used, missing = _rendered_assets(project, state)
    registered = defaultdict(set)
    for aid, asset in state["assets"].items():
        source = asset.get("source", {})
        if source.get("type") == "generation":
            registered[source.get("attempt_id")].add(aid)
    routes = {}
    for tid, attempt in state.get("attempts", {}).items():
        kind = attempt.get("kind")
        if kind not in ("image", "video"):
            continue
        snapshot = _snapshot(project, attempt.get("route_path") or f"work/{tid}/route.json")
        route = snapshot.get("id") or _snapshot(project, f"work/{tid}/request.json").get("route")
        if not isinstance(route, str) or not route:
            route = "unknown"
        model = snapshot.get("model")
        key = route, model, kind
        if key not in routes:
            row = {"route": route, "model": model, "kind": kind, "attempts": 0, "by_status": {},
                   "submissions": dict.fromkeys(("accepted", "rejected", "unknown", "not_sent"), 0),
                   "outputs": 0, "used_in_renders": 0, "sizes": {}}
            if kind == "video":
                row.update(video_seconds=0.0, used_video_seconds=0.0)
            routes[key] = row
        row = routes[key]
        outputs = registered[tid].union(attempt.get("outputs") or [])
        row["attempts"] += 1
        status = attempt.get("status", "unknown")
        row["by_status"][status] = row["by_status"].get(status, 0) + 1
        row["submissions"][_submission(attempt, outputs)] += 1
        for aid in sorted(outputs):
            asset = state["assets"].get(aid, {})
            if asset.get("kind") != kind:
                continue
            meta = asset.get("metadata", {})
            row["outputs"] += 1
            if meta.get("width") and meta.get("height"):
                size = f"{meta['width']}x{meta['height']}"
                row["sizes"][size] = row["sizes"].get(size, 0) + 1
            if aid in used:
                row["used_in_renders"] += 1
            if kind == "video":
                seconds = float(meta.get("duration_seconds") or 0)
                row["video_seconds"] += seconds
                if aid in used:
                    row["used_video_seconds"] += seconds
    for row in routes.values():
        if row["kind"] == "video":
            for field in ("video_seconds", "used_video_seconds"):
                row[field] = round(row[field], 2)
    return {"routes": sorted(routes.values(), key=lambda r: (r["route"], r["model"] or "", r["kind"])),
            "missing_render_inputs": sorted(missing),
            "note": "attempts 计本地尝试，submissions 按远端提交证据分类。outputs 计已登记的同类素材。"
                    "used_in_renders 计各版已编码成片直接引用的不同素材，used_video_seconds 计这些源片的完整时长。"
                    "动画页面中的副本和外部加工后重新导入的文件单独登记。费用以通道账单为准。"}
