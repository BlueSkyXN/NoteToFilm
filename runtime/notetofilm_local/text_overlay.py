"""Local text rendering with optional Pillow; no service or credential access."""
from __future__ import annotations

import importlib.metadata
import math
from pathlib import Path
import shutil
import subprocess
import tempfile

from .errors import NTFError
from .media import run_media_command


def render_support():
    filters = set()
    if shutil.which('ffmpeg'):
        result = run_media_command(['ffmpeg', '-hide_banner', '-filters'], timeout=15)
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) > 1:
                filters.add(parts[1])
    try:
        pillow = importlib.metadata.version('Pillow')
    except importlib.metadata.PackageNotFoundError:
        pillow = None
    return {'ffmpeg_subtitles': 'subtitles' in filters,
            'ffmpeg_overlay': 'overlay' in filters, 'ffmpeg_drawtext': 'drawtext' in filters,
            'pillow': pillow}


def _font(root, settings):
    try:
        from PIL import ImageFont
    except ImportError:
        raise NTFError('text_dependency_missing', 'Pillow text rendering requires the render extra from the selected local plugin source; alternatively use an FFmpeg build with the subtitles filter for captions.') from None
    value = settings.get('subtitle_font_file')
    if not value:
        raise NTFError('text_font_required', 'Set output.subtitle_font_file to an available font file; choose a font containing the characters used in captions and labels.')
    path = Path(value).expanduser()
    path = path if path.is_absolute() else Path(root) / path
    # Keep the existing ASS-unit size convention consistent across renderers.
    size = max(1, round(settings['subtitle_font_size'] * settings['height'] / 288))
    try:
        return ImageFont.truetype(str(path), size=size)
    except (OSError, ValueError):
        raise NTFError('text_font_invalid', 'Cannot load output.subtitle_font_file; select a readable TTF, OTF, or TTC font.') from None


def prepare_text_renderer(root, settings, cues, overlays):
    if not cues and not overlays:
        return None
    support = render_support()
    requested = settings['subtitle_renderer']
    if requested == 'libass':
        if overlays:
            raise NTFError('text_renderer_unsupported', 'Timed text_overlays require subtitle_renderer=pillow or auto; libass handles the subtitle track only.')
        if not support['ffmpeg_subtitles']:
            raise NTFError('subtitle_filter_missing', 'This FFmpeg build lacks the subtitles filter. Use subtitle_renderer=pillow with the render extra and a subtitle_font_file, or select an FFmpeg build with libass.')
        return 'libass'
    if requested == 'auto' and not overlays and support['ffmpeg_subtitles']:
        return 'libass'
    if not support['ffmpeg_overlay']:
        raise NTFError('text_filter_missing', 'The Pillow route requires the FFmpeg overlay filter; select an FFmpeg build that provides overlay.')
    _font(root, settings)
    return 'pillow'


_NO_LINE_START = set('，。！？、；：,.!?;:）)]】》」』”’…—%')
_NO_LINE_END = set('（([【《「『“‘')


def _word(char):
    return char.isascii() and char.isalnum()


def _lines(draw, value, font, width):
    """Wrap by width; closing punctuation stays at line end, Latin words and numbers stay whole."""
    lines = []
    for paragraph in value.split('\n'):
        line = ''
        for char in paragraph:
            if line and draw.textlength(line + char, font=font) > width and char not in _NO_LINE_START:
                if char == ' ':
                    lines.append(line.rstrip())
                    line = ''
                    continue
                carry = ''
                while line and line[-1] in _NO_LINE_END:
                    carry, line = line[-1] + carry, line[:-1]
                if not carry and _word(char):
                    start = len(line)
                    while start and _word(line[start - 1]):
                        start -= 1
                    if start:
                        carry, line = line[start:], line[:start]
                if line:
                    lines.append(line.rstrip())
                line = carry
            line += char
        lines.append(line)
    return lines


def _draw_frame(settings, font, active):
    from PIL import Image, ImageDraw
    width, height = settings['width'], settings['height']
    image = Image.new('RGBA', (width, height))
    draw = ImageDraw.Draw(image)
    margin = max(4, round(width * .05))
    line_height = max(1, round(font.size * 1.35))
    stroke = max(1, round(font.size / 18))
    for item in active:
        caption = item.get('position') == 'caption'
        lines = _lines(draw, item['text'], font, width - margin * 2)
        block_height = line_height * len(lines)
        if block_height > height - margin * 2:
            raise NTFError('text_does_not_fit', 'Text is taller than the output frame; reduce subtitle_font_size or shorten the displayed text without inventing new subtitle times.')
        position = item.get('position', 'top-left')
        y = height - margin - block_height if caption or position.startswith('bottom') else margin
        sizes = [draw.textlength(line, font=font) for line in lines]
        block_width = max(sizes, default=0)
        x = width - margin - block_width if position.endswith('right') else margin
        if position.endswith('center'):
            x = (width - block_width) / 2
        if not caption:
            pad = max(2, font.size // 3)
            draw.rectangle((x-pad, y-pad, x+block_width+pad, y+block_height+pad), fill=(12, 22, 30, 205))
        for i, line in enumerate(lines):
            left = (width - sizes[i]) / 2 if caption else x
            draw.text((left, y + i * line_height), line, font=font, anchor='lt', fill='white',
                      stroke_width=stroke, stroke_fill=(0, 0, 0, 210))
    return image.tobytes()


def burn_text(source, output, root, settings, duration, cues, overlays):
    """Stream a bounded-memory RGBA track; copy the already composed audio."""
    font = _font(root, settings)
    events = [{**cue, 'position': 'caption'} for cue in cues] + list(overlays)
    width, height = settings['width'], settings['height']
    args = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-threads', '1',
            '-filter_complex_threads', '1', '-i', str(source),
            '-f', 'rawvideo', '-pixel_format', 'rgba', '-video_size', f'{width}x{height}',
            '-framerate', settings['fps_expression'], '-i', 'pipe:0',
            '-filter_complex', '[0:v:0][1:v:0]overlay=0:0:shortest=1[v]',
            '-map', '[v]', '-map', '0:a?', '-map_metadata', '0', '-c:v', 'libx264', '-preset', 'veryfast',
            '-crf', '20', '-pix_fmt', 'yuv420p', '-threads', '1', '-c:a', 'copy',
            '-t', str(duration), '-movflags', '+faststart', str(output)]
    process = None
    with tempfile.TemporaryFile() as errors:
        try:
            process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors)
            previous, frame = None, None
            for n in range(math.ceil(duration * settings['fps'] - 1e-8)):
                t = n / settings['fps']
                active = tuple(i for i, event in enumerate(events) if event['start_seconds'] <= t < event['end_seconds'])
                if active != previous:
                    frame = _draw_frame(settings, font, [events[i] for i in active])
                    previous = active
                process.stdin.write(frame)
            process.stdin.close()
            if process.wait(timeout=300):
                raise OSError('FFmpeg text rendering failed')
        except BaseException as exc:
            if process:
                if process.poll() is None:
                    process.kill()
                process.wait()
                if process.stdin and not process.stdin.closed:
                    try:
                        process.stdin.close()
                    except OSError:
                        pass
            if isinstance(exc, NTFError):
                raise
            if not isinstance(exc, Exception):
                raise
            errors.seek(0)
            raise NTFError('text_render_failed', 'Could not finish local text rendering; earlier source media was preserved.',
                           {'stderr': errors.read().decode('utf-8', errors='replace')[-3000:]}) from None
