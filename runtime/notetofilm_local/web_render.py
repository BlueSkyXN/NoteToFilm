"""Render a page that exposes window.render(t) frame by frame into a silent project video.

The page draws the complete picture for any time t (seconds); frames are captured in a headless
browser and encoded with FFmpeg. The approach follows the render(t) contract of garden-skills
motion-showreel (MIT); see THIRD_PARTY_NOTICES.md.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import threading
import uuid
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlencode

from .errors import NTFError
from .io import atomic_json, file_digest
from .media import probe
from .project import check_id
from .review_server import ReviewHandler

BROWSER_ARGS = ['--force-color-profile=srgb', '--font-render-hinting=none', '--hide-scrollbars',
                '--enable-gpu', '--ignore-gpu-blocklist', '--enable-unsafe-swiftshader',
                '--autoplay-policy=no-user-gesture-required'] + (['--use-angle=metal'] if sys.platform == 'darwin' else [])
READY = "() => typeof window.render === 'function' && (!('READY' in window) || window.READY === true)"
RENDER = "async t => { await window.render(t); }"
RENDER_AND_COLLECT = "async t => { window.__ntfText.reset(); await window.render(t); return window.__ntfText.collect(); }"
TEXT_HOOK = Path(__file__).with_name('data') / 'text_hook.js'


class PageHandler(ReviewHandler):
    extensions_map = {**ReviewHandler.extensions_map, '.js': 'text/javascript', '.mjs': 'text/javascript',
                      '.json': 'application/json', '.svg': 'image/svg+xml', '.wasm': 'application/wasm',
                      '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf', '.otf': 'font/otf'}


def _difference(a, b):
    """Share of pixels whose largest channel change exceeds 24 levels (GPU antialiasing stays below)."""
    if a == b:
        return 0.0
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return 1.0
    import io
    with Image.open(io.BytesIO(a)) as first, Image.open(io.BytesIO(b)) as second:
        if first.size != second.size:
            return 1.0
        red, green, blue = ImageChops.difference(first.convert('RGB'), second.convert('RGB')).split()
        histogram = ImageChops.lighter(ImageChops.lighter(red, green), blue).histogram()
        return sum(histogram[25:]) / (first.size[0] * first.size[1])


def analyze_text(boxes, width, height, *, min_size_ratio=.025, bleed_size_ratio=.08):
    """Classify text boxes: CUT (crossing the frame edge), BLEED (large display type crossing on purpose),
    OVERLAP (two different strings covering each other) and TINY (too small to read)."""
    # text that lies wholly outside the frame (a label the camera has already left) is not on screen at all
    visible = [b for b in boxes if b.get('alpha', 1) >= .3 and b['x1'] > b['x0'] and b['y1'] > b['y0']
               and b['x1'] > 0 and b['y1'] > 0 and b['x0'] < width and b['y0'] < height]
    issues = []
    for b in visible:
        outside = b['x0'] < -1 or b['y0'] < -1 or b['x1'] > width + 1 or b['y1'] > height + 1
        if outside and not b.get('clip'):
            kind = 'BLEED' if b.get('size', 0) >= height * bleed_size_ratio else 'CUT'
            issues.append({'type': kind, 'text': b['text'], 'box': [round(b[k]) for k in ('x0', 'y0', 'x1', 'y1')]})
        if b.get('size', 0) < height * min_size_ratio:
            issues.append({'type': 'TINY', 'text': b['text'], 'size_px': round(b.get('size', 0), 1),
                           'box': [round(b[k]) for k in ('x0', 'y0', 'x1', 'y1')]})
    for i, a in enumerate(visible):
        for b in visible[i + 1:]:
            if a['text'] == b['text']:
                continue
            w = min(a['x1'], b['x1']) - max(a['x0'], b['x0'])
            h = min(a['y1'], b['y1']) - max(a['y0'], b['y0'])
            if w <= 0 or h <= 0:
                continue
            smaller = min((a['x1'] - a['x0']) * (a['y1'] - a['y0']), (b['x1'] - b['x0']) * (b['y1'] - b['y0']))
            if w * h > .15 * smaller:
                issues.append({'type': 'OVERLAP', 'text': [a['text'], b['text']],
                               'box': [round(max(a['x0'], b['x0'])), round(max(a['y0'], b['y0'])),
                                       round(min(a['x1'], b['x1'])), round(min(a['y1'], b['y1']))]})
    return issues


def _mark_issues(png, issues, scale, target):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    import io
    colors = {'CUT': (230, 40, 40), 'OVERLAP': (240, 140, 0), 'TINY': (40, 120, 230), 'BLEED': (150, 150, 150)}
    with Image.open(io.BytesIO(png)) as image:
        marked = image.convert('RGB')
        draw = ImageDraw.Draw(marked)
        for issue in issues:
            x0, y0, x1, y1 = (v * scale for v in issue['box'])
            draw.rectangle((x0, y0, x1, y1), outline=colors[issue['type']], width=max(2, round(2 * scale)))
            draw.text((x0 + 3, max(0, y0 - 12 * scale)), issue['type'], fill=colors[issue['type']])
        marked.save(target)
    return target


def _average(images):
    """Equal-weight mean of PNG frames (motion blur from sub-frame samples)."""
    if len(images) == 1:
        return images[0]
    try:
        from PIL import Image
    except ImportError as exc:
        raise NTFError('render_dependency_missing', '--subframes 需要 render 依赖中的 Pillow。') from exc
    import io
    mean = None
    for count, raw in enumerate(images, 1):
        with Image.open(io.BytesIO(raw)) as image:
            frame = image.convert('RGB')
            mean = frame if mean is None else Image.blend(mean, frame, 1 / count)
    out = io.BytesIO()
    mean.save(out, 'PNG', compress_level=1)
    return out.getvalue()


def _page(project, page):
    path = Path(page).expanduser()
    path = (path if path.is_absolute() else project.root / path).resolve()
    if not path.is_relative_to(project.root.resolve()):
        raise NTFError('web_page_invalid', '动画页面须放在项目目录内，与项目一起保存。')
    if path.is_dir():
        path = path / 'index.html'
    if not path.is_file() or path.suffix.lower() not in ('.html', '.htm'):
        raise NTFError('web_page_invalid', '找不到动画页面；传入项目内的 .html 文件或含 index.html 的目录。', {'page': str(path)})
    return path


def _fingerprint(page, settings, duration):
    folder = page.parent
    files = sorted(p for p in folder.rglob('*') if p.is_file() and not any(part.startswith('.') for part in p.relative_to(folder).parts))
    sources = [[p.relative_to(folder).as_posix(), file_digest(p)] for p in files]
    payload = {'page': page.name, 'sources': sources, 'settings': settings, 'duration': duration,
               'renderer': file_digest(Path(__file__))}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _settings(project, width, height, fps):
    from .compose import _settings as checked
    output = dict(project.document.get('output', {}))
    for key, value in (('width', width), ('height', height), ('fps', fps)):
        if value is not None:
            output[key] = value
    result = checked({'output': output})
    return {key: result[key] for key in ('width', 'height', 'fps', 'fps_expression')}


class _Session:
    """Local HTTP server over the project plus one headless browser page."""

    def __init__(self, project, page, settings, duration, dpr=1, text_check=False):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise NTFError('web_dependency_missing', '网页动画渲染需要 Playwright：在运行环境安装 web 可选依赖'
                           '（pip install playwright），再安装 Chromium（python -m playwright install chromium）或使用本机 Chrome。') from exc
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(PageHandler, directory=str(project.root)))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.errors = []
        self.playwright = sync_playwright().start()
        self.browser, tried = None, []
        for option in ({}, {'channel': 'chrome'}, {'channel': 'msedge'}):
            try:
                self.browser = self.playwright.chromium.launch(headless=True, args=BROWSER_ARGS, **option)
                self.engine = option.get('channel', 'chromium')
                break
            except Exception as exc:  # Playwright raises its own error types per channel
                tried.append(f"{option.get('channel', 'chromium')}: {str(exc).splitlines()[0][:160]}")
        if self.browser is None:
            self.close()
            raise NTFError('web_browser_missing', '没有可用的无头浏览器；安装 Chromium（python -m playwright install chromium）或 Google Chrome。',
                           {'tried': tried})
        self.size = {'width': settings['width'], 'height': settings['height']}
        self.dpr = dpr
        self.init_script = TEXT_HOOK.read_text(encoding='utf-8') if text_check else None
        relative = page.relative_to(project.root.resolve()).as_posix()
        query = urlencode({'w': settings['width'], 'h': settings['height'], 'fps': settings['fps'],
                           'duration': duration if duration is not None else '', 'render': 1})
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/{quote(relative)}?{query}'

    def open(self):
        page = self.browser.new_page(viewport=self.size, device_scale_factor=self.dpr)
        if self.init_script:
            page.add_init_script(self.init_script)
        page.on('pageerror', lambda error: self.errors.append(f'pageerror: {error}'[:300]))
        page.on('console', lambda message: message.type == 'error' and not message.text.startswith('Failed to load resource')
                and self.errors.append(f'console: {message.text}'[:300]))
        page.on('response', lambda response: response.status >= 400 and not response.url.endswith('/favicon.ico')
                and self.errors.append(f'{response.status} {response.url}'[:300]))
        page.goto(self.url)
        try:
            page.wait_for_function(READY, timeout=120000)
            page.evaluate("() => document.fonts ? document.fonts.ready.then(() => true) : true")
        except Exception as exc:
            raise NTFError('web_page_not_ready', '页面没有提供 window.render(t)，或 window.READY 一直未变为 true。',
                           {'errors': self.errors[-6:], 'detail': str(exc).splitlines()[0][:200]}) from exc
        self.check()
        return page

    def check(self):
        if self.errors:
            raise NTFError('web_page_error', '页面运行出错或缺少资源；修正后重试。', {'errors': self.errors[-6:]})

    def frame(self, page, t):
        page.evaluate(RENDER, t)
        self.check()
        return page.screenshot(type='png', clip={'x': 0, 'y': 0, **self.size}, caret='hide')

    def close(self):
        for action in (lambda: self.browser and self.browser.close(), lambda: self.playwright.stop(),
                       self.server.shutdown, self.server.server_close):
            try:
                action()
            except Exception:
                pass


def web_render(project, page, *, scene_id, duration=None, select=None, fps=None, width=None, height=None,
               preview_times=None, force=False, dpr=1, subframes=1, shutter=.5, grain=0, text_check=False):
    scene_id = check_id(scene_id, 'scene ID')
    slot = check_id(select or f'web.{scene_id}', 'selection slot')
    page = _page(project, page)
    settings = _settings(project, width, height, fps)
    if duration is not None and (isinstance(duration, bool) or not math.isfinite(duration) or duration <= 0):
        raise NTFError('web_render_parameters', '--duration 须为正的秒数。')
    preview_times = list(preview_times or [])
    if any(not math.isfinite(t) or t < 0 for t in preview_times):
        raise NTFError('web_render_parameters', '--preview-time 须为非负秒数。')
    options = {'dpr': dpr, 'subframes': subframes, 'shutter': shutter, 'grain': grain}
    if (isinstance(dpr, bool) or not isinstance(dpr, (int, float)) or not 1 <= dpr <= 3
            or not isinstance(subframes, int) or not 1 <= subframes <= 8
            or not isinstance(shutter, (int, float)) or not 0 < shutter <= 1
            or not isinstance(grain, (int, float)) or not 0 <= grain <= 40):
        raise NTFError('web_render_parameters', '--dpr 取 1–3，--subframes 取 1–8，--shutter 取 (0, 1]，--grain 取 0–40。')
    if text_check and not preview_times:
        raise NTFError('web_render_parameters', '--text-check 与 --preview-time 一起使用，检查指定时刻的文字。')
    session = _Session(project, page, settings, duration, dpr=dpr, text_check=text_check)
    job = project.root / 'work' / ('web_' + uuid.uuid4().hex[:12])
    try:
        view = session.open()
        if duration is None:
            duration = view.evaluate("() => Number(window.DUR)")
            if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
                raise NTFError('web_render_parameters', '页面未设置 window.DUR；用 --duration 指定秒数。')
        frames = math.ceil(duration * settings['fps'] - 1e-8)
        window = frames / settings['fps']
        base = {'scene_id': scene_id, 'page': page.relative_to(project.root.resolve()).as_posix(),
                'duration_seconds': window, 'frames': frames, 'selection_slot': slot, 'browser': session.engine,
                **{k: settings[k] for k in ('width', 'height', 'fps')}}
        if preview_times:
            if any(t >= window for t in preview_times):
                raise NTFError('web_render_parameters', '--preview-time 须位于动画时长之内。', {'duration_seconds': window})
            job.mkdir(parents=True)
            stills, mismatched, text_report = [], [], []
            for t in preview_times:
                if text_check:
                    boxes = view.evaluate(RENDER_AND_COLLECT, t)
                    session.check()
                    image = view.screenshot(type='png', clip={'x': 0, 'y': 0, **session.size}, caret='hide')
                else:
                    image = session.frame(view, t)
                target = job / f'preview_{t:.3f}s.png'
                target.write_bytes(image)
                stills.append({'time_seconds': t, 'path': target.relative_to(project.root).as_posix()})
                if text_check:
                    issues = analyze_text(boxes, settings['width'], settings['height'])
                    entry = {'time_seconds': t, 'text_boxes': len(boxes), 'issues': issues}
                    if issues:
                        counts = {}
                        for issue in issues:
                            counts[issue['type']] = counts.get(issue['type'], 0) + 1
                        entry['counts'] = counts
                    if issues:
                        marked = _mark_issues(image, issues, dpr, job / f'text_{t:.3f}s.png')
                        if marked:
                            entry['marked_path'] = marked.relative_to(project.root).as_posix()
                    text_report.append(entry)
            fresh = session.open()  # same times in another order, after an unrelated time
            session.frame(fresh, (preview_times[0] + window * .61 + .17) % window)
            for t in reversed(preview_times):
                share = _difference(session.frame(fresh, t), (job / f'preview_{t:.3f}s.png').read_bytes())
                if share > .0005:
                    mismatched.append({'time_seconds': t, 'changed_pixel_share': round(share, 5)})
            fresh.close()
            result = {'status': 'previewed', **base, 'previews': stills, 'deterministic': not mismatched,
                      'nondeterministic': sorted(mismatched, key=lambda item: item['time_seconds'])}
            if text_check:
                result['text_check'] = text_report
            return result
        fingerprint = _fingerprint(page, {**settings, **options}, window)
        if not force:
            for asset in project.state['assets'].values():
                source = asset.get('source', {})
                if source.get('type') == 'web' and source.get('fingerprint') == fingerprint:
                    path = project.path(asset['path'])
                    if path.is_file() and file_digest(path) == asset['sha256']:
                        project.select(slot, [asset['id']])
                        return {'status': 'reused', **base, 'asset_id': asset['id'], 'path': asset['path']}
        job.mkdir(parents=True)
        partial_file = job / 'render.mp4'
        filters = []
        if dpr != 1:
            filters.append(f"scale={settings['width']}:{settings['height']}:flags=lanczos")
        if grain:
            filters.append(f'noise=alls={grain:g}:allf=t')
        encoder = subprocess.Popen(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                                    '-f', 'image2pipe', '-framerate', settings['fps_expression'], '-c:v', 'png', '-i', '-',
                                    '-an'] + (['-vf', ','.join(filters)] if filters else []) +
                                   ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '16', '-preset', 'medium',
                                    '-movflags', '+faststart', str(partial_file)],
                                   stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        fps_value = settings['fps']
        try:
            for index in range(frames):
                t = index / fps_value
                samples = [min(max(0.0, t + ((k + .5) / subframes - .5) * shutter / fps_value), window - 1e-6)
                           for k in range(subframes)] if subframes > 1 else [t]
                encoder.stdin.write(_average([session.frame(view, sample) for sample in samples]))
            encoder.stdin.close()
            stderr = encoder.stderr.read().decode(errors='replace')
            if encoder.wait(timeout=600):
                raise NTFError('media_command_failed', '动画帧编码失败。', {'stderr': stderr[-3000:]})
        finally:
            if encoder.poll() is None:
                encoder.kill()
        metadata = probe(partial_file)
        if metadata.get('has_audio') or abs(metadata['duration_seconds'] - window) > 1.1 / settings['fps']:
            raise NTFError('web_render_mismatch', '导出视频与计划时长不符。', {'expected': window, 'actual': metadata['duration_seconds']})
        destination = project.root / 'assets/videos' / ('web_' + uuid.uuid4().hex[:16] + '.mp4')
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial_file.replace(destination)
        asset = project.register_file(destination, 'video', {'type': 'web', 'scene_id': scene_id, 'page': base['page'],
                                                             'fingerprint': fingerprint}, slot)
        atomic_json(job / 'render.json', {**base, 'asset_id': asset['id'], 'fingerprint': fingerprint})
        return {'status': 'rendered', **base, **options, 'asset_id': asset['id'], 'path': asset['path']}
    finally:
        session.close()
