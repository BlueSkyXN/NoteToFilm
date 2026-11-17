"""Export only review media and a standalone HTML page, without project secrets."""
from __future__ import annotations
import html
import json
import math
from pathlib import Path
import shutil
import sys
import uuid

from .errors import NTFError
from .inspection import inspect_media
from .io import atomic_json
from .media import probe


def _timeline(value, duration=None, fps=30):
    if not isinstance(value, dict) or not isinstance(value.get('scenes'), list):
        raise NTFError('preview_timeline_invalid', '时间表须包含 scenes 数组。')
    windows = {}
    last_start = -1
    tolerance = max(.1, 1.1 / fps)
    for scene in value['scenes']:
        if not isinstance(scene, dict) or not isinstance(scene.get('id'), str) or not scene['id'] or scene['id'] in windows:
            raise NTFError('preview_timeline_invalid', '时间表中的镜头 ID 必须唯一且非空。')
        start, end = scene.get('start_seconds'), scene.get('end_seconds')
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (start, end)):
            raise NTFError('preview_timeline_invalid', '镜头窗口须使用有限的秒数。')
        if not 0 <= start < end or start < last_start or (duration is not None and end > duration + tolerance):
            raise NTFError('preview_timeline_mismatch', '时间表的镜头顺序或窗口与最终视频不符。')
        windows[scene['id']] = (start, end)
        last_start = start
    total = value.get('duration_seconds')
    if duration is not None and (isinstance(total, bool) or not isinstance(total, (int, float)) or
                                 not math.isfinite(total) or abs(total - duration) > tolerance):
        raise NTFError('preview_timeline_mismatch', '时间表总时长与最终视频不符，请选择对应版本。')
    return windows


def export_preview(project, *, output=None, video=None, render_id=None, timeline_file=None, max_width=960, jpeg_quality=80):
    if video and render_id:
        raise NTFError('preview_parameters', 'Select either --video or --render, not both.')
    if timeline_file and not video:
        raise NTFError('preview_parameters', '--timeline 必须与明确的 --video 一起使用。')
    state=project.state
    renders=state.get('renders',{})
    record={}
    if render_id:
        if render_id not in renders:
            raise NTFError('preview_render_missing', 'The requested render ID is not in this project.')
        record=renders[render_id]
    elif not video:
        completed=[r for r in renders.values() if r.get('video_path') and project.path(r['video_path']).is_file()]
        if completed:record=max(completed,key=lambda r:r.get('created_at',''))
    movie=Path(video).expanduser().resolve() if video else (project.path(record['video_path']) if record.get('video_path') else None)
    info=probe(movie) if movie else None
    if movie and info['kind']!='video':
        raise NTFError('preview_parameters', '--video must be an actual video file.')
    timeline={}
    if timeline_file:
        timeline=json.loads(Path(timeline_file).expanduser().resolve().read_text(encoding='utf-8'))
    elif record.get('timeline_path'):
        timeline=json.loads(project.path(record['timeline_path']).read_text())
    windows=_timeline(timeline, info['duration_seconds'] if info else None, info.get('fps',30) if info else 30) if timeline else {}
    storyboard = project.storyboard.get('scenes',[])
    if timeline_file and storyboard and set(windows) != {scene['id'] for scene in storyboard}:
        raise NTFError('preview_timeline_mismatch', '时间表与正式分镜的镜头 ID 不一致，请同步分镜或选择对应时间表。')
    if timeline_file:
        by_id={scene['id']:scene for scene in storyboard}
        storyboard=[by_id.get(scene['id'], {'id':scene['id']}) for scene in timeline['scenes']]
    directory=Path(output).expanduser().resolve() if output else project.root/'views'/('preview_'+uuid.uuid4().hex[:10])
    if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
        raise NTFError('output_exists', 'Choose an empty preview directory; existing pages are preserved.')
    directory.mkdir(parents=True,exist_ok=True)
    if movie:
        shutil.copyfile(movie,directory/'movie.mp4')
        inspect_media(movie,output=directory/'poster',frames=1,max_width=max_width,jpeg_quality=jpeg_quality,write_report=False)
    rows=[];identities={}
    for number,scene in enumerate(storyboard,1):
        sid=scene['id'];source=None;identity=None
        refs=scene.get('visuals')
        if not refs:
            slots=[f'{sid}.video',f'{sid}.image']+[a['selection_slot'] for a in project.plan['actions'] if a.get('scene_id')==sid and a.get('selection_slot') and a['kind'] in ('image','video')]
            slot=next((k for k in slots if k in state['selection']),None)
            if slot:refs=[{'selection':slot}]
            elif scene.get('review',{}).get('reference_asset_id'):refs=[{'asset_id':scene['review']['reference_asset_id']}]
        if refs:
            try:
                resolved=project.resolve(refs)[0]
                source=project.path(resolved['path']);identity=(resolved.get('sha256'),scene.get('review',{}).get('crop','center'))
            except NTFError:
                source=None
        window=windows.get(sid)
        if window is None and scene.get('planned_window'):
            window=(scene['planned_window']['start'],scene['planned_window']['end'])
        at=None
        if movie and window and 0<=window[0]<window[1]<=info['duration_seconds']+.1:
            source=movie;at=[min(info['duration_seconds']-.01,(window[0]+window[1])/2)]
        thumb=None
        if source:
            folder=directory/f'scene_{number:02d}'
            inspected=inspect_media(source,output=folder,frames=1,max_width=max_width,jpeg_quality=jpeg_quality,at_seconds=at,write_report=False)
            if inspected['previews']:thumb=Path(inspected['previews'][0]['path']).relative_to(directory).as_posix()
        row={'number':number,'scene_id':sid,'title':scene.get('title',sid),'narration':scene.get('narration',''),
             'start_seconds':window[0] if window else None,'end_seconds':window[1] if window else None,'thumbnail':thumb}
        rows.append(row)
        if identity and identity[0]:identities.setdefault(identity,[]).append(sid)
    reused=[ids for ids in identities.values() if len(ids)>1]
    cards=[]
    for r in rows:
        thumb=f'<img src="{r["thumbnail"]}" alt="分镜预览">' if r['thumbnail'] else '<div class="missing">素材待选</div>'
        start=f' data-start="{r["start_seconds"]}"' if movie and r['start_seconds'] is not None else ''
        cards.append(f'<button{start}>{thumb}<b>{r["number"]:02d} · {html.escape(r["title"])}</b><p>{html.escape(r["narration"])}</p></button>')
    player='<video id="film" controls playsinline preload="metadata" poster="poster/frame_01.jpg" src="movie.mp4"></video><p><a href="movie.mp4" download>下载MP4</a></p>' if movie else ''
    title=html.escape(project.document.get('title','视频项目'))
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title><style>body{max-width:1180px;margin:30px auto;padding:0 22px;background:#131b22;color:#e5ecec;font:15px/1.65 sans-serif}h1{font-size:28px}video{display:block;width:100%;background:#000}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}button{padding:0;background:#1d2a33;border:1px solid #41505c;color:#e4e9e8;text-align:left;cursor:pointer}img,.missing{display:block;width:100%;aspect-ratio:16/9;object-fit:cover}.missing{display:grid;place-items:center;color:#a7b7be}button b,button p{display:block;margin:10px 12px}button p{font-size:12px;color:#afbec6}a{color:#cdb482}.meta{color:#afbec6}@media(max-width:780px){.grid{grid-template-columns:repeat(2,1fr)}}</style><h1>__TITLE__</h1><p class="meta">__META__</p>__PLAYER__<div class="grid">__CARDS__</div><script>let v=document.getElementById('film');document.querySelectorAll('[data-start]').forEach(b=>b.onclick=()=>{v.currentTime=Number(b.dataset.start);v.play()});</script></html>'''
    meta=f'{len(rows)} 幕'+(f' · {info["duration_seconds"]:.2f} 秒 · {info["width"]}×{info["height"]}' if info else ' · 分镜预览')
    (directory/'review.html').write_text(page.replace('__TITLE__',title).replace('__META__',meta).replace('__PLAYER__',player).replace('__CARDS__',''.join(cards)))
    bundle={'scene_count':len(rows),'movie':'movie.mp4' if movie else None,'scenes':rows,'reused_source_groups':reused}
    atomic_json(directory/'review-data.json',bundle)
    source_cli=Path(__file__).resolve().parents[2]/'scripts/ntf.py'
    if getattr(sys,'frozen',False):
        command=[sys.executable]
    else:
        command=[sys.executable,str(source_cli)] if source_cli.is_file() else [sys.executable,'-m','notetofilm_local']
    return {'page':str(directory/'review.html'),'directory':str(directory),**bundle,
            'serve_argv':command+['serve','--port','0','--directory',str(directory)]}
