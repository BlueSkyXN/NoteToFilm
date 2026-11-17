"""Actual media inspection and compressed JPEG review frames."""
from __future__ import annotations
import math
import re
import json
from pathlib import Path

from .errors import NTFError
from .io import atomic_json
from .media import probe, run_media_command


def inspect_media(source, *, decode=False, output=None, frames=3, max_width=960, jpeg_quality=80,
                  at_seconds=None, write_report=True, expected_width=None, expected_height=None,
                  expected_fps=None, expected_duration=None, duration_tolerance=.1,
                  expect_audio=None, audio_check=False, min_mean_dbfs=-60, max_peak_dbfs=-.1,
                  expected_loudness_lufs=None, loudness_tolerance=1):
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
