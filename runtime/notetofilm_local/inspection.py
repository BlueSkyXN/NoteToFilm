"""Actual media inspection and compressed JPEG review frames."""
from __future__ import annotations
import math
import re
import json
from pathlib import Path

from .errors import NTFError
from .io import atomic_json
from .media import probe, run_media_command


_NUMBER = r'(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)'
_SCAN_AUDIO_FORMAT = 'aformat=sample_fmts=dbl'


def _intervals(starts, ends, duration):
    result = []
    for i, start in enumerate(starts):
        end = ends[i] if i < len(ends) else duration
        result.append({'start_seconds': round(max(0.0, start), 3), 'end_seconds': round(min(end, duration), 3)})
    return result


def _add_overlap(pauses, intervals, field):
    index = 0
    for pause in pauses:
        total = 0.0
        while index < len(intervals):
            span = intervals[index]
            if span['start_seconds'] >= pause['end_seconds']:
                break
            total += max(0.0, min(pause['end_seconds'], span['end_seconds'])
                         - max(pause['start_seconds'], span['start_seconds']))
            if span['end_seconds'] > pause['end_seconds']:
                break
            index += 1
        pause[field] = round(total, 3)


def _scan_audio_pauses(log, duration, input_args, audio_map, filters):
    # FFmpeg 6 logs the filter class instead of the instance name. Read each detector separately on that build.
    unnamed_events = re.search(r'\[silencedetect @ [^\]]+\]\s+silence_start:', log)

    def intervals(name):
        detector_log = log
        event = rf'\[silencedetect@{name} @ [^\]]+\]\s+silence_'
        if unnamed_events:
            detector_log = run_media_command(
                input_args + audio_map + ['-vn', '-af', f'{_SCAN_AUDIO_FORMAT},{filters[name]}', '-f', 'null', '-'],
                timeout=900,
            ).stderr
            event = r'\bsilence_'
        return _intervals([float(v) for v in re.findall(event + 'start: ' + _NUMBER, detector_log)],
                          [float(v) for v in re.findall(event + 'end: ' + _NUMBER, detector_log)], duration)

    pauses = intervals('pause')
    if pauses:
        _add_overlap(pauses, intervals('near'), 'near_silence_seconds')
        _add_overlap(pauses, intervals('zero'), 'digital_silence_seconds')
    return pauses


def scan_media(source, info, *, freeze_seconds=1.0, silence_seconds=.5, timeline=None):
    """Report frozen, black and silent intervals as places worth looking at; never a pass/fail verdict."""
    if info['kind'] != 'video' or not info.get('duration_seconds'):
        raise NTFError('inspect_parameters', '--scan 只处理可测得时长的视频。')
    if any(not math.isfinite(v) or v <= 0 for v in (freeze_seconds, silence_seconds)):
        raise NTFError('inspect_parameters', '冻结与静音的最短时长须为正数。')
    duration = info['duration_seconds']
    input_args = ['ffmpeg', '-hide_banner', '-nostdin', '-i', str(source)]
    args = input_args + ['-vf', f'freezedetect=n=-60dB:d={freeze_seconds:g},blackdetect=d=0.2:pix_th=0.10',
                         '-map', f"0:{info.get('video_stream_index', 'V:0')}"]
    filters = {
        'pause': f'silencedetect=n=-35dB:d={silence_seconds:g}',
        'near': 'silencedetect=n=-70dB:d=0.2',
        # Map each decoded channel sample to 0 (exact zero) or 1 before measuring zero runs.
        'zero': r'aeval=not(eq(val(ch)\,0)):c=same,silencedetect=n=0.5:d=0.001',
    }
    audio_map = ['-map', f"0:{info.get('audio_stream_index', 'a:0')}"] if info.get('has_audio') else []
    if audio_map:
        named_filters = ','.join(value.replace('silencedetect=', f'silencedetect@{name}=')
                                 for name, value in filters.items())
        args += audio_map + ['-af', f'{_SCAN_AUDIO_FORMAT},{named_filters}']
    else:
        args += ['-an']
    log = run_media_command(args + ['-f', 'null', '-'], timeout=900).stderr
    found = {
        'freeze': _intervals([float(v) for v in re.findall(r'freeze_start: ' + _NUMBER, log)],
                             [float(v) for v in re.findall(r'freeze_end: ' + _NUMBER, log)], duration),
        'black': [{'start_seconds': round(float(a), 3), 'end_seconds': round(float(b), 3)}
                  for a, b in re.findall(r'black_start:' + _NUMBER + r' black_end:' + _NUMBER, log)],
        'silence': _scan_audio_pauses(log, duration, input_args, audio_map, filters) if audio_map else None,
    }
    if timeline:
        from .io import read_json
        from .preview import _timeline
        windows = _timeline(read_json(timeline), duration, info.get('fps') or 30)
        for items in found.values():
            for item in items or []:
                item['scene_ids'] = [sid for sid, (a, b) in windows.items()
                                     if a < item['end_seconds'] and b > item['start_seconds']]
    found['thresholds'] = {'freeze_seconds': freeze_seconds, 'black_seconds': .2,
                           'silence_seconds': silence_seconds if info.get('has_audio') else None,
                           'silence_db': -35 if info.get('has_audio') else None,
                           'near_silence_db': -70 if info.get('has_audio') else None,
                           'near_silence_min_seconds': .2 if info.get('has_audio') else None,
                           'digital_silence_min_seconds': .001 if info.get('has_audio') else None}
    return found


def inspect_media(source, *, decode=False, output=None, frames=3, max_width=960, jpeg_quality=80,
                  at_seconds=None, write_report=True, expected_width=None, expected_height=None,
                  expected_fps=None, expected_duration=None, duration_tolerance=.1,
                  expect_audio=None, audio_check=False, min_mean_dbfs=-60, max_peak_dbfs=-.1,
                  expected_loudness_lufs=None, loudness_tolerance=1,
                  scan=False, freeze_seconds=1.0, silence_seconds=.5, timeline=None):
    source = Path(source).expanduser().resolve()
    if frames < 1 or frames > 30 or max_width < 16 or max_width > 4096 or not 1<=jpeg_quality<=95:
        raise NTFError('inspect_parameters', 'Use 1–30 frames, width 16–4096, and JPEG quality 1–95.')
    info = probe(source)
    expected = [v for v in (expected_width, expected_height, expected_fps, expected_duration) if v is not None]
    if any(not math.isfinite(v) or v <= 0 for v in expected) or not math.isfinite(duration_tolerance) or duration_tolerance < 0:
        raise NTFError('inspect_parameters', 'Expected dimensions, fps and duration must be positive; tolerance must be finite and nonnegative.')
    if not all(math.isfinite(v) for v in (min_mean_dbfs,max_peak_dbfs)) or min_mean_dbfs > 0 or max_peak_dbfs > 0:
        raise NTFError('inspect_parameters', 'Audio level limits must be finite dBFS values at or below zero.')
    if not math.isfinite(loudness_tolerance) or loudness_tolerance < 0 or (expected_loudness_lufs is not None and (not math.isfinite(expected_loudness_lufs) or expected_loudness_lufs > 0)):
        raise NTFError('inspect_parameters','Expected loudness must be finite LUFS at or below zero; tolerance must be nonnegative.')
    if at_seconds and (info['kind']!='video' or any(not math.isfinite(t) or t<0 or t>=info.get('duration_seconds',0) for t in at_seconds)):
        raise NTFError('inspect_parameters', 'Requested frame times must lie inside a measurable video.')
    result = {'media':info, 'full_decode':'not_requested', 'previews':[]}
    checks = []
    def check(name, passed, wanted, actual):
        checks.append({'name':name,'passed':bool(passed),'expected':wanted,'actual':actual})
    for name,wanted in (('width',expected_width),('height',expected_height)):
        if wanted is not None:
            check(name,info.get(name)==wanted,wanted,info.get(name))
    if expected_fps is not None:
        check('fps',abs(info.get('fps',0)-expected_fps)<=.01,expected_fps,info.get('fps'))
    if expected_duration is not None:
        check('duration_seconds',abs(info.get('duration_seconds',0)-expected_duration)<=duration_tolerance,
              {'value':expected_duration,'tolerance':duration_tolerance},info.get('duration_seconds'))
    if expect_audio is not None:
        check('has_audio',bool(info.get('has_audio'))==expect_audio,expect_audio,bool(info.get('has_audio')))
    if decode:
        run_media_command(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-i',str(source),'-f','null','-'], timeout=600)
        result['full_decode'] = 'passed'
        check('full_decode',True,'passed','passed')
    if audio_check or expected_loudness_lufs is not None:
        check('audible_audio_present',bool(info.get('has_audio')),True,bool(info.get('has_audio')))
        if info.get('has_audio'):
            measured = run_media_command(['ffmpeg','-hide_banner','-nostdin','-i',str(source),'-vn','-af',
                'volumedetect,loudnorm=I=-24:TP=-2:LRA=9:print_format=json','-f','null','-'], timeout=600)
            levels = {}
            for name,value in re.findall(r'(mean_volume|max_volume):\s*(-?(?:[0-9.]+|inf)) dB',measured.stderr):
                number = float(value)
                levels[name] = number if math.isfinite(number) else None
            if not {'mean_volume','max_volume'} <= levels.keys():
                raise NTFError('audio_measurement_failed','FFmpeg returned no usable audio level measurements.')
            result['audio_levels_dbfs'] = levels
            block = re.search(r'\{\s*"input_i"[\s\S]*?\}',measured.stderr)
            if not block:
                raise NTFError('audio_measurement_failed','FFmpeg returned no usable loudness measurement.')
            loudness = json.loads(block.group())
            def finite_level(value):
                number = float(value)
                return number if math.isfinite(number) else None
            integrated = finite_level(loudness['input_i'])
            result['audio_loudness'] = {'integrated_lufs':integrated,'true_peak_db':finite_level(loudness['input_tp'])}
            if expected_loudness_lufs is not None:
                check('integrated_loudness_lufs',integrated is not None and abs(integrated-expected_loudness_lufs)<=loudness_tolerance,
                      {'value':expected_loudness_lufs,'tolerance':loudness_tolerance},integrated)
            check('mean_volume_dbfs',levels['mean_volume'] is not None and levels['mean_volume']>=min_mean_dbfs,
                  {'minimum':min_mean_dbfs},levels['mean_volume'])
            check('max_volume_dbfs',levels['max_volume'] is None or levels['max_volume']<=max_peak_dbfs,
                  {'maximum':max_peak_dbfs},levels['max_volume'])
    if scan:
        result['scan'] = scan_media(source, info, freeze_seconds=freeze_seconds,
                                    silence_seconds=silence_seconds, timeline=timeline)
    result['verification'] = {'passed':all(c['passed'] for c in checks) if checks else None,'checks':checks}
    if output is None:
        return result
    output = Path(output).expanduser().resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise NTFError('output_exists', 'Choose an empty inspection output directory to preserve earlier previews.')
    if source.is_relative_to(output):
        raise NTFError('output_input_collision', 'Inspection output must not contain its source file.')
    output.mkdir(parents=True,exist_ok=True)
    times = []
    if info['kind']=='image':
        times = [None]
    elif info['kind']=='video':
        duration = info.get('duration_seconds',0)
        if duration<=0:
            raise NTFError('media_duration_unknown', 'Video duration is unavailable.')
        times = list(at_seconds) if at_seconds else ([duration/2] if frames==1 else [min(max(0,duration-.01),max(0,.2+(duration-.4)*i/(frames-1))) for i in range(frames)])
    quality = max(2,min(31,round(31-jpeg_quality*29/95)))
    for i,t in enumerate(times,1):
        target=output/f'frame_{i:02d}.jpg'
        args=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y']
        if t is not None:args += ['-ss',str(round(t,6))]
        args += ['-i',str(source),'-frames:v','1','-vf',f"scale='min(iw,{max_width})':-2",'-q:v',str(quality),str(target)]
        run_media_command(args)
        result['previews'].append({'path':str(target),'requested_time_seconds':t})
    if write_report:
        atomic_json(output/'inspection.json',result)
    return result
