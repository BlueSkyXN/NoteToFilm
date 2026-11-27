"""JSON command interface used by both people and the seven Skills."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import platform
import shutil
import sys
import uuid
from pathlib import Path

from . import __version__
from .errors import NTFError
from .io import atomic_json, read_json
from .project import Project, init_project


def parser():
    p = argparse.ArgumentParser(prog="ntf", description="NoteToFilm CLI: local video projects, model routes, media processing and delivery")
    p.add_argument("--version", action="version", version=f"NoteToFilm CLI {__version__}")
    commands = p.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a local project")
    init.add_argument("project")
    init.add_argument("--title", default="Untitled film")
    cfg = commands.add_parser("config-init", help="Write seven unconfigured company model routes")
    cfg.add_argument("file")
    routes = commands.add_parser("routes", help="List configured model routes without calling them")
    routes.add_argument("--config")
    routes.add_argument("--connections-file", help="Bind matching connection values from an external private JSON file")
    info = commands.add_parser("install-info", help="Show runtime and local media dependencies")
    info.add_argument('--require-audio', action='store_true')
    info.add_argument('--require-render', action='store_true')
    info.add_argument('--font-file')
    info.add_argument('--font-index', type=int, default=0, help='Face index inside a TTC/OTC font collection')
    imp = commands.add_parser("import", help="Copy actual media into the project and register it")
    imp.add_argument("project")
    imp.add_argument("file")
    imp.add_argument("--kind", choices=["image", "video", "audio"])
    imp.add_argument("--select")
    board = commands.add_parser("storyboard", help="Validate and save the formal storyboard")
    board.add_argument("project")
    board.add_argument("--file", required=True)
    settings = commands.add_parser("settings", help="Read or update project voice, output and route defaults")
    settings.add_argument("project")
    for name in ("voice", "rate", "volume", "pitch", "image-route", "video-route"):
        settings.add_argument("--" + name)
    settings.add_argument("--width", type=int)
    settings.add_argument("--height", type=int)
    settings.add_argument("--fps")
    settings.add_argument("--subtitles", choices=["sidecar", "burn", "embed", "none"])
    settings.add_argument("--audio-tracks", choices=["single", "dual"])
    settings.add_argument("--subtitle-renderer", choices=["auto", "libass", "pillow"])
    settings.add_argument("--font-file")
    settings.add_argument("--font-index", type=int, help="Face index inside a TTC/OTC font collection (default 0)")
    settings.add_argument("--font-size", type=float)
    settings.add_argument('--loudness-lufs', type=float)
    settings.add_argument('--true-peak-db', type=float)
    settings.add_argument('--no-loudness-normalization', action='store_true')
    settings.add_argument('--background-audio', help='Registered asset ID for background sound')
    settings.add_argument('--no-background-audio', action='store_true')
    settings.add_argument('--background-volume', type=float)
    settings.add_argument('--background-start-seconds', type=float)
    settings.add_argument('--background-trim-start', type=float)
    settings.add_argument('--background-duration', type=float)
    settings.add_argument('--background-fade-in', type=float)
    settings.add_argument('--background-fade-out', type=float)
    settings.add_argument('--background-loop', action=argparse.BooleanOptionalAction, default=None)
    plan = commands.add_parser("plan", help="Build a plan from the storyboard or load a custom DAG")
    plan.add_argument("project")
    plan.add_argument("--file")
    for name in ("ready", "status"):
        command = commands.add_parser(name, help="Inspect project state and current input dependencies")
        command.add_argument("project")
        if name == "status":
            command.add_argument("--usage", action="store_true", help="按路由、模型和媒体类型查看提交状态、登记素材和成片直接引用量")
    run = commands.add_parser("run", help="Execute ready work or resume recorded tasks")
    run.add_argument("project")
    run.add_argument("--action")
    run.add_argument("--config")
    run.add_argument("--connections-file")
    run.add_argument("--wait-seconds", type=float, default=0)
    run.add_argument("--retry", action="store_true", help="Allow a new attempt for failed/unknown/interrupted work")
    run.add_argument("--force", action="store_true", help="Regenerate the explicitly named action")
    run.add_argument("--kind", choices=["image", "video", "audio", "compose", "manual"])
    run.add_argument("--scene", action="append", dest="scene_ids", help="Select a fixed scene ID; repeat for multiple scenes")
    phase = run.add_mutually_exclusive_group()
    phase.add_argument("--poll-only", action="store_true", help="Query or download existing tasks; never create a new attempt")
    phase.add_argument("--submit-only", action="store_true", help="Start ready actions without polling existing tasks")
    run.add_argument("--max-new-actions", type=int, help="Limit newly started actions in this invocation")
    run.add_argument("--stop-on-error", action="store_true", help="Stop this batch after the first failed or uncertain action")
    select = commands.add_parser("select", help="Select one or ordered multiple assets for a slot")
    select.add_argument("project")
    select.add_argument("slot")
    select.add_argument("asset_ids", nargs="+")
    generate = commands.add_parser("generate", help="Add and run a standalone image or video request")
    generate.add_argument("project")
    generate.add_argument("--request", required=True)
    generate.add_argument("--config")
    generate.add_argument("--connections-file")
    generate.add_argument("--wait-seconds", type=float, default=0)
    audio = commands.add_parser("audio", help="Add and synthesize a standalone Edge TTS narration")
    audio.add_argument("project")
    audio.add_argument("--text", required=True)
    audio.add_argument("--speech-text")
    audio.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    audio.add_argument("--rate", default="+0%")
    audio.add_argument("--volume", default="+0%")
    audio.add_argument("--pitch", default="+0Hz")
    audio.add_argument("--action-id")
    audio.add_argument("--select")
    compose = commands.add_parser("compose", help="Compose an explicit mixed-media manifest")
    compose.add_argument("project")
    compose.add_argument("--manifest", required=True)
    compose.add_argument("--plan-only", action="store_true")
    motion = commands.add_parser('motion', help='从参数化图层、关键帧和路径生成项目动效素材')
    motion.add_argument('project')
    motion.add_argument('--manifest', required=True)
    motion.add_argument('--scene', action='append', dest='scene_ids')
    motion.add_argument('--stage', choices=['all','picture','annotate'], default='all')
    motion.add_argument('--select-prefix', default='motion')
    motion_mode = motion.add_mutually_exclusive_group()
    motion_mode.add_argument('--plan-only', action='store_true')
    motion_mode.add_argument('--preview-only', action='store_true')
    motion.add_argument('--preview-time', type=float)
    motion.add_argument('--force', action='store_true', help='重新渲染为新素材，保留已有版本')
    web = commands.add_parser('web-render', help='把提供 render(t) 的网页逐帧渲染为项目视频素材')
    web.add_argument('project')
    web.add_argument('--page', required=True, help='项目内的 .html 文件或含 index.html 的目录')
    web.add_argument('--scene', required=True, dest='scene_id', help='对应的固定镜头 ID')
    web.add_argument('--duration', type=float, help='秒数；省略时读取页面的 window.DUR')
    web.add_argument('--select', help='采用位置，默认 web.<scene>')
    web.add_argument('--width', type=int)
    web.add_argument('--height', type=int)
    web.add_argument('--fps')
    web.add_argument('--preview-time', type=float, action='append', dest='preview_times',
                     help='只输出该时刻的静帧并检查画面是否只由时间决定；可重复')
    web.add_argument('--force', action='store_true', help='重新渲染为新素材，保留已有版本')
    web.add_argument('--dpr', type=float, default=1, help='超采样倍数 1–3，导出时缩回项目画幅')
    web.add_argument('--subframes', type=int, default=1, help='每帧子帧数 1–8，平均得到运动模糊')
    web.add_argument('--shutter', type=float, default=.5, help='子帧覆盖的快门比例 (0, 1]，默认 0.5')
    web.add_argument('--grain', type=float, default=0, help='编码时叠加的颗粒强度 0–40')
    web.add_argument('--text-check', action='store_true', help='预览时检查文字出界、重叠和过小')
    web.add_argument('--text-scan', type=float, metavar='SECONDS', help='按间隔对整片（或 --range）做文字检查，连续时刻并成区间')
    web.add_argument('--range', dest='time_range', metavar='START-END',
                     help='配 --text-scan 时只扫这一段；单独用时只重渲这一段，拼回当前采用的整片')
    score = commands.add_parser('score', help='运行配乐脚本，合成原创配乐与音效并登记为项目音频')
    score.add_argument('project')
    score.add_argument('--file', required=True, help='项目内的 .py 配乐脚本，定义 DUR 与 score(S)')
    score.add_argument('--select', help='采用位置，默认 film.score')
    score.add_argument('--duration', type=float, help='秒数；省略时读取脚本里的 DUR')
    score.add_argument('--stems', action='store_true', help='另存每条总线的分轨，便于排查')
    score.add_argument('--force', action='store_true', help='重新合成为新素材，保留已有版本')
    timing = commands.add_parser("timing", help="Report narration estimates or apply measured shot durations")
    timing.add_argument("project")
    timing.add_argument("--mode", choices=["estimate", "measured"], default="measured")
    timing.add_argument("--scene", action="append", dest="scene_ids")
    timing.add_argument("--lead-seconds", type=float)
    timing.add_argument("--tail-seconds", type=float, default=.6)
    timing.add_argument("--min-seconds", type=int, default=1)
    timing.add_argument("--max-seconds", type=int)
    timing.add_argument("--units-per-second", type=float, help="Override the estimate speed; by default about 4.6 units/s scaled by the narration rate")
    timing.add_argument("--preserve-planned", action="store_true")
    timing.add_argument("--apply", action="store_true", help="Write measured durations and windows to the storyboard; re-plan afterwards")
    timing.add_argument("--js", help="项目内的 .js 文件：导出镜头窗口与逐词时间，供代码动画页面使用（需要先 --apply）")
    inspect = commands.add_parser("inspect", help="Probe actual media, optionally fully decode and export small JPEG frames")
    inspect.add_argument("file")
    inspect.add_argument("--decode", action="store_true")
    inspect.add_argument("--output")
    inspect.add_argument("--frames", type=int, default=3)
    inspect.add_argument("--at-seconds", action="append", type=float)
    inspect.add_argument("--max-width", type=int, default=960)
    inspect.add_argument("--jpeg-quality", type=int, default=80)
    inspect.add_argument('--expect-width', type=int)
    inspect.add_argument('--expect-height', type=int)
    inspect.add_argument('--expect-fps', type=float)
    inspect.add_argument('--expect-duration', type=float)
    inspect.add_argument('--duration-tolerance', type=float, default=.1)
    inspect.add_argument('--expect-audio', choices=['yes','no'])
    inspect.add_argument('--audio-check', action='store_true')
    inspect.add_argument('--min-mean-dbfs', type=float, default=-60)
    inspect.add_argument('--max-peak-dbfs', type=float, default=-.1)
    inspect.add_argument('--expect-loudness-lufs', type=float)
    inspect.add_argument('--loudness-tolerance', type=float, default=1)
    inspect.add_argument('--scan', action='store_true', help='标出冻结、低运动、黑场和静音区间，统计剪点与镜长，供定位查看')
    inspect.add_argument('--freeze-seconds', type=float, default=1.0)
    inspect.add_argument('--silence-seconds', type=float, default=.5)
    inspect.add_argument('--low-motion-seconds', type=float, default=1.5, help='低运动区间的最短秒数，默认 1.5；安静的观察片可放宽')
    inspect.add_argument('--low-motion-level', type=float, default=1.2, help='低运动阈值（缩小灰度画面的平均帧差，0–255），默认 1.2')
    inspect.add_argument('--timeline', help='合成时间表；--scan 结果据此标注镜头 ID')
    inspect.add_argument('--hold', action='append', dest='holds', metavar='START-END',
                         help='有意停留的区间（秒），落在其中的冻结和低运动区间标为 intended；可重复，与 --scan 一起用')
    inspect.add_argument('--drop', action='append', type=float, dest='drops', metavar='SECONDS',
                         help='重拍时刻：量重拍前半拍的凹陷和重拍的抬升；可重复，与 --audio-check 一起用')
    inspect.add_argument('--beat-seconds', type=float, default=.5, help='一拍的秒数，--drop 用它划窗口，默认 0.5')
    frames = commands.add_parser('frames', help='把采用的视频片段抽成代码动画页面读取的帧序列')
    frames.add_argument('project')
    frames.add_argument('--select', help='视频的采用位，例如 s05.video')
    frames.add_argument('--asset', dest='asset_id', help='素材 ID（采用位对应多个素材时用）')
    frames.add_argument('--output', required=True, help='项目内的空目录，例如 animation/film/media/s05')
    frames.add_argument('--fps', type=float, default=24.0, help='抽帧帧率，默认 24（与常见生成视频一致）')
    frames.add_argument('--width', type=int, help='帧宽，默认项目画幅')
    frames.add_argument('--height', type=int, help='帧高，默认项目画幅')
    frames.add_argument('--jpeg-quality', type=int, default=3, help='JPEG 质量 2–31，越小越好，默认 3')
    frames.add_argument('--force', action='store_true', help='目录已有帧时用新素材替换')
    sheet = commands.add_parser('sheet', help='按时间抽帧生成带时间与镜头标注的联系表')
    sheet.add_argument('file')
    sheet.add_argument('--output', required=True)
    sheet.add_argument('--fps', type=float, default=2.0)
    sheet.add_argument('--start', type=float)
    sheet.add_argument('--end', type=float)
    sheet.add_argument('--timeline', help='合成时间表；标注镜头 ID 与字幕，--cuts 据此定位剪点')
    sheet.add_argument('--cuts', action='store_true', help='只看每个剪点或转场前后')
    sheet.add_argument('--cut-padding', type=float, default=.5)
    sheet.add_argument('--cell-width', type=int, default=320)
    sheet.add_argument('--columns', type=int, default=4)
    sheet.add_argument('--max-cells', type=int, default=24)
    sheet.add_argument('--jpeg-quality', type=int, default=80)
    compare = commands.add_parser('compare', help='把多个图片或视频的画面并排、叠合或局部放大，用于挑候选、比方向、核对剪点和查小字')
    compare.add_argument('inputs', nargs='+', help='图片或视频；视频可写 FILE@秒数 只取这一帧')
    compare.add_argument('--output', required=True)
    compare.add_argument('--at', type=float, action='append', help='视频内的显示时刻，可重复；每个视频一行，图上标注实际帧时间')
    compare.add_argument('--overlay', action='store_true', help='把各输入的一帧等权叠合，核对位置是否对齐')
    compare.add_argument('--crop', help='x,y,宽,高（0–1 比例），所有画面裁同一区域放大')
    compare.add_argument('--label', action='append', help='每个输入的标签，按顺序；中文标签需同时给 --font-file')
    compare.add_argument('--font-file')
    compare.add_argument('--cell-width', type=int, default=320)
    compare.add_argument('--columns', type=int, default=4)
    preview = commands.add_parser("preview", help="Export a standalone review page with compressed frames and optional final video")
    preview.add_argument("project")
    preview.add_argument("--output")
    preview.add_argument("--video")
    preview.add_argument("--render")
    preview.add_argument("--timeline", help="Explicit timeline JSON for a postprocessed --video")
    preview.add_argument("--max-width", type=int, default=960)
    preview.add_argument("--jpeg-quality", type=int, default=80)
    normalize = commands.add_parser('normalize', help='双遍校准成片响度，保留源文件与视频码流')
    normalize.add_argument('file')
    normalize.add_argument('--output', required=True)
    normalize.add_argument('--lufs', type=float, default=-17)
    normalize.add_argument('--true-peak', type=float, default=-2)
    normalize.add_argument('--lra', type=float, default=11)
    normalize.add_argument('--report')
    serve = commands.add_parser('serve', help='在 127.0.0.1 提供支持视频拖动的审阅目录')
    serve.add_argument('--directory', required=True)
    serve.add_argument('--port', type=int, default=0)
    return p


def add_request(project, payload):
    from .workflow import save_plan
    if not isinstance(payload, dict) or "request" in payload:
        raise NTFError("request_format", "Use a flat request object with kind, mode, prompt and optional references.")
    request = dict(payload)
    kind = request.pop("kind", None)
    if kind not in ("image", "video", "audio"):
        raise NTFError("request_kind", "Request kind must be image, video or audio.")
    aid = request.pop("action_id", kind + "." + uuid.uuid4().hex[:12])
    action = {"id": aid, "kind": kind, "needs": request.pop("needs", []), "request": request}
    for name in ("scene_id", "selection_slot", "select_index"):
        if name in request:
            action[name] = request.pop(name)
    plan = project.plan
    index = next((i for i, a in enumerate(plan["actions"]) if a["id"] == aid), None)
    if index is not None:
        # A request that failed local checks (an invalid size, say) never reached the provider: the same ID can be
        # requested again with the fix. Anything sent, still planned or with results keeps its record.
        record = project.state["actions"].get(aid, {})
        attempts = [project.state["attempts"].get(t, {}) for t in record.get("attempts", [])]
        never_sent = (record.get("status") == "failed" and attempts and not record.get("outputs")
                      and not any(a.get("submission_started") or a.get("job") for a in attempts))
        if not never_sent:
            raise NTFError("action_exists", "Action already exists. Edit its plan and use ntf run --action; use --force for an intentional new version.")
        plan["actions"][index] = action
        with project.transaction() as state:
            entry = state["actions"].setdefault(aid, {"attempts": [], "outputs": []})
            entry["status"] = "pending"
            for key in ("error", "blocked_reason"):
                entry.pop(key, None)
    else:
        plan["actions"].append(action)
    save_plan(project, plan)
    return aid


def dispatch(args):
    from .config import default_config, list_routes, load_config, connection_environment
    from .runner import compose_project, run
    from .workflow import make_plan, save_plan, status
    if args.command == "init":
        project = init_project(args.project, args.title)
        return {"project": str(project.root), "project_id": project.document["project_id"]}
    if args.command == "config-init":
        path = Path(args.file).expanduser().resolve()
        if path.exists():
            raise NTFError("config_exists", "The configuration file already exists; edit it in place.")
        if path.suffix.lower() in (".yaml", ".yml", ".toml"):
            raise NTFError("config_format", "config-init writes JSON; use a .json filename.")
        config = default_config()
        atomic_json(path, config)
        return {"config": str(path), "routes": len(config["routes"]), "connectivity": "not_tested"}
    if args.command == "routes":
        from .config import LOADED_ENV_FILES, connection_status
        with connection_environment(load_config(args.config), args.connections_file) as config:
            routes = [{**row, **connection_status(config, row["id"])} for row in list_routes(config)]
            return {"routes": routes, "env_files": list(LOADED_ENV_FILES)}
    if args.command == "inspect":
        from .inspection import inspect_media
        return inspect_media(args.file, decode=args.decode, output=args.output, frames=args.frames,
                             max_width=args.max_width, jpeg_quality=args.jpeg_quality, at_seconds=args.at_seconds,
                             expected_width=args.expect_width, expected_height=args.expect_height, expected_fps=args.expect_fps,
                             expected_duration=args.expect_duration, duration_tolerance=args.duration_tolerance,
                             expect_audio=None if args.expect_audio is None else args.expect_audio=='yes',
                             audio_check=args.audio_check, min_mean_dbfs=args.min_mean_dbfs, max_peak_dbfs=args.max_peak_dbfs,
                             expected_loudness_lufs=args.expect_loudness_lufs, loudness_tolerance=args.loudness_tolerance,
                             scan=args.scan, freeze_seconds=args.freeze_seconds, silence_seconds=args.silence_seconds,
                             timeline=args.timeline, holds=args.holds, drops=args.drops, beat_seconds=args.beat_seconds,
                             low_motion_seconds=args.low_motion_seconds, low_motion_level=args.low_motion_level)
    if args.command == 'compare':
        from .compare import compare_board
        return compare_board(args.inputs, output=args.output, at=args.at, overlay=args.overlay, crop=args.crop,
                             labels=args.label, cell_width=args.cell_width, columns=args.columns, font_file=args.font_file)
    if args.command == 'sheet':
        from .sheet import contact_sheet
        if args.cuts and (args.start is not None or args.end is not None):
            raise NTFError('sheet_parameters', '--cuts 与 --start/--end 二选一。')
        return contact_sheet(args.file, output=args.output, fps=args.fps, start=args.start, end=args.end,
                             timeline=args.timeline, cuts=args.cuts, cut_padding=args.cut_padding,
                             cell_width=args.cell_width, columns=args.columns, max_cells=args.max_cells,
                             jpeg_quality=args.jpeg_quality)
    if args.command == 'normalize':
        from .loudness import normalize
        try:
            return normalize(Path(args.file), Path(args.output), lufs=args.lufs,
                             true_peak=args.true_peak, lra=args.lra,
                             report=Path(args.report) if args.report else None)
        except (ValueError, OSError) as exc:
            raise NTFError('audio_normalization_failed', str(exc)) from exc
    if args.command == 'serve':
        from .review_server import serve
        try:
            return serve(Path(args.directory), args.port)
        except (ValueError, OSError) as exc:
            raise NTFError('review_server_failed', str(exc)) from exc
    if args.command == "install-info":
        from .text_overlay import render_support
        try:
            edge_version = importlib.metadata.version("edge-tts")
        except importlib.metadata.PackageNotFoundError:
            edge_version = None
        support = render_support()
        result = {"version": __version__, "python": sys.executable, "python_version": platform.python_version(),
                "package": str(Path(__file__).parent), "ffmpeg": shutil.which("ffmpeg"),
                "ffprobe": shutil.which("ffprobe"), "edge_tts": edge_version,
                "text_rendering": support}
        try:
            result["web_rendering"] = {"playwright": importlib.metadata.version("playwright")}
        except importlib.metadata.PackageNotFoundError:
            result["web_rendering"] = {"playwright": None}
        marker = Path(sys.prefix).parent/'installation.json'
        if marker.is_file():
            installed = read_json(marker)
            if installed.get('plugin') == 'notetofilm-local':
                result['ntf_command'] = installed.get('ntf_command')
        checks = []
        if args.require_audio:
            checks.append({'name':'audio_dependencies','passed':bool(edge_version and result['ffprobe'])})
        if args.require_render:
            checks.append({'name':'render_dependencies','passed':bool(result['ffmpeg'] and result['ffprobe'] and support['pillow'] and support['ffmpeg_overlay'])})
        if args.font_file:
            from .text_overlay import _font
            try:
                _font(Path.cwd(),{'subtitle_font_file':args.font_file,'subtitle_font_index':args.font_index,'subtitle_font_size':13,'height':720})
                checks.append({'name':'readable_font','passed':True})
            except NTFError as exc:
                checks.append({'name':'readable_font','passed':False,'error_code':exc.code})
        if checks:
            result['verification'] = {'passed':all(c['passed'] for c in checks),'checks':checks}
        return result
    project = Project(args.project)
    if args.command == "import":
        return project.import_asset(args.file, args.kind, args.select)
    if args.command == 'frames':
        from .frames import extract_frames
        return extract_frames(project, select=args.select, asset_id=args.asset_id, output=args.output, fps=args.fps,
                              width=args.width, height=args.height, jpeg_quality=args.jpeg_quality, force=args.force)
    if args.command == "storyboard":
        return project.put_storyboard(read_json(args.file))
    if args.command == "settings":
        from .compose import _settings
        document = project.document
        changed = False
        for name in ("voice", "rate", "volume", "pitch", "image_route", "video_route"):
            value = getattr(args, name)
            if value is not None:
                document.setdefault("defaults", {})[name] = value
                changed = True
        for argument, field_name in (("width", "width"), ("height", "height"), ("fps", "fps"),
                                     ("subtitles", "subtitles_mode"), ("audio_tracks", "audio_tracks"),
                                     ("subtitle_renderer", "subtitle_renderer"),
                                     ("font_file", "subtitle_font_file"), ("font_index", "subtitle_font_index"),
                                     ("font_size", "subtitle_font_size"),
                                     ('loudness_lufs','audio_loudness_lufs'),('true_peak_db','audio_true_peak_db')):
            value = getattr(args, argument)
            if value is not None:
                document.setdefault("output", {})[field_name] = value
                changed = True
        if args.no_background_audio and args.background_audio:
            raise NTFError('settings_parameters','Select background-audio or no-background-audio, not both.')
        if args.no_loudness_normalization:
            if args.loudness_lufs is not None:
                raise NTFError('settings_parameters','Select loudness-lufs or no-loudness-normalization, not both.')
            document.setdefault('output',{})['audio_loudness_lufs'] = None
            changed = True
        if args.no_background_audio:
            document.pop('background_audio',None)
            changed = True
        background_updates = {field: getattr(args,argument) for argument,field in (
            ('background_volume','volume'),('background_start_seconds','start_seconds'),
            ('background_trim_start','trim_start'),('background_duration','duration_seconds'),
            ('background_fade_in','fade_in_seconds'),('background_fade_out','fade_out_seconds'),('background_loop','loop'))
            if getattr(args,argument) is not None}
        if any(isinstance(v,(int,float)) and not isinstance(v,bool) and (not math.isfinite(v) or v<0)
               for v in background_updates.values()):
            raise NTFError('settings_parameters','Background timing and volume must be finite nonnegative values.')
        if args.background_audio:
            asset = project.state['assets'].get(args.background_audio)
            if not asset or not asset['metadata'].get('has_audio'):
                raise NTFError('settings_parameters','background-audio must select an imported asset containing audio.')
            document['background_audio'] = {'asset_id':args.background_audio}
        if args.background_audio or background_updates:
            if not document.get('background_audio'):
                raise NTFError('settings_parameters','Select background-audio before updating its mix parameters.')
            document['background_audio'].update(background_updates)
            changed = True
        _settings({"output": document.get("output", {})})
        if changed:
            atomic_json(project.root / "project.json", document)
        return {"defaults": document.get("defaults", {}), "output": document.get("output", {}),
                'background_audio':document.get('background_audio'),
                "updated": changed, "plan_refresh_required": changed}
    if args.command == "plan":
        return save_plan(project, read_json(args.file) if args.file else make_plan(project))
    if args.command in ("status", "ready"):
        result = status(project)
        if args.command == "ready":
            return {"project": str(project.root), "ready": [a for a in result["actions"] if a["ready"]],
                    "resumable": [a for a in result["actions"] if a["status"] in ("submitted", "waiting_download")]}
        if getattr(args, "usage", False):
            from .workflow import usage
            result["usage"] = usage(project)
        return result
    if args.command == "run":
        with connection_environment(load_config(args.config), args.connections_file) as config:
            return run(project, config, args.action, args.wait_seconds, args.retry, args.force,
                       kind=args.kind, scene_ids=args.scene_ids, poll_only=args.poll_only,
                       submit_only=args.submit_only, max_new_actions=args.max_new_actions,
                       stop_on_error=args.stop_on_error)
    if args.command == "select":
        selected = project.select(args.slot, args.asset_ids)
        selected["state"] = status(project)
        return selected
    if args.command == "generate":
        request = read_json(args.request)
        if isinstance(request, dict) and request.get("kind") not in ("image", "video"):
            raise NTFError("request_kind", "generate accepts image or video; use ntf audio for speech.")
        aid = add_request(project, request)
        with connection_environment(load_config(args.config), args.connections_file) as config:
            return run(project, config, aid, args.wait_seconds)
    if args.command == "audio":
        request = {"kind": "audio", "text": args.text, "voice": args.voice,
                   "rate": args.rate, "volume": args.volume, "pitch": args.pitch}
        for key, value in (("speech_text", args.speech_text), ("action_id", args.action_id), ("selection_slot", args.select)):
            if value is not None:
                request[key] = value
        return run(project, action_id=add_request(project, request))
    if args.command == "compose":
        return compose_project(project, read_json(args.manifest), render=not args.plan_only)
    if args.command == 'motion':
        from .motion import motion_project
        return motion_project(project, read_json(args.manifest), scene_ids=args.scene_ids, stage=args.stage,
                              select_prefix=args.select_prefix, plan_only=args.plan_only,
                              preview_only=args.preview_only, preview_time=args.preview_time, force=args.force)
    if args.command == 'web-render':
        from .web_render import web_render
        return web_render(project, args.page, scene_id=args.scene_id, duration=args.duration, select=args.select,
                          fps=args.fps, width=args.width, height=args.height,
                          preview_times=args.preview_times, force=args.force, dpr=args.dpr,
                          subframes=args.subframes, shutter=args.shutter, grain=args.grain,
                          text_check=args.text_check, text_scan=args.text_scan, time_range=args.time_range)
    if args.command == 'score':
        from .synth import score_project
        return score_project(project, args.file, select=args.select, duration=args.duration, stems=args.stems, force=args.force)
    if args.command == "timing":
        from .timing import narration_timing
        result = narration_timing(project, mode=args.mode, scene_ids=args.scene_ids,
                                tail_seconds=args.tail_seconds, lead_seconds=args.lead_seconds,
                                min_seconds=args.min_seconds, max_seconds=args.max_seconds,
                                units_per_second=args.units_per_second,
                                preserve_planned=args.preserve_planned, apply=args.apply)
        if args.js:
            from .timing import export_timing_js
            result['timing_js'] = export_timing_js(project, args.js)
        return result
    if args.command == "preview":
        from .preview import export_preview
        return export_preview(project, output=args.output, video=args.video, render_id=args.render,
                              timeline_file=args.timeline, max_width=args.max_width, jpeg_quality=args.jpeg_quality)
    raise NTFError("command", "Unknown command.")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        from .config import load_env_files
        load_env_files()
        result = dispatch(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get('verification',{}).get('passed') is False:
            return 2
        return 2 if any(x.get("error") or x.get("status") in ("failed", "unknown", "interrupted") for x in result.get("executed", [])) else 0
    except NTFError as exc:
        print(json.dumps({"error": exc.as_dict()}, ensure_ascii=False), file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": {"code": "local_operation_failed", "message": "Cannot read or write a local input.",
                                    "details": {"exception": type(exc).__name__}}}), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"error": {"code": "interrupted", "message": "Local execution stopped; use ntf status before resuming."}}), file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
