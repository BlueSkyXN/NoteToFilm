"""Narration estimates and measured, explicitly applied shot timing."""
from __future__ import annotations
import copy
import math
import re

from .errors import NTFError
from .media import probe


def narration_timing(project, *, mode='measured', scene_ids=None, tail_seconds=.6,
                     lead_seconds=None, min_seconds=1, max_seconds=None,
                     units_per_second=3.5, preserve_planned=False, apply=False):
    values = [tail_seconds, min_seconds, units_per_second]
    values += [v for v in (lead_seconds, max_seconds) if v is not None]
    if any(not math.isfinite(v) or v < 0 for v in values) or min_seconds < 1 or units_per_second <= 0 or (max_seconds is not None and max_seconds < min_seconds):
        raise NTFError('timing_parameters', 'Use finite, nonnegative padding and a positive timing range/rate.')
    if mode not in ('estimate', 'measured') or (apply and mode != 'measured'):
        raise NTFError('timing_mode', 'Apply requires measured audio; estimates are a design report only.')
    board = copy.deepcopy(project.storyboard)
    selected = set(scene_ids or [s['id'] for s in board['scenes']])
    if not selected or selected - {s['id'] for s in board['scenes']}:
        raise NTFError('timing_scope', 'Select existing fixed scene IDs from the storyboard.')
    rows = []
    for scene in board['scenes']:
        sid = scene['id']
        if sid not in selected:
            continue
        lead = lead_seconds
        if lead is None:
            lead = scene.get('audio', {}).get('start_seconds', scene.get('narration_start_seconds', 0))
        if not isinstance(lead, (int, float)) or not math.isfinite(lead) or lead < 0:
            raise NTFError('timing_parameters', 'Narration start must be a finite nonnegative number.')
        row = {'scene_id':sid, 'mode':mode, 'lead_seconds':lead, 'tail_seconds':tail_seconds}
        if mode == 'estimate':
            text = scene.get('speech_text', scene.get('narration', ''))
            han = len(re.findall(r'[\u3400-\u4dbf\u4e00-\u9fff]', text))
            latin = len(re.findall(r'[A-Za-z]', text))
            digits = len(re.findall(r'\d', text))
            pause = sum(text.count(k)*v for k,v in {'，':.15,'。':.3,'：':.2,'、':.1,'；':.25,'？':.3,'！':.3}.items())
            seconds = (han+latin+digits)/units_per_second+pause
            row.update(spoken_units=han+latin+digits, estimated_seconds=round(seconds,3),
                       needs_pronunciation_review=bool(latin or digits), measured=False)
        else:
            try:
                ref = project.resolve(scene.get('audio') or {'selection':f'{sid}.audio'})
            except NTFError as exc:
                raise NTFError('timing_audio_missing', 'Generate or select each scene audio before measured timing.', {'scene_id':sid}) from exc
            info = probe(project.path(ref['path']))
            seconds = info.get('audio_duration_seconds', info.get('duration_seconds'))
            if not info.get('has_audio') or not isinstance(seconds, (int,float)) or not math.isfinite(seconds) or seconds <= 0:
                raise NTFError('timing_audio_invalid', 'Selected narration has no measurable audio.', {'scene_id':sid})
            row.update(audio_seconds=seconds, audio_asset_id=ref.get('asset_id'), measured=True)
        target = max(min_seconds, math.ceil(lead+seconds+tail_seconds-1e-8))
        if preserve_planned:
            planned = scene.get('duration_seconds', 0)
            if isinstance(planned, bool) or not isinstance(planned,(int,float)) or not math.isfinite(planned) or planned < 0:
                raise NTFError('timing_parameters', 'Existing duration_seconds must be a finite nonnegative number.')
            target = max(target, math.ceil(planned))
        row.update(duration_seconds=target, requires_split=max_seconds is not None and target>max_seconds)
        rows.append(row)
        if mode == 'measured':
            scene['actual_narration_seconds'] = seconds
            scene['duration_seconds'] = target
            if scene.get('audio'):
                scene['audio']['start_seconds'] = lead
            else:
                scene['narration_start_seconds'] = lead
            if scene.get('visual_type') == 'video' and not scene.get('visuals'):
                scene.setdefault('video_parameters', {})['duration_seconds'] = target
    if apply:
        split = [r for r in rows if r['requires_split']]
        if split:
            raise NTFError('timing_requires_split', 'Some scenes exceed max-seconds; split them before applying.', {'scenes':split})
        from .compose import _settings, _transition
        fps = _settings({'output':project.document.get('output',{})})['fps']
        cursor, previous, previous_overlap, previous_duration = 0, None, 0, 0
        for scene in board['scenes']:
            duration = scene.get('duration_seconds')
            if isinstance(duration,bool) or not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<=0:
                raise NTFError('timing_incomplete', 'Every scene needs a positive duration before applying full timeline windows.')
            duration = math.ceil(duration*fps-1e-8)/fps
            transition = _transition(scene.get('transition'),fps)
            overlap = transition['duration_seconds']
            if overlap and previous is None:
                raise NTFError('transition_invalid','首镜不能与前镜重叠。')
            if overlap and (overlap >= duration or overlap+previous_overlap >= previous_duration-1e-8):
                raise NTFError('transition_too_long','转场须为每镜保留至少一帧非重叠画面。')
            start = cursor-overlap
            if overlap and not transition.get('allow_narration_overlap'):
                old_seconds = previous.get('actual_narration_seconds')
                current_seconds = scene.get('actual_narration_seconds')
                if isinstance(old_seconds,(int,float)) and isinstance(current_seconds,(int,float)):
                    old_lead=previous.get('audio',{}).get('start_seconds',previous.get('narration_start_seconds',0))
                    new_lead=scene.get('audio',{}).get('start_seconds',scene.get('narration_start_seconds',0))
                    if previous['planned_window']['start']+old_lead+old_seconds > start+new_lead+1e-6:
                        raise NTFError('transition_narration_overlap','转场会让旁白重叠；增加停顿、缩短转场或明确允许重叠。')
            scene['planned_window'] = {'start':start,'end':start+duration}
            cursor = start+duration
            previous, previous_overlap, previous_duration = scene, overlap, duration
        board['planned_total_seconds'] = cursor
        project.put_storyboard(board)
    return {'mode':mode,'applied':apply,'scenes':rows,'plan_refresh_required':apply,
            'planned_total_seconds':board.get('planned_total_seconds') if apply else None}
