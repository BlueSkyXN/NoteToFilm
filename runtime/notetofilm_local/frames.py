"""Turn an adopted video clip into the numbered frame sequence a code-animation page reads (media/<name>/000.jpg …)."""
from __future__ import annotations
import math
import shutil

from .errors import NTFError
from .media import probe, run_media_command


def extract_frames(project, *, select=None, asset_id=None, output, fps=24.0, width=None, height=None,
                   jpeg_quality=3, force=False):
    """Frames are named from 000.jpg at a fixed rate; the page maps clip seconds to floor(seconds * fps)."""
    if bool(select) == bool(asset_id):
        raise NTFError('frames_parameters', '用 --select 采用位或 --asset 素材 ID 二选一指定片段。')
    if not math.isfinite(fps) or not 1 <= fps <= 60 or not 2 <= jpeg_quality <= 31:
        raise NTFError('frames_parameters', '抽帧帧率用 1–60，JPEG 质量用 2–31（越小越好）。')
    ref = project.resolve({'selection': select} if select else {'asset_id': asset_id})
    if isinstance(ref, list):
        raise NTFError('frames_parameters', '这个采用位对应多个素材；用 --asset 指定其中一个。', {'select': select})
    if ref.get('kind') != 'video':
        raise NTFError('frames_parameters', '只能从视频素材抽帧。', {'asset_id': ref.get('asset_id')})
    if width is None or height is None:
        from .compose import _settings
        settings = _settings({'output': project.document.get('output', {})})
        width, height = width or settings['width'], height or settings['height']
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 16 or v > 8192 for v in (width, height)):
        raise NTFError('frames_parameters', '帧的宽高用 16–8192 的整数。')
    target = project.path(output)
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        if not force:
            raise NTFError('output_exists', '输出目录已有内容；换一个目录，或加 --force 用新素材替换。', {'output': output})
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    source = project.path(ref['path'])
    run_media_command(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-i', str(source), '-map', '0:v:0',
                       '-vf', f'fps={fps:g},scale={width}:{height}:flags=lanczos', '-q:v', str(jpeg_quality),
                       '-start_number', '0', str(target / '%03d.jpg')], timeout=900)
    frames = len(list(target.glob('*.jpg')))
    if not frames:
        raise NTFError('media_command_failed', '没有抽出任何帧。', {'asset_id': ref.get('asset_id')})
    info = probe(source)
    return {'output': target.relative_to(project.root).as_posix(), 'asset_id': ref.get('asset_id'), 'frames': frames,
            'fps': fps, 'width': width, 'height': height, 'source_duration_seconds': info.get('duration_seconds'),
            'naming': '000.jpg 起，第 i 帧对应素材 i / fps 秒'}
