"""Explicit background sound and final audio processing for the local composer."""
from __future__ import annotations
import math
from .errors import NTFError
from .media import probe, project_path


def _number(raw, name, default=0):
    value = raw.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise NTFError('background_audio_invalid', f'{name} must be a finite nonnegative number.')
    return float(value)


def plan_background(root, raw, total, cache):
    if raw is None:
        return None
    if not isinstance(raw, dict) or not raw.get('path'):
        raise NTFError('background_audio_invalid', 'background_audio requires a resolved project-local audio path.')
    path = project_path(root, raw['path'])
    info = probe(path)
    available = info.get('audio_duration_seconds', info.get('duration_seconds', 0))
    if not info.get('has_audio') or not available:
        raise NTFError('background_audio_invalid', 'Selected background media has no measurable audio.')
    start = _number(raw, 'start_seconds')
    trim = _number(raw, 'trim_start')
    if start >= total or trim >= available:
        raise NTFError('background_audio_invalid', 'Background start or trim is beyond the available timeline.')
    loop = raw.get('loop', False)
    if not isinstance(loop, bool):
        raise NTFError('background_audio_invalid', 'Background loop must be true or false.')
    duration = _number(raw, 'duration_seconds', total-start if loop else min(available-trim, total-start))
    if duration <= 0 or duration > total-start+1e-6:
        raise NTFError('background_audio_invalid', 'Background duration must fit inside the film window.')
    if not loop and duration > available-trim+1e-6:
        raise NTFError('background_audio_short', 'Background media is too short; shorten its duration or explicitly enable loop.')
    fade_in = _number(raw, 'fade_in_seconds')
    fade_out = _number(raw, 'fade_out_seconds')
    if fade_in+fade_out > duration+1e-6:
        raise NTFError('background_audio_invalid', 'Background fades must fit inside its duration.')
    cache[str(path)] = info
    return {'path': str(path), 'start_seconds': start, 'trim_start': trim,
            'duration_seconds': duration, 'loop': loop, 'volume': _number(raw, 'volume', .15),
            'fade_in_seconds': fade_in, 'fade_out_seconds': fade_out, 'metadata': info}


def final_audio_arguments(settings, background, total):
    inputs, filters = [], []
    stream = '[0:a:0]'
    if background:
        if background['loop']:
            inputs += ['-stream_loop', '-1']
        inputs += ['-i', background['path']]
        duration = background['duration_seconds']
        chain = (f"[1:a:0]atrim=start={background['trim_start']}:duration={duration},asetpts=PTS-STARTPTS,"
                 'aresample=48000,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,'
                 f"volume={background['volume']}")
        if background['fade_in_seconds']:
            chain += f",afade=t=in:st=0:d={background['fade_in_seconds']}"
        if background['fade_out_seconds']:
            chain += f",afade=t=out:st={duration-background['fade_out_seconds']}:d={background['fade_out_seconds']}"
        delay = round(background['start_seconds']*48000)
        chain += f',adelay=delays={delay}S:all=1,apad,atrim=duration={total}[bed]'
        filters.append(chain)
        filters.append('[0:a:0][bed]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mixed]')
        stream = '[mixed]'
    loudness = settings.get('audio_loudness_lufs')
    if loudness is not None:
        filters.append(f"{stream}loudnorm=I={loudness}:TP={settings['audio_true_peak_db']}:LRA=9[master]")
    elif background:
        filters.append(f'{stream}alimiter=limit=0.95:level=0:latency=1[master]')
    return inputs, ';'.join(filters) if filters else None
