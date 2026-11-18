"""Side-by-side boards for comparing candidates, directions, cut alignment and small details."""
from __future__ import annotations

import math
import shutil
import tempfile
from pathlib import Path

from .errors import NTFError
from .io import atomic_json
from .media import probe, run_media_command

MAX_INPUTS = 12
MAX_TIMES = 10


def _parse_input(raw):
    """`file` or `file@seconds`; the suffix picks one frame of a video."""
    text = str(raw)
    path, at = text, None
    if '@' in text:
        head, tail = text.rsplit('@', 1)
        try:
            at = float(tail)
        except ValueError:
            head, at = text, None
        else:
            path = head
    if at is not None and (not math.isfinite(at) or at < 0):
        raise NTFError('compare_parameters', '输入后缀 @秒数 须为非负数。', {'input': text})
    return Path(path).expanduser().resolve(), at


def _crop(value):
    if value is None:
        return None
    try:
        parts = [float(v) for v in str(value).split(',')]
    except ValueError:
        parts = []
    if len(parts) != 4 or not all(math.isfinite(v) for v in parts):
        raise NTFError('compare_parameters', '--crop 写成 x,y,宽,高，取 0–1 的画面比例，例如 0.2,0.6,0.3,0.2。')
    x, y, w, h = parts
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 - x + 1e-9 and 0 < h <= 1 - y + 1e-9):
        raise NTFError('compare_parameters', '--crop 区域须落在画面之内。')
    return x, y, w, h


def _frame(source, info, at, work, index, label):
    """Return a PIL image for an image file or one video frame."""
    from PIL import Image
    if info['kind'] == 'image':
        with Image.open(source) as image:
            return image.convert('RGB')
    duration = info.get('duration_seconds') or 0
    t = min(at, max(0.0, duration - 1 / max(1.0, info.get('fps') or 30)))
    target = work / f'{index:03d}_{label}.png'
    run_media_command(['ffmpeg', '-hide_banner', '-nostdin', '-ss', f'{t:.6f}', '-i', str(source),
                       '-frames:v', '1', '-y', str(target)], timeout=120)
    if not target.is_file():
        raise NTFError('compare_no_frame', '没能从视频中取出这一时刻的画面。', {'input': str(source), 'time_seconds': t})
    with Image.open(target) as image:
        return image.convert('RGB')


def _font(font_file, size):
    from PIL import ImageFont
    if font_file:
        try:
            return ImageFont.truetype(str(Path(font_file).expanduser()), size)
        except (OSError, ValueError):
            raise NTFError('compare_parameters', '无法读取 --font-file 字体。') from None
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def compare_board(inputs, *, output, at=None, overlay=False, crop=None, labels=None, cell_width=320,
                  columns=4, font_file=None, jpeg_quality=85):
    """Write compare.jpg and compare.json.

    Board: one row per video input with a cell per --at time; image inputs (or videos with @t) take one cell.
    When every input is a single frame, cells wrap into a grid of `columns`. Overlay: blend all single frames
    at equal weight to check whether objects line up across a cut. Crop: the same 0–1 region from every frame,
    enlarged, for checking small text and details.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise NTFError('render_dependency_missing', '对比表需要 render 依赖中的 Pillow。') from exc
    if not inputs or len(inputs) > MAX_INPUTS:
        raise NTFError('compare_parameters', f'提供 1–{MAX_INPUTS} 个图片或视频。')
    times = list(at or [])
    if len(times) > MAX_TIMES or any(isinstance(t, bool) or not math.isfinite(t) or t < 0 for t in times):
        raise NTFError('compare_parameters', f'--at 最多 {MAX_TIMES} 个非负秒数。')
    if not 120 <= cell_width <= 960 or not 1 <= columns <= 8:
        raise NTFError('compare_parameters', '使用 120–960 的格宽和 1–8 列。')
    region = _crop(crop)
    if labels is not None and len(labels) != len(inputs):
        raise NTFError('compare_parameters', '--label 的个数须与输入个数相同。')
    parsed = [_parse_input(raw) for raw in inputs]
    infos = []
    for path, _ in parsed:
        if not path.is_file():
            raise NTFError('compare_parameters', '找不到输入文件。', {'input': str(path)})
        info = probe(path)
        if info['kind'] not in ('image', 'video'):
            raise NTFError('compare_parameters', '只比较图片和视频。', {'input': str(path), 'kind': info['kind']})
        infos.append(info)
    output = Path(output).expanduser().resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise NTFError('output_exists', '选择一个空目录保存对比结果，保留之前的查看记录。')
    if any(path.is_relative_to(output) for path, _ in parsed):
        raise NTFError('output_input_collision', '对比目录不能包含输入文件。')
    names = labels or [f'{i + 1} {path.stem}' for i, (path, _) in enumerate(parsed)]
    if not font_file:
        names = [n if n.isascii() else f'{i + 1}' for i, n in enumerate(names)]
    output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='frames-', dir=output))
    rows = []
    try:
        for i, ((path, suffix_at), info) in enumerate(zip(parsed, infos)):
            if info['kind'] == 'image' or suffix_at is not None or overlay:
                moments = [None if info['kind'] == 'image' else (suffix_at if suffix_at is not None else (times[0] if times else 0.0))]
            else:
                if not times:
                    raise NTFError('compare_parameters', '视频输入需要 --at 时刻，或在文件名后写 @秒数。', {'input': str(path)})
                moments = times
            cells = []
            for n, t in enumerate(moments):
                frame = _frame(path, info, t or 0.0, work, i * MAX_TIMES + n, f'{i}')
                if region:
                    x, y, w, h = region
                    frame = frame.crop((round(x * frame.width), round(y * frame.height),
                                        round((x + w) * frame.width), round((y + h) * frame.height)))
                cells.append({'time_seconds': t, 'image': frame})
            rows.append({'label': names[i], 'input': str(path), 'kind': info['kind'], 'cells': cells})
        font, small = _font(font_file, 16), _font(font_file, 13)
        record = {'inputs': [{'label': r['label'], 'input': r['input'], 'kind': r['kind'],
                              'times': [c['time_seconds'] for c in r['cells']]} for r in rows],
                  'crop': region, 'overlay': overlay}
        if overlay:
            frames = [r['cells'][0]['image'] for r in rows]
            if len(frames) < 2:
                raise NTFError('compare_parameters', '--overlay 至少需要两个画面。')
            base = frames[0]
            blended = base.copy()
            for k, frame in enumerate(frames[1:], 2):
                blended = Image.blend(blended, frame.resize(base.size), 1 / k)
            scale = cell_width * 2 / base.width
            blended = blended.resize((round(base.width * scale), round(base.height * scale)))
            strip_h = round(blended.height / len(frames))
            strip_w = round(base.width * strip_h / base.height)
            board = Image.new('RGB', (blended.width + strip_w + 12, max(blended.height, strip_h * len(frames)) + 30), (24, 24, 24))
            draw = ImageDraw.Draw(board)
            draw.text((6, 6), 'overlay (equal weights)  ' + ' + '.join(r['label'] for r in rows), fill=(235, 235, 235), font=font)
            board.paste(blended, (0, 30))
            for k, (frame, row) in enumerate(zip(frames, rows)):
                thumb = frame.resize((strip_w, strip_h))
                board.paste(thumb, (blended.width + 12, 30 + k * strip_h))
                draw.text((blended.width + 16, 32 + k * strip_h), row['label'], fill=(255, 214, 102), font=small)
        else:
            single = all(len(r['cells']) == 1 for r in rows)
            sample = rows[0]['cells'][0]['image']
            cell_h = max(40, round(cell_width * sample.height / sample.width))
            label_h, gap, side = 20, 6, 0 if single else 150
            if single:
                ncol = min(columns, len(rows))
                nrow = math.ceil(len(rows) / ncol)
                board = Image.new('RGB', (gap + ncol * (cell_width + gap), gap + nrow * (cell_h + label_h + gap)), (24, 24, 24))
                draw = ImageDraw.Draw(board)
                for k, row in enumerate(rows):
                    x, y = gap + (k % ncol) * (cell_width + gap), gap + (k // ncol) * (cell_h + label_h + gap)
                    cell = row['cells'][0]
                    board.paste(cell['image'].resize((cell_width, cell_h)), (x, y))
                    stamp = '' if cell['time_seconds'] is None else f"  {cell['time_seconds']:.2f}s"
                    draw.text((x + 3, y + cell_h + 3), row['label'] + stamp, fill=(255, 214, 102), font=small)
            else:
                ncol = max(len(r['cells']) for r in rows)
                board = Image.new('RGB', (side + gap + ncol * (cell_width + gap), gap + len(rows) * (cell_h + label_h + gap)), (24, 24, 24))
                draw = ImageDraw.Draw(board)
                for k, row in enumerate(rows):
                    y = gap + k * (cell_h + label_h + gap)
                    draw.text((8, y + cell_h // 2 - 8), row['label'], fill=(235, 235, 235), font=font)
                    for n, cell in enumerate(row['cells']):
                        x = side + gap + n * (cell_width + gap)
                        board.paste(cell['image'].resize((cell_width, cell_h)), (x, y))
                        stamp = 'image' if cell['time_seconds'] is None else f"{cell['time_seconds']:.2f}s"
                        draw.text((x + 3, y + cell_h + 3), stamp, fill=(255, 214, 102), font=small)
        target = output / 'compare.jpg'
        board.save(target, quality=jpeg_quality)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    record['board'] = str(target)
    atomic_json(output / 'compare.json', record)
    record['compare_json'] = str(output / 'compare.json')
    return record
