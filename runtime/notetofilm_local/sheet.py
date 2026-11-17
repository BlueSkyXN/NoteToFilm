"""Timestamped contact sheets that let an Agent look through a video by time."""
from __future__ import annotations

import math
import re
import shutil
import tempfile
from pathlib import Path

from .errors import NTFError
from .io import atomic_json, read_json
from .media import probe, run_media_command

MAX_FRAMES = 600


def _label_font(size):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _read_timeline(path, info):
    from .preview import _timeline
    data = read_json(path)
    windows = _timeline(data, info.get('duration_seconds'), info.get('fps') or 30)
    transitions = {}
    for scene in data['scenes']:
        transition = scene.get('transition') if isinstance(scene.get('transition'), dict) else {}
        seconds = transition.get('duration_seconds', 0) or 0
        transitions[scene['id']] = (str(transition.get('type', 'cut')),
                                    float(seconds) if isinstance(seconds, (int, float)) and math.isfinite(seconds) else 0.0)
    cues = []
    for cue in data.get('subtitles', []) if isinstance(data.get('subtitles'), list) else []:
        if isinstance(cue, dict) and isinstance(cue.get('text'), str) and all(
                isinstance(cue.get(k), (int, float)) and not isinstance(cue.get(k), bool) for k in ('start_seconds', 'end_seconds')):
            cues.append((float(cue['start_seconds']), float(cue['end_seconds']), cue['text']))
    return windows, transitions, cues


def _windows(info, start, end, cuts, cut_padding, timeline):
    duration = info['duration_seconds']
    if cuts:
        if timeline is None:
            raise NTFError('sheet_parameters', '--cuts 需要同时提供 --timeline。')
        windows, transitions, _ = timeline
        ordered = sorted(windows.items(), key=lambda item: item[1][0])
        result = []
        for (previous, _), (scene_id, (scene_start, _)) in zip(ordered, ordered[1:]):
            kind, seconds = transitions.get(scene_id, ('cut', 0.0))
            label = f'cut {previous}>{scene_id}' + ('' if kind == 'cut' else f' {kind} {seconds:g}s')
            result.append({'label': label, 'start_seconds': max(0.0, scene_start - cut_padding),
                           'end_seconds': min(duration, scene_start + seconds + cut_padding)})
        if not result:
            raise NTFError('sheet_parameters', '时间表只有一个镜头，没有可查看的剪点。')
        return result
    start = 0.0 if start is None else start
    end = duration if end is None else min(end, duration)
    if not 0 <= start < end:
        raise NTFError('sheet_parameters', '查看窗口须位于视频时长之内，且起点早于终点。')
    return [{'label': 'full' if start == 0 and end == duration else 'window',
             'start_seconds': start, 'end_seconds': end}]


def contact_sheet(source, *, output, fps=2.0, start=None, end=None, timeline=None, cuts=False,
                  cut_padding=.5, cell_width=320, columns=4, max_cells=24, jpeg_quality=80):
    """Write JPEG contact sheets plus sheet.json; frames are labelled with source time and scene IDs."""
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise NTFError('render_dependency_missing', '联系表需要 render 依赖中的 Pillow。') from exc
    numbers = [v for v in (fps, start, end, cut_padding) if v is not None]
    if any(isinstance(v, bool) or not math.isfinite(v) for v in numbers) or not 0 < fps <= 30 or cut_padding < 0:
        raise NTFError('sheet_parameters', '采样帧率须在 0–30 之间，窗口与剪点余量须为有限的非负秒数。')
    if not 80 <= cell_width <= 960 or not 1 <= columns <= 8 or not columns <= max_cells <= 64 or not 1 <= jpeg_quality <= 95:
        raise NTFError('sheet_parameters', '使用 80–960 的格宽、1–8 列、每张不超过 64 格及 1–95 的 JPEG 质量。')
    source = Path(source).expanduser().resolve()
    info = probe(source)
    if info['kind'] != 'video' or not info.get('duration_seconds'):
        raise NTFError('sheet_parameters', '联系表只处理可测得时长的视频。')
    parsed = _read_timeline(timeline, info) if timeline else None
    windows = _windows(info, start, end, cuts, cut_padding, parsed)
    planned = sum(max(1, math.ceil((w['end_seconds'] - w['start_seconds']) * fps)) for w in windows)
    if planned > MAX_FRAMES:
        raise NTFError('sheet_too_many_frames', f'本次约需 {planned} 帧，超过 {MAX_FRAMES}；降低 --fps 或缩小查看窗口。',
                       {'planned_frames': planned, 'limit': MAX_FRAMES})
    output = Path(output).expanduser().resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise NTFError('output_exists', '选择一个空目录保存联系表，保留之前的查看记录。')
    if source.is_relative_to(output):
        raise NTFError('output_input_collision', '联系表目录不能包含源视频。')
    output.mkdir(parents=True, exist_ok=True)
    quality = max(2, min(31, round(31 - jpeg_quality * 29 / 95)))
    font, small = _label_font(15), _label_font(13)
    scene_windows, _, cues = parsed if parsed else ({}, {}, [])
    result = {'video': str(source), 'media': {k: info.get(k) for k in ('duration_seconds', 'width', 'height', 'fps', 'has_audio')},
              'fps': fps, 'timeline': str(Path(timeline).expanduser().resolve()) if timeline else None,
              'windows': [], 'sheets': []}
    sheet_number = 0
    work = Path(tempfile.mkdtemp(prefix='frames-', dir=output))
    try:
        for index, window in enumerate(windows, 1):
            frames_dir = work / f'w{index:03d}'
            frames_dir.mkdir()
            span = window['end_seconds'] - window['start_seconds']
            # Keep the first decoded frame of each sampling interval and label it with its own timestamp.
            bucket = f'floor(t*{fps:g}+1e-6)'
            select = f"select='isnan(prev_selected_t)+gte({bucket}-floor(prev_selected_t*{fps:g}+1e-6),1)'"
            log = run_media_command(['ffmpeg', '-hide_banner', '-nostdin',
                                     '-ss', f"{window['start_seconds']:.6f}", '-t', f'{span:.6f}', '-i', str(source),
                                     '-an', '-vf', f'{select},showinfo,scale={cell_width}:-2', '-fps_mode', 'vfr',
                                     '-q:v', str(quality), str(frames_dir / 'f_%05d.jpg')], timeout=600).stderr
            stamps = [float(v) for v in re.findall(r'Parsed_showinfo.*?pts_time:\s*(-?[0-9.]+)', log)]
            files = sorted(frames_dir.glob('f_*.jpg'))
            if not files or len(stamps) != len(files):
                raise NTFError('sheet_no_frames', '该窗口没有解出可标注时间的画面；检查起止时间或源视频。',
                               {'window': window, 'frames': len(files), 'timestamps': len(stamps)})
            frames = []
            for path, stamp in zip(files, stamps):
                t = round(window['start_seconds'] + stamp, 3)
                frames.append({'path': path, 'time_seconds': t,
                               'scene_ids': [sid for sid, (a, b) in scene_windows.items() if a - 1e-6 <= t < b],
                               'subtitle': next((text for a, b, text in cues if a - 1e-6 <= t < b), None)})
            record = {**window, 'sheets': []}
            for first in range(0, len(frames), max_cells):
                batch = frames[first:first + max_cells]
                sheet_number += 1
                with Image.open(batch[0]['path']) as sample:
                    cell_w, cell_h = sample.size
                label_h, header_h, gap = 22, 26, 4
                rows = math.ceil(len(batch) / columns)
                sheet = Image.new('RGB', (columns * (cell_w + gap) + gap, header_h + rows * (cell_h + label_h + gap) + gap), (24, 24, 24))
                draw = ImageDraw.Draw(sheet)
                draw.text((gap + 2, 5), f"{window['label']}  {window['start_seconds']:.2f}-{window['end_seconds']:.2f}s  "
                          f"{fps:g} fps  part {first // max_cells + 1}", fill=(235, 235, 235), font=font)
                for n, frame in enumerate(batch):
                    x = gap + (n % columns) * (cell_w + gap)
                    y = header_h + (n // columns) * (cell_h + label_h + gap)
                    with Image.open(frame['path']) as image:
                        sheet.paste(image.convert('RGB'), (x, y))
                    scenes = '/'.join(frame['scene_ids'])
                    draw.text((x + 3, y + cell_h + 3), f"{frame['time_seconds']:.2f}s  {scenes}", fill=(255, 214, 102), font=small)
                target = output / f'sheet_{sheet_number:03d}.jpg'
                sheet.save(target, quality=jpeg_quality)
                entry = {'path': str(target), 'window': window['label'],
                         'frames': [{k: v for k, v in f.items() if k != 'path'} for f in batch]}
                record['sheets'].append(str(target))
                result['sheets'].append(entry)
            result['windows'].append(record)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    atomic_json(output / 'sheet.json', result)
    result['sheet_json'] = str(output / 'sheet.json')
    return result
