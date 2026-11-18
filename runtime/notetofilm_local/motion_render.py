"""Render validated motion layers with Pillow and FFmpeg; no provider calls."""
from __future__ import annotations

import math
from pathlib import Path
import subprocess
import tempfile

from .errors import NTFError

try:
    from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFont, ImageOps
except ImportError:
    Image = ImageChops = ImageColor = ImageDraw = ImageFont = ImageOps = None

def color(value):
    return value if isinstance(value, str) else tuple(value)

def partial_path(points, fraction):
    points = [tuple(p) for p in points]
    if fraction >= 1:
        return points
    length = sum(math.dist(a, b) for a, b in zip(points, points[1:])) * max(0, fraction)
    result = points[:1]
    for a, b in zip(points, points[1:]):
        distance = math.dist(a, b)
        if distance <= length:
            result.append(b); length -= distance
        else:
            ratio = length / max(distance, 1e-9)
            result.append(tuple(a[j] + (b[j]-a[j])*ratio for j in range(2)))
            break
    return result

def draw_layer(layer, size, font_file, t=None, fonts=None, font_index=0):
    canvas = Image.new('RGBA', size)
    d = ImageDraw.Draw(canvas)
    for obj in layer.get('objects', []):
        kind = obj['type']
        fill = color(obj.get('fill', '#191919'))
        if kind == 'rect':
            outline = color(obj['outline']) if obj.get('outline') is not None else None
            d.rectangle(obj['box'], fill=fill, outline=outline, width=obj.get('width', 1))
        elif kind == 'gradient':
            x0, y0, x1, y1 = obj['box']
            rgb = ImageColor.getrgb(obj.get('fill', '#141414'))[:3]
            for yy in range(y0, y1):
                alpha = round(obj.get('alpha_start', 0)+(obj.get('alpha_end', 240)-obj.get('alpha_start', 0))*(yy-y0)/max(1, y1-y0-1))
                d.line([(x0, yy), (x1, yy)], fill=(*rgb, alpha))
        elif kind in ('line', 'arrow'):
            progress = 1 if t is None else min(1, max(0, (t-obj.get('reveal_start', -1))/max(1e-6, obj.get('reveal_end', 0)-obj.get('reveal_start', -1))))
            if progress <= 0:
                continue
            points = partial_path(obj['points'], progress)
            d.line(points, fill=fill, width=obj.get('width', 2))
            if kind == 'line' or len(points) < 2:
                continue
            a, b = points[-2:]
            width = obj.get('width', 3)
            angle = math.atan2(b[1]-a[1], b[0]-a[0])
            length = obj.get('head', 13)
            pts = [b, (b[0]-length*math.cos(angle-.5), b[1]-length*math.sin(angle-.5)),
                   (b[0]-length*math.cos(angle+.5), b[1]-length*math.sin(angle+.5))]
            d.polygon(pts, fill=fill)
        elif kind == 'text':
            fonts = fonts if fonts is not None else {}
            font_size = obj.get('size', 32)
            if font_size not in fonts:
                fonts[font_size] = ImageFont.truetype(font_file, font_size, index=font_index)
            font = fonts[font_size]
            x, y = obj['xy']
            width = obj.get('max_width', size[0]-x)
            lines = []
            for paragraph in obj['text'].split('\n'):
                line = ''
                for char in paragraph:
                    if line and d.textlength(line+char, font=font) > width:
                        lines.append(line); line = ''
                    line += char
                lines.append(line)
            for i, line in enumerate(lines):
                d.text((x, y+i*round(font.size*obj.get('leading', 1.25))), line,
                       font=font, fill=fill, anchor='lt')
        else:
            raise ValueError(f'Unknown drawing object: {kind}')
    return canvas

def opacity(layer, t, duration):
    start, end = layer.get('start', 0), layer.get('end', duration)
    if t < start or t >= end:
        return 0
    alpha = 1.
    fi, fo = layer.get('fade_in', 0), layer.get('fade_out', 0)
    if fi:
        alpha = min(alpha, (t-start)/fi)
    if fo:
        alpha = min(alpha, (end-t)/fo)
    return max(0., min(1., alpha))

def eased(value, kind):
    value = min(1., max(0., value))
    if kind == 'linear':
        return value
    if kind == 'ease_out':
        return 1-(1-value)**3
    if kind in ('smooth', 'ease_in_out'):
        return value*value*(3-2*value)
    raise ValueError(f'Unknown easing: {kind}')

def sample_property(layer, key, t, default):
    track = [(float(k['t']), k[key], k.get('ease', 'smooth'))
             for k in layer.get('keyframes', []) if key in k]
    if not track:
        return default
    if any(b[0] <= a[0] for a, b in zip(track, track[1:])):
        raise ValueError('同一属性的关键帧时间必须递增。')
    if track[0][0] > 0:
        track.insert(0, (0., default, 'linear'))
    if t <= track[0][0]:
        return track[0][1]
    for a, b in zip(track, track[1:]):
        if t <= b[0]:
            f = eased((t-a[0])/(b[0]-a[0]), b[2])
            if isinstance(a[1], (list, tuple)):
                return [x+(y-x)*f for x, y in zip(a[1], b[1])]
            return a[1]+(b[1]-a[1])*f
    return track[-1][1]


class VideoFrames:
    """顺序读取按目标帧率和速度解码的 RGBA 帧，避免额外视频库。"""
    def __init__(self, layer, fps):
        self.size = tuple(layer['source_size'])
        self.bytes_per_frame = self.size[0] * self.size[1] * 4
        self.index, self.last = -1, None
        self.errors = tempfile.TemporaryFile()
        self.process = subprocess.Popen([
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-threads', '1',
            '-ss', str(layer.get('trim_start', 0)), '-i', layer['path'],
            '-an', '-sn', '-dn', '-vf', f'setpts=(PTS-STARTPTS)/{layer.get("speed",1)},fps={fps}',
            '-pix_fmt', 'rgba', '-f', 'rawvideo', 'pipe:1'],
            stdout=subprocess.PIPE, stderr=self.errors)

    def frame(self, index):
        if index < self.index:
            raise NTFError('motion_frame_order', 'Motion video frames must be requested in time order.')
        while self.index < index:
            data = bytearray()
            while len(data) < self.bytes_per_frame:
                block = self.process.stdout.read(self.bytes_per_frame - len(data))
                if not block:
                    self.errors.seek(0)
                    raise NTFError('motion_source_short', '视频无法覆盖所需动效时间，请检查采用区间和速度。',
                                   {'stderr': self.errors.read().decode('utf-8', errors='replace')[-2000:]})
                data.extend(block)
            self.last = Image.frombytes('RGBA', self.size, bytes(data))
            self.index += 1
        return self.last

    def close(self):
        self.process.stdout.close()
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.errors.close()


class MotionFrames:
    def __init__(self, scene, settings):
        self.scene, self.settings = scene, settings
        self.size = (settings['width'], settings['height'])
        self.images, self.videos, self.placed, self.fonts = {}, {}, {}, {}
        for index, layer in enumerate(scene['layers']):
            if layer['type'] == 'image':
                with Image.open(layer['path']) as source:
                    self.images[index] = source.convert('RGBA')
            elif layer['type'] == 'draw' and not any('reveal_start' in obj for obj in layer['objects']):
                self.images[index] = draw_layer(layer, self.size, settings.get('font_file'), fonts=self.fonts,
                                                font_index=settings.get('font_index', 0))

    def close(self):
        for video in self.videos.values():
            video.close()
        for picture in self.images.values():
            picture.close()

    def frame(self, t):
        canvas = Image.new('RGBA', self.size, color(self.scene['background']))
        for index, layer in enumerate(self.scene['layers']):
            alpha = opacity(layer, t, self.scene['duration']) * sample_property(layer, 'opacity', t, layer.get('opacity', 1.))
            if alpha <= 0:
                continue
            rect = sample_property(layer, 'rect', t, layer.get('rect', [0, 0, *self.size]))
            offset = sample_property(layer, 'offset', t, layer.get('offset', [0, 0]))
            x, y, width, height = rect
            x, y = x + offset[0], y + offset[1]
            dynamic = layer['type'] == 'draw' and index not in self.images
            if layer['type'] == 'video':
                if index not in self.videos:
                    self.videos[index] = VideoFrames(layer, self.settings['fps_expression'])
                frame_index = max(0, math.floor((t - layer['start']) * self.settings['fps'] + 1e-6))
                source = self.videos[index].frame(frame_index)
            elif dynamic:
                source = draw_layer(layer, self.size, self.settings.get('font_file'), t=t, fonts=self.fonts,
                                    font_index=self.settings.get('font_index', 0))
            else:
                source = self.images[index]
            sw, sh = source.size
            cw, ch = (sh * width / height, sh) if sw / sh > width / height else (sw, sw * height / width)
            cx, cy = layer.get('centering', [.5, .5])
            fit = [(sw-cw)*cx, (sh-ch)*cy, (sw-cw)*cx+cw, (sh-ch)*cy+ch]
            crop = sample_property(layer, 'crop', t, layer.get('crop', fit))
            left, top, right, bottom = crop
            progress = min(1., max(0., (t-layer['start'])/(layer['end']-layer['start'])))
            zoom = layer.get('zoom_start', 1) + layer.get('zoom', 0) * progress
            fx, fy = layer.get('focus', [.5, .5])
            zw, zh = (right-left)/zoom, (bottom-top)/zoom
            left += ((right-left)-zw)*fx
            top += ((bottom-top)-zh)*fy
            crop = [left, top, left+zw, top+zh]
            cache_key = (tuple(rect), tuple(offset), tuple(crop))
            if layer['type'] != 'video' and not dynamic and self.placed.get(index, (None,))[0] == cache_key:
                placed = self.placed[index][1]
            else:
                sx, sy = zw/width, zh/height
                placed = source.transform(self.size, Image.Transform.AFFINE,
                    (sx, 0, left-x*sx, 0, sy, top-y*sy), Image.Resampling.BICUBIC,
                    fillcolor=(0, 0, 0, 0))
                bounds = Image.new('L', self.size)
                ImageDraw.Draw(bounds).rectangle((round(x), round(y), round(x+width)-1, round(y+height)-1), fill=255)
                placed.putalpha(ImageChops.multiply(placed.getchannel('A'), bounds))
                if layer['type'] != 'video' and not dynamic:
                    self.placed[index] = (cache_key, placed)
            reveal = layer.get('reveal')
            if reveal:
                progress = eased((t-reveal['start'])/(reveal['end']-reveal['start']), reveal.get('ease', 'smooth'))
                if progress <= 0:
                    continue
                a, b, c, d = reveal.get('box', [0, 0, *self.size])
                direction = reveal.get('direction', 'right')
                if direction == 'down': d = b+(d-b)*progress
                elif direction == 'up': b = d-(d-b)*progress
                elif direction == 'left': a = c-(c-a)*progress
                else: c = a+(c-a)*progress
                mask = Image.new('L', self.size)
                ImageDraw.Draw(mask).rectangle((a,b,c,d), fill=255)
                placed = placed.copy()
                placed.putalpha(ImageChops.multiply(placed.getchannel('A'), mask))
            if alpha < 1:
                placed = placed.copy()
                placed.putalpha(placed.getchannel('A').point(lambda value: round(value*alpha)))
            canvas.alpha_composite(placed)
        return canvas


def render_motion(scene, settings, target, preview_path, *, preview_only=False, preview_time=None):
    if Image is None:
        raise NTFError('render_dependency_missing', '动效需要现有 render 依赖中的 Pillow。')
    count = scene['frames']
    preview_at = scene.get('preview_time', min(scene['duration']*.62, (count-1)/settings['fps'])) if preview_time is None else preview_time
    if not preview_only:
        frames = MotionFrames(scene, settings)
        process = None
        with tempfile.TemporaryFile() as errors:
            try:
                process = subprocess.Popen([
                    'ffmpeg','-hide_banner','-loglevel','error','-nostdin','-n',
                    '-f','rawvideo','-pixel_format','rgb24','-video_size',f'{settings["width"]}x{settings["height"]}',
                    '-framerate',settings['fps_expression'],'-i','pipe:0','-an',
                    '-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-threads','2',
                    '-frames:v',str(count),'-movflags','+faststart',str(target)],
                    stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=errors)
                for index in range(count):
                    process.stdin.write(frames.frame(index/settings['fps']).convert('RGB').tobytes())
                process.stdin.close()
                if process.wait(timeout=300):
                    raise OSError('FFmpeg encoding failed')
            except BaseException as exc:
                if process:
                    if process.poll() is None: process.kill()
                    process.wait()
                    if process.stdin and not process.stdin.closed:
                        try: process.stdin.close()
                        except OSError: pass
                if isinstance(exc, NTFError) or not isinstance(exc, Exception):
                    raise
                errors.seek(0)
                raise NTFError('motion_render_failed', '动效编码未完成，已有素材保留。',
                               {'stderr':errors.read().decode('utf-8',errors='replace')[-3000:]}) from exc
            finally:
                frames.close()
    preview = MotionFrames(scene, settings)
    try:
        ImageOps.contain(preview.frame(preview_at).convert('RGB'), (960,960)).save(preview_path, quality=82, optimize=True)
    finally:
        preview.close()
