"""Narration estimates and measured, explicitly applied shot timing."""
from __future__ import annotations
import copy
import json
import math
import os
import re
import tempfile

from .errors import NTFError
from .media import probe


# Calibrated on zh-CN-XiaoxiaoNeural narration (2026-11, ten measured scenes, mean error about 4%):
# about 4.6 spoken units per second at rate +0%; a Latin word counts as two units.
BASE_UNITS_PER_SECOND = 4.6
LATIN_WORD_UNITS = 2


def _rate_factor(rate):
    match = re.fullmatch(r'\s*([+-]?\d+(?:\.\d+)?)\s*%\s*', str(rate or '+0%'))
    return max(.2, 1 + float(match.group(1)) / 100) if match else 1.0


def narration_timing(project, *, mode='measured', scene_ids=None, tail_seconds=.6,
                     lead_seconds=None, min_seconds=1, max_seconds=None,
                     units_per_second=None, preserve_planned=False, apply=False):
    values = [tail_seconds, min_seconds] + ([units_per_second] if units_per_second is not None else [])
    values += [v for v in (lead_seconds, max_seconds) if v is not None]
    if any(not math.isfinite(v) or v < 0 for v in values) or min_seconds < 1 or (units_per_second is not None and units_per_second <= 0) or (max_seconds is not None and max_seconds < min_seconds):
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
            latin = len(re.findall(r'[A-Za-z]+', text)) * LATIN_WORD_UNITS
            digits = len(re.findall(r'\d', text))
            pause = sum(text.count(k)*v for k,v in {'，':.15,'。':.3,'：':.2,'、':.1,'；':.25,'？':.3,'！':.3}.items())
            rate = scene.get('rate', project.document.get('defaults', {}).get('rate', '+0%'))
            speed = units_per_second if units_per_second is not None else BASE_UNITS_PER_SECOND * _rate_factor(rate)
            seconds = (han+latin+digits)/speed+pause
            row.update(spoken_units=han+latin+digits, units_per_second=round(speed, 3), estimated_seconds=round(seconds,3),
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


_TIMING_JS_HELPERS = """export const DUR = TL.dur;
export const SC = Object.fromEntries(TL.scenes.map(s => [s.id, s]));
/** 某镜第 n 次说到 word 的绝对时刻（秒）。词边界缺失的镜头用 SC[id].voice 或 SC[id].start 加秒数。 */
export function W(id, word, n = 1) {
  const hits = (SC[id]?.words || []).filter(w => w[0] === word);
  if (hits.length < n) throw new Error(`${id} 里没有第 ${n} 个“${word}”`);
  return hits[n - 1][1];
}
const _bare = s => String(s).replace(/[\\s，。、：；！？“”‘’（）《》,.:;!?"'()\\-—·]/g, '');
/** 某镜第 n 次说到短语 phrase 的时刻：从某个词的开头起，连续几个词拼起来以 phrase 开头（忽略空格和标点）。
 *  “取件码”能落在“取件”“码”两个词上，“120”能落在“120 个”上；“能”不会落在“功能”上。找不到就报错。 */
export function P(id, phrase, n = 1) {
  const words = SC[id]?.words || [], want = _bare(phrase);
  let seen = 0;
  for (let i = 0; i < words.length && want; i++) {
    let joined = '';
    for (let j = i; j < words.length && joined.length < want.length; j++) joined += _bare(words[j][0]);
    if (_bare(words[i][0]) && joined.startsWith(want) && ++seen === n) return words[i][1];
  }
  throw new Error(`${id} 里没有第 ${n} 处从词首开始的“${phrase}”`);
}
"""


def export_timing_js(project, output):
    """Write a timing module for code-animation pages: scene windows from the storyboard and word times from the
    adopted narration's word boundaries, all in seconds from the start of the film."""
    board = project.storyboard
    scenes = board.get('scenes', [])
    if not scenes or any(not isinstance(s.get('planned_window'), dict) for s in scenes):
        raise NTFError('timing_windows_missing', '导出 timing.js 需要每镜的 planned_window：先运行 ntf timing PROJECT --apply。')
    target = project.path(output)
    if target.suffix != '.js':
        raise NTFError('timing_parameters', '--js 写到项目内的 .js 文件，例如 animation/film/timing.js。')
    rows, without_words = [], []
    for scene in scenes:
        sid, window = scene['id'], scene['planned_window']
        start, end = float(window['start']), float(window['end'])
        row = {'id': sid, 'start': round(start, 3), 'dur': round(end - start, 3), 'voice': None, 'words': []}
        lead = (scene.get('audio') or {}).get('start_seconds', scene.get('narration_start_seconds', 0))
        try:
            ref = project.resolve(scene.get('audio') or {'selection': f'{sid}.audio'})
        except NTFError:
            ref = None
        if ref is not None:
            row['voice'] = round(start + lead, 3)
            path = ref.get('boundaries_path')
            words = json.loads(project.path(path).read_text(encoding='utf-8')) if path else []
            row['words'] = [[w['text'], round(start + lead + w['offset'] / 1e7, 3)]
                            for w in words if isinstance(w, dict) and 'text' in w and 'offset' in w]
            if not row['words']:
                without_words.append(sid)
        rows.append(row)
    total = board.get('planned_total_seconds') or max(r['start'] + r['dur'] for r in rows)
    timeline = {'dur': round(float(total), 3), 'scenes': rows}
    text = ('// 由 ntf timing PROJECT --js 生成：镜头窗口取自正式分镜，逐词时间取自所采用配音的词边界（秒，从片头算起）。\n'
            '// 改旁白或重新 --apply 后重新导出，不手改。\n'
            f'export const TL = {json.dumps(timeline, ensure_ascii=False)};\n' + _TIMING_JS_HELPERS)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(prefix='.timing-', suffix='.js', dir=target.parent)
    with os.fdopen(handle, 'w', encoding='utf-8') as fh:
        fh.write(text)
    os.replace(temp, target)
    return {'path': target.relative_to(project.root).as_posix(), 'duration_seconds': timeline['dur'],
            'scenes': len(rows), 'words': sum(len(r['words']) for r in rows), 'scenes_without_words': without_words}
