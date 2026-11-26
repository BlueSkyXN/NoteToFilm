"""Actual media inspection and compressed JPEG review frames."""
from __future__ import annotations
import math
import operator
import re
import json
import statistics
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


def _parse_holds(holds):
    parsed = []
    for item in holds or []:
        try:
            start, end = (float(v) for v in str(item).split('-', 1))
        except ValueError:
            raise NTFError('inspect_parameters', f'--hold 写成 开始-结束 的秒数，例如 16.8-20：{item}') from None
        if not (math.isfinite(start) and math.isfinite(end)) or start < 0 or end <= start:
            raise NTFError('inspect_parameters', f'--hold 的结束须晚于开始：{item}')
        parsed.append((start, end))
    return parsed


def _bright_share(source, at, stream):
    """Share of pixels above 25 % luma in one small grey frame: a dark frame with titles is not an empty one."""
    done = run_media_command(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-ss', f'{at:.3f}', '-i', str(source),
                              '-map', f'0:{stream}', '-frames:v', '1', '-vf', 'scale=160:90,format=gray', '-f', 'rawvideo', '-'],
                             timeout=120, text=False)
    pixels = done.stdout or b''
    return round(sum(1 for v in pixels if v > 64) / len(pixels), 4) if pixels else None


# 低运动：把画面缩成 64×36 灰度、每秒 10 帧，相邻两帧平均像素差（0–255）的 0.5 秒滑动中位数低于 1.2，且连续至少 1.5 秒。
# 缩小加中位数后，字幕出现、标签切换这类一闪而过的变化不算运动；推拉、人物动作这类持续的变化量得出。剪点处断开。
_PACE = {'fps': 10, 'width': 64, 'height': 36, 'level': 1.2, 'seconds': 1.5, 'cut_score': .3, 'cut_merge': .4}


def _motion_pace(source, stream, duration, level=None, seconds=None):
    """Low-motion intervals and shot lengths: a still picture with changing captions is not frozen, but it is not moving either."""
    fps, w, h = _PACE['fps'], _PACE['width'], _PACE['height']
    level = _PACE['level'] if level is None else level
    seconds = _PACE['seconds'] if seconds is None else seconds
    raw = run_media_command(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-i', str(source), '-map', f'0:{stream}',
                             '-vf', f'fps={fps},scale={w}:{h}:flags=area,format=gray', '-f', 'rawvideo', '-'],
                            timeout=900, text=False).stdout or b''
    n = w * h
    frames = [raw[i:i + n] for i in range(0, len(raw) - n + 1, n)]
    diffs = [sum(map(abs, map(operator.sub, a, b))) / n for a, b in zip(frames, frames[1:])]
    log = run_media_command(['ffmpeg', '-hide_banner', '-nostdin', '-i', str(source), '-map', f'0:{stream}', '-an',
                             '-vf', f"scale=320:-2,select='gt(scene,{_PACE['cut_score']})',showinfo", '-f', 'null', '-'],
                            timeout=900).stderr
    cuts = []
    for t in sorted(float(v) for v in re.findall(r'pts_time:' + _NUMBER, log)):
        if 0 < t < duration and (not cuts or t - cuts[-1] > _PACE['cut_merge']):
            cuts.append(round(t, 3))
    # 运动要持续：取 0.5 秒滑动中位数，字幕出现、标签切换这类单帧跳变不算；静止区间在剪点处断开。
    half = fps // 4
    smooth = [statistics.median(diffs[max(0, i - half):i + half + 1]) for i in range(len(diffs))]
    cut_frames = {round(c * fps) - 1 for c in cuts} | {round(c * fps) for c in cuts}
    low = [d < level and i not in cut_frames for i, d in enumerate(smooth)]
    runs, start = [], None
    for i, flag in enumerate(low + [False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if (i - start) / fps >= seconds:
                runs.append({'start_seconds': round(start / fps, 3), 'end_seconds': round(min(duration, i / fps), 3)})
            start = None
    edges = [0.0] + cuts + [duration]
    shots = [b - a for a, b in zip(edges, edges[1:])]
    pace = {'cuts': cuts, 'shot_count': len(shots), 'cuts_per_minute': round(len(cuts) / duration * 60, 1),
            'median_shot_seconds': round(statistics.median(shots), 2), 'longest_shot_seconds': round(max(shots), 2),
            'low_motion_share': round(sum(low) / len(low), 3) if low else None}
    return runs, pace


def scan_media(source, info, *, freeze_seconds=1.0, silence_seconds=.5, timeline=None, holds=None,
               low_motion_seconds=1.5, low_motion_level=1.2):
    """Report frozen, black and silent intervals as places worth looking at; never a pass/fail verdict."""
    holds = _parse_holds(holds)
    if info['kind'] != 'video' or not info.get('duration_seconds'):
        raise NTFError('inspect_parameters', '--scan 只处理可测得时长的视频。')
    if any(not math.isfinite(v) or v <= 0 for v in (freeze_seconds, silence_seconds, low_motion_seconds, low_motion_level)):
        raise NTFError('inspect_parameters', '冻结、静音、低运动的最短时长和低运动阈值须为正数。')
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
    found['low_motion'], pace = _motion_pace(source, info.get('video_stream_index', 'V:0'), duration,
                                             low_motion_level, low_motion_seconds)
    for item in found['black']:
        share = _bright_share(source, (item['start_seconds'] + item['end_seconds']) / 2, info.get('video_stream_index', 'V:0'))
        item['bright_pixel_share'] = share
        item['has_content'] = bool(share and share >= .002)
    if holds:
        for item in found['freeze'] + found['low_motion']:   # freezedetect needs a few frames to notice a freeze: allow 0.35 s either side
            item['intended'] = any(item['start_seconds'] >= a - .35 and item['end_seconds'] <= b + .35 for a, b in holds)
        found['holds'] = [{'start_seconds': a, 'end_seconds': b} for a, b in holds]
    if timeline:
        from .io import read_json
        from .preview import _timeline
        windows = _timeline(read_json(timeline), duration, info.get('fps') or 30)
        for items in found.values():
            for item in items or []:
                item['scene_ids'] = [sid for sid, (a, b) in windows.items()
                                     if a < item['end_seconds'] and b > item['start_seconds']]
    found['pace'] = pace
    found['thresholds'] = {'freeze_seconds': freeze_seconds, 'black_seconds': .2,
                           'low_motion_level': low_motion_level, 'low_motion_seconds': low_motion_seconds,
                           'low_motion_frame': f"{_PACE['width']}x{_PACE['height']}@{_PACE['fps']}fps",
                           'cut_scene_score': _PACE['cut_score'],
                           'silence_seconds': silence_seconds if info.get('has_audio') else None,
                           'silence_db': -35 if info.get('has_audio') else None,
                           'near_silence_db': -70 if info.get('has_audio') else None,
                           'near_silence_min_seconds': .2 if info.get('has_audio') else None,
                           'digital_silence_min_seconds': .001 if info.get('has_audio') else None}
    return found


_OCTAVES = (31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)


def _audio_balance(source, info):
    """Power per octave band in dB relative to the 1 kHz octave (pink noise ≈ all 0), with hints."""
    rate = info.get('sample_rate') or 48000
    levels = {}
    for centre in _OCTAVES:
        if centre * 1.41 >= rate / 2:
            continue
        done = run_media_command(['ffmpeg', '-hide_banner', '-nostdin', '-i', str(source), '-vn', '-af',
                                  f'aformat=channel_layouts=mono,bandpass=f={centre:g}:width_type=o:width=1,volumedetect',
                                  '-f', 'null', '-'], timeout=600)
        found = re.search(r'mean_volume:\s*(-?(?:[0-9.]+|inf)) dB', done.stderr)
        value = float(found.group(1)) if found else None
        levels[centre] = value if value is not None and math.isfinite(value) else None
    ref = levels.get(1000)
    if ref is None:
        return {'octave_db_re_1k': None, 'notes': ['1 kHz 附近几乎没有能量，频段平衡无从比较。']}
    power = lambda c: 10 ** ((levels[c] - ref) / 10) if levels.get(c) is not None else 0.0
    rel = {f'{c:g}': (round(levels[c] - ref, 1) if levels.get(c) is not None else None) for c in levels}
    low = 10 * math.log10(max(1e-12, (power(31.5) + power(63) + power(125)) / 3))
    high = 10 * math.log10(max(1e-12, (power(4000) + power(8000)) / 2))
    notes = []
    if low > 14:
        notes.append(f'低频偏重：31–125 Hz 比 1 kHz 高 {low:.1f} dB（常见混音 +4…+12）。降低贝斯或低音铺底，缩短底鼓衰减，给铺底加高通。')
    elif low < 0:
        notes.append(f'几乎没有低频（比 1 kHz 低 {-low:.1f} dB）。刻意轻盈的片子可以这样；否则加底鼓、贝斯或低音。')
    if high < -24:
        notes.append(f'发闷：4–8 kHz 比 1 kHz 低 {-high:.1f} dB（常见 −6…−18）。加踩镲、沙锤或更亮的音色。')
    elif high > -2:
        notes.append(f'偏刺：4–8 kHz 只比 1 kHz 低 {-high:.1f} dB。压低噪声层、踩镲和上升音效。')
    return {'octave_db_re_1k': rel, 'low_db_re_1k': round(low, 1), 'high_db_re_1k': round(high, 1), 'notes': notes}


def _audio_drops(source, duration, drops, beat):
    """Breath before each hit: the last half-beat against the bar before it, and the hit against that bar."""
    from array import array
    rate = 8000
    done = run_media_command(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-i', str(source), '-vn',
                              '-ac', '1', '-ar', str(rate), '-f', 's16le', '-'], timeout=600, text=False)
    samples = array('h')
    samples.frombytes((done.stdout or b'')[:len(done.stdout or b'') // 2 * 2])

    def rms_db(a, b):
        i, j = max(0, int(a * rate)), min(len(samples), int(b * rate))
        if j - i < rate * .02:
            return None
        power = sum(v * v for v in samples[i:j]) / (j - i)
        return 10 * math.log10(power / 32768 ** 2) if power > 0 else -120.0
    report = []
    for d in drops:
        breath, bar, hit = rms_db(d - beat / 2, d - .01), rms_db(d - beat / 2 - 4 * beat, d - beat / 2), rms_db(d, d + 2 * beat)
        if None in (breath, bar, hit):
            report.append({'time_seconds': d, 'notes': ['重拍前后不足一小节，无法比较。']})
            continue
        dip, lift = bar - breath, hit - bar
        notes = []
        if dip < 4:
            notes.append(f'重拍前没有明显的呼吸：最后半拍只比前一小节低 {dip:.1f} dB。在这半拍停掉鼓和铺底，最多留上升音效的尾巴。')
        if lift < 1:
            notes.append(f'重拍没有比前一小节更响（{lift:+.1f} dB）：减薄铺垫，或给重拍加分量。')
        report.append({'time_seconds': d, 'breath_db_vs_bar': round(-dip, 1), 'hit_db_vs_bar': round(lift, 1), 'notes': notes})
    return report


def inspect_media(source, *, decode=False, output=None, frames=3, max_width=960, jpeg_quality=80,
                  at_seconds=None, write_report=True, expected_width=None, expected_height=None,
                  expected_fps=None, expected_duration=None, duration_tolerance=.1,
                  expect_audio=None, audio_check=False, min_mean_dbfs=-60, max_peak_dbfs=-.1,
                  expected_loudness_lufs=None, loudness_tolerance=1,
                  scan=False, freeze_seconds=1.0, silence_seconds=.5, timeline=None, holds=None,
                  low_motion_seconds=1.5, low_motion_level=1.2,
                  drops=None, beat_seconds=.5):
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
    drops = list(drops or [])
    if drops and not audio_check:
        raise NTFError('inspect_parameters', '--drop 与 --audio-check 一起使用。')
    if not math.isfinite(beat_seconds) or beat_seconds <= 0 or any(not math.isfinite(d) or d <= 0 for d in drops):
        raise NTFError('inspect_parameters', '--drop 与 --beat-seconds 须为正的秒数。')
    if holds and not scan:
        raise NTFError('inspect_parameters', '--hold 与 --scan 一起使用。')
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
            if audio_check:
                result['audio_balance'] = _audio_balance(source, info)
                if drops:
                    result['audio_drops'] = _audio_drops(source, info.get('duration_seconds'), drops, beat_seconds)
    if scan:
        result['scan'] = scan_media(source, info, freeze_seconds=freeze_seconds,
                                    silence_seconds=silence_seconds, timeline=timeline, holds=holds,
                                    low_motion_seconds=low_motion_seconds, low_motion_level=low_motion_level)
    result['verification'] = {'passed':all(c['passed'] for c in checks) if checks else None,'checks':checks}
    if output is None:
        return result
    output = Path(output).expanduser().resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise NTFError('output_exists', 'Choose an empty inspection output directory to preserve earlier previews.')
    if source.is_relative_to(output):
        raise NTFError('output_input_collision', 'Inspection output must not contain its source file.')
    output.mkdir(parents=True,exist_ok=True)
    if audio_check and info.get('has_audio'):   # Agents cannot listen: the waveform and spectrum are the closest look
        for name, graph in (('audio_wave.png', 'showwavespic=s=1600x320:split_channels=1'),
                            ('audio_spectrum.png', 'showspectrumpic=s=1600x520:legend=1:scale=log')):
            run_media_command(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-i', str(source), '-vn',
                               '-lavfi', graph, '-frames:v', '1', str(output / name)], timeout=600)
            result.setdefault('audio_images', []).append(str(output / name))
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
