"""Plan and register deterministic motion graphics from project-local media."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import uuid

from .compose import _settings
from .errors import NTFError
from .io import atomic_json, file_digest
from .media import probe
from .project import check_id
from . import motion_render


EASING = ('linear', 'smooth', 'ease_in_out', 'ease_out')
PROPERTIES = {'rect': 4, 'crop': 4, 'offset': 2, 'opacity': 0}


def number(value, label, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise NTFError('motion_invalid', f'{label} 须为有限数值。')
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise NTFError('motion_invalid', f'{label} 超出允许范围。')
    return float(value)


def vector(value, length, label):
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise NTFError('motion_invalid', f'{label} 须包含 {length} 个数值。')
    return [number(x, label) for x in value]


def rectangle(value, label, *, edges=False):
    result = vector(value, 4, label)
    width = result[2] - result[0] if edges else result[2]
    height = result[3] - result[1] if edges else result[3]
    if width < 1 or height < 1:
        raise NTFError('motion_invalid', f'{label} 的宽高须至少为 1 像素。')
    return result


def color(value):
    try:
        if isinstance(value, str):
            motion_render.ImageColor.getcolor(value, 'RGBA')
            return value
        if isinstance(value, (list, tuple)) and len(value) in (3, 4) and all(
                isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 255 for x in value):
            return list(value)
    except ValueError:
        pass
    raise NTFError('motion_invalid', '颜色须为有效颜色字符串或 RGB/RGBA 整数数组。')


def timing(raw, duration, start_key='start', end_key='end'):
    start = number(raw.get(start_key, 0), start_key, minimum=0)
    end = number(raw.get(end_key, duration), end_key, minimum=0, maximum=duration)
    if not start < end:
        raise NTFError('motion_invalid', f'{start_key} 必须早于 {end_key}。')
    return start, end


def draw_object(raw, duration):
    if not isinstance(raw, dict) or raw.get('type') not in ('rect', 'gradient', 'line', 'arrow', 'text'):
        raise NTFError('motion_invalid', '绘图对象支持 rect、gradient、line、arrow、text。')
    obj = copy.deepcopy(raw)
    kind = obj['type']
    obj['fill'] = color(obj.get('fill', '#191919'))
    if kind in ('rect', 'gradient'):
        obj['box'] = rectangle(obj.get('box'), f'{kind}.box', edges=True)
        if kind == 'gradient':
            obj['box'] = [round(x) for x in obj['box']]
            for key, default in (('alpha_start', 0), ('alpha_end', 240)):
                obj[key] = round(number(obj.get(key, default), key, minimum=0, maximum=255))
            if not isinstance(obj['fill'], str):
                raise NTFError('motion_invalid', 'gradient.fill 使用颜色字符串。')
        elif obj.get('outline') is not None:
            obj['outline'] = color(obj['outline'])
    if kind in ('rect', 'line', 'arrow'):
        obj['width'] = round(number(obj.get('width', 2), 'width', minimum=1, maximum=1024))
    if kind in ('line', 'arrow'):
        points = obj.get('points')
        if not isinstance(points, list) or len(points) < 2:
            raise NTFError('motion_invalid', '线或箭头至少需要两个 points。')
        obj['points'] = [vector(p, 2, 'points') for p in points]
        if sum(math.dist(a,b) for a,b in zip(obj['points'],obj['points'][1:])) <= 0:
            raise NTFError('motion_invalid', '线或箭头的路径长度须大于零。')
        obj['head'] = number(obj.get('head', 13), 'head', minimum=1)
        if 'reveal_start' in obj or 'reveal_end' in obj:
            obj['reveal_start'], obj['reveal_end'] = timing(obj, duration, 'reveal_start', 'reveal_end')
    if kind == 'text':
        if not isinstance(obj.get('text'), str) or not obj['text']:
            raise NTFError('motion_invalid', 'text 对象需要非空文字。')
        obj['xy'] = vector(obj.get('xy'), 2, 'text.xy')
        obj['size'] = round(number(obj.get('size', 32), 'text.size', minimum=1, maximum=1024))
        obj['leading'] = number(obj.get('leading', 1.25), 'text.leading', minimum=.1)
        if 'max_width' in obj:
            obj['max_width'] = number(obj['max_width'], 'text.max_width', minimum=1)
    return obj


def layer_plan(project, raw, duration, settings):
    if not isinstance(raw, dict) or raw.get('type') not in ('image', 'video', 'draw'):
        raise NTFError('motion_invalid', '图层 type 支持 image、video、draw。')
    layer = copy.deepcopy(raw)
    layer['start'], layer['end'] = timing(layer, duration)
    span = layer['end'] - layer['start']
    for name in ('fade_in', 'fade_out'):
        layer[name] = number(layer.get(name, 0), name, minimum=0, maximum=span)
    layer['rect'] = rectangle(layer.get('rect', [0, 0, settings['width'], settings['height']]), 'rect')
    if 'crop' in layer: layer['crop'] = rectangle(layer['crop'], 'crop', edges=True)
    if 'offset' in layer: layer['offset'] = vector(layer['offset'], 2, 'offset')
    layer['opacity'] = number(layer.get('opacity', 1), 'opacity', minimum=0, maximum=1)
    for name in ('centering', 'focus'):
        layer[name] = vector(layer.get(name, [.5,.5]), 2, name)
        if any(x < 0 or x > 1 for x in layer[name]):
            raise NTFError('motion_invalid', f'{name} 坐标使用 0 至 1 的比例。')
    layer['zoom_start'] = number(layer.get('zoom_start', 1), 'zoom_start', minimum=.01)
    layer['zoom'] = number(layer.get('zoom', 0), 'zoom')
    if layer['zoom_start'] + layer['zoom'] < .01:
        raise NTFError('motion_invalid', '结束缩放值须大于等于 0.01。')
    frames = layer.get('keyframes', [])
    if not isinstance(frames, list):
        raise NTFError('motion_invalid', 'keyframes 须为数组。')
    last = {}
    for keyframe in frames:
        if not isinstance(keyframe, dict) or set(keyframe) - {'t', 'ease', *PROPERTIES}:
            raise NTFError('motion_invalid', '关键帧支持 t、ease 和 rect/crop/offset/opacity。')
        keyframe['t'] = number(keyframe.get('t'), 'keyframe.t', minimum=0, maximum=duration)
        if keyframe.get('ease', 'smooth') not in EASING:
            raise NTFError('motion_invalid', 'ease 支持 linear、smooth、ease_in_out、ease_out。')
        if not set(keyframe).intersection(PROPERTIES):
            raise NTFError('motion_invalid', '关键帧需要至少一个可变化属性。')
        for prop in PROPERTIES:
            if prop not in keyframe: continue
            if prop in last and keyframe['t'] <= last[prop]:
                raise NTFError('motion_invalid', '同一属性的关键帧时间须严格递增。')
            last[prop] = keyframe['t']
            if prop in ('rect', 'crop'):
                keyframe[prop] = rectangle(keyframe[prop], prop, edges=prop == 'crop')
            elif prop == 'offset': keyframe[prop] = vector(keyframe[prop], 2, prop)
            else: keyframe[prop] = number(keyframe[prop], prop, minimum=0, maximum=1)
    layer['keyframes'] = frames
    if layer.get('reveal') is not None:
        reveal = layer['reveal']
        if not isinstance(reveal, dict): raise NTFError('motion_invalid', 'reveal 须为对象。')
        reveal['start'], reveal['end'] = timing(reveal, duration)
        reveal['box'] = rectangle(reveal.get('box', [0,0,settings['width'],settings['height']]), 'reveal.box', edges=True)
        if reveal.get('direction', 'right') not in ('right','left','down','up') or reveal.get('ease', 'smooth') not in EASING:
            raise NTFError('motion_invalid', 'reveal 使用 right/left/down/up 和支持的 ease。')
    if layer['type'] == 'draw':
        if not isinstance(layer.get('objects'), list): raise NTFError('motion_invalid', 'draw 图层需要 objects 数组。')
        layer['objects'] = [draw_object(obj, duration) for obj in layer['objects']]
    else:
        if not isinstance(layer.get('path'), str) or not layer['path']:
            raise NTFError('motion_invalid', '图片和视频图层需要项目内 path、asset_id 或 selection。')
        source = project.path(layer.get('path'))
        metadata = probe(source)
        if metadata['kind'] != layer['type']:
            raise NTFError('motion_invalid', '图层 type 与实际媒体类型不符。')
        layer.update(path=str(source), source_size=[metadata['width'],metadata['height']], source_sha256=file_digest(source))
        if layer['type'] == 'video':
            layer['speed'] = number(layer.get('speed',1), 'speed', minimum=.01, maximum=100)
            layer['trim_start'] = number(layer.get('trim_start',0), 'trim_start', minimum=0)
            required = math.ceil(span*settings['fps']-1e-8)/settings['fps']*layer['speed']
            if layer['trim_start'] + required > metadata['duration_seconds'] + 1e-6:
                raise NTFError('motion_source_short', '视频图层所需区间超过源片；调整 start/end、trim_start 或 speed。')
    return layer


def plan_motion(project, manifest, *, scene_ids=None, stage='all', select_prefix='motion', preview_time=None):
    if motion_render.Image is None:
        raise NTFError('render_dependency_missing', '动效需要 render 依赖中的 Pillow，请使用已有可用运行入口。')
    if not isinstance(manifest, dict) or manifest.get('schema_version',1) != 1 or not isinstance(manifest.get('scenes'), list) or not manifest['scenes']:
        raise NTFError('motion_invalid', '动效清单需要 schema_version:1 和非空 scenes。')
    if stage not in ('all','picture','annotate'): raise NTFError('motion_invalid', 'stage 支持 all、picture、annotate。')
    check_id(select_prefix, 'selection prefix')
    resolved = project.resolve(manifest)
    output = dict(project.document.get('output', {}))
    raw_output = resolved.get('output', {})
    if not isinstance(raw_output, dict): raise NTFError('motion_invalid', 'output 须为对象。')
    for key in ('width','height','fps'):
        if key in resolved: output[key] = resolved[key]
    output.update(raw_output)
    checked = _settings({'output':output})
    settings = {key:checked[key] for key in ('width','height','fps','fps_expression')}
    font = resolved.get('font_file', output.get('subtitle_font_file'))
    if font:
        if not isinstance(font,str): raise NTFError('motion_invalid', 'font_file 须为字体路径。')
        font = Path(font).expanduser()
        font = (font if font.is_absolute() else project.root/font).resolve()
    settings['font_file'] = str(font) if font else None
    font_index = resolved.get('font_index', output.get('subtitle_font_index', 0))
    if isinstance(font_index, bool) or not isinstance(font_index, int) or font_index < 0:
        raise NTFError('motion_invalid', 'font_index 须为非负整数（字体合集中的字形序号）。')
    if font_index:
        settings['font_index'] = font_index   # 只在非默认值时写入，旧动效的复用指纹不变
    scenes, seen = [], set()
    for raw in resolved['scenes']:
        if not isinstance(raw,dict): raise NTFError('motion_invalid', '每个 scene 须为对象。')
        sid = check_id(raw.get('id'),'scene ID')
        if sid in seen: raise NTFError('duplicate_scene', '动效镜头 ID 重复。')
        seen.add(sid)
        if scene_ids and sid not in scene_ids: continue
        duration = number(raw.get('duration_seconds',raw.get('duration')), 'duration_seconds', minimum=.001)
        if 'duration_seconds' in raw and 'duration' in raw and raw['duration'] != duration:
            raise NTFError('motion_invalid', 'duration 与 duration_seconds 同时出现时须一致。')
        frame_count = math.ceil(duration*settings['fps']-1e-8)
        window = frame_count/settings['fps']
        layers = raw.get('layers')
        if not isinstance(layers,list): raise NTFError('motion_invalid', 'scene.layers 须为数组。')
        if stage == 'picture': layers = [l for l in layers if not isinstance(l,dict) or l.get('type') != 'draw']
        if stage == 'annotate':
            picture = project.resolve({'selection':f'{select_prefix}.{sid}.picture'})
            layers = [{'type':'video','path':picture['path'],'start':0,'end':window}] + [l for l in layers if isinstance(l,dict) and l.get('type') == 'draw']
        scene = {'id':sid, 'requested_duration_seconds':duration, 'duration_seconds':window, 'duration':window,
                 'frames':frame_count, 'background':color(raw.get('background','#f3f3f3')),
                 'layers':[layer_plan(project,l,window,settings) for l in layers]}
        at = preview_time if preview_time is not None else raw.get('preview_time',min(window*.62,(frame_count-1)/settings['fps']))
        scene['preview_time'] = number(at, 'preview_time', minimum=0)
        if scene['preview_time'] >= window: raise NTFError('motion_invalid', 'preview_time 须位于镜头窗口内。')
        scene['selection_slot'] = check_id(f'{select_prefix}.{sid}'+('.picture' if stage == 'picture' else ''),'selection slot')
        scenes.append(scene)
    if scene_ids and set(scene_ids)-seen:
        raise NTFError('unknown_scene', '指定的动效镜头 ID 不在清单中。', {'scene_ids':sorted(set(scene_ids)-seen)})
    uses_text = any(obj['type']=='text' for scene in scenes for layer in scene['layers'] for obj in layer.get('objects',[]))
    if uses_text:
        if not font or not font.is_file(): raise NTFError('font_missing', '文字图层需要可读取的 font_file。')
        try: motion_render.ImageFont.truetype(str(font),32,index=font_index)
        except OSError as exc: raise NTFError('font_invalid','无法读取 font_file 字体，或 font_index 超出字体合集范围。') from exc
        settings['font_sha256'] = file_digest(font)
    else:
        settings['font_file'] = None
        settings.pop('font_index', None)
    return {'schema_version':1,'stage':stage,'settings':settings,'scenes':scenes,'audio':'silent visuals; compose handles audio'}


def motion_project(project, manifest, *, scene_ids=None, stage='all', select_prefix='motion',
                   plan_only=False, preview_only=False, preview_time=None, force=False):
    plan = plan_motion(project,manifest,scene_ids=scene_ids,stage=stage,select_prefix=select_prefix,preview_time=preview_time)
    if plan_only: return {'status':'planned',**plan}
    job = project.root/'work'/('motion_'+uuid.uuid4().hex[:12])
    job.mkdir(parents=True)
    atomic_json(job/'plan.json',plan)
    implementation = file_digest(Path(__file__)) + file_digest(Path(motion_render.__file__))
    assets = project.state['assets']
    results = []
    for scene in plan['scenes']:
        recipe = {k:v for k,v in scene.items() if k not in ('preview_time','selection_slot')}
        fingerprint = hashlib.sha256(json.dumps({'scene':recipe,'settings':plan['settings'],'stage':stage,
                                                 'renderer':implementation},sort_keys=True).encode()).hexdigest()
        reused = None
        if not force and not preview_only:
            for asset in assets.values():
                if asset.get('source',{}).get('type')=='motion' and asset['source'].get('fingerprint')==fingerprint:
                    path=project.path(asset['path'])
                    if path.is_file() and file_digest(path)==asset['sha256']:
                        reused=asset; break
        preview = job/(scene['id']+'.jpg')
        partial = job/(scene['id']+'.partial.mp4')
        try:
            motion_render.render_motion(scene,plan['settings'],partial,preview,preview_only=preview_only or bool(reused))
            row={'scene_id':scene['id'],'preview_path':preview.relative_to(project.root).as_posix(),
                 'duration_seconds':scene['duration'],'selection_slot':scene['selection_slot']}
            if preview_only:
                row['status']='previewed'
            elif reused:
                project.select(scene['selection_slot'],[reused['id']])
                row.update(status='reused',asset_id=reused['id'],path=reused['path'])
            else:
                metadata=probe(partial)
                if metadata.get('has_audio') or abs(metadata['duration_seconds']-scene['duration']) > 1.1/plan['settings']['fps']:
                    raise NTFError('motion_render_mismatch','动效成片与计划时长或音轨约定不符。')
                destination=project.root/'assets/videos'/('motion_'+uuid.uuid4().hex[:16]+'.mp4')
                partial.replace(destination)
                asset=project.register_file(destination,'video',{'type':'motion','scene_id':scene['id'],
                                            'stage':stage,'fingerprint':fingerprint},scene['selection_slot'])
                row.update(status='rendered',asset_id=asset['id'],path=asset['path'])
            results.append(row)
        except NTFError as exc:
            exc.details.update(completed=results,plan_path=(job/'plan.json').relative_to(project.root).as_posix())
            raise
    return {'status':'previewed' if preview_only else 'complete','stage':stage,'scenes':results,
            'plan_path':(job/'plan.json').relative_to(project.root).as_posix()}
