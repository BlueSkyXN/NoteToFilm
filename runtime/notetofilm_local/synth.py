"""Deterministic music and sound-effect synthesis for `ntf score`, standard library only.

Adapted from garden-skills motion-showreel scripts/lib/synth.mjs (MIT License, see THIRD_PARTY_NOTICES.md):
instrument recipes, chord and scale tables and the session API (tempo, buses, ducking, shared space).
Rewritten for CPython: wavetable oscillators for steady tones, block-wise comb and all-pass reverb so the
inner loops run in C, and bus filters, the final mix and the peak limiter run in FFmpeg.
"""
from __future__ import annotations

import hashlib
import math
import os
import random
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import uuid
from array import array
from itertools import accumulate, repeat
from operator import add, mod as _mod, mul as _mul
from pathlib import Path

from .errors import NTFError

SR = 48000
TAU = 2 * math.pi


def N(sec):
    return max(0, int(round(sec * SR)))


def buf(n):
    return array('f', bytes(4 * n))


# ─────────────────────────── notes & harmony ───────────────────────────
_NOTE = {'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11}


def midi(n):
    if isinstance(n, (int, float)) and not isinstance(n, bool):
        return n
    s = str(n).strip()
    if len(s) >= 2 and s[0].lower() in _NOTE:
        i, v = 1, _NOTE[s[0].lower()]
        while i < len(s) and s[i] in '#b':
            v += 1 if s[i] == '#' else -1
            i += 1
        try:
            return v + (int(s[i:]) + 1) * 12
        except ValueError:
            pass
    raise NTFError('score_parameters', f'音名写法不对：{n}（例如 A3、C#4、Eb2 或 MIDI 数字）')


def hz(n):
    return 440 * 2 ** ((midi(n) - 69) / 12)


CHORDS = {
    'maj': [0, 4, 7], 'min': [0, 3, 7], 'sus2': [0, 2, 7], 'sus4': [0, 5, 7], 'dim': [0, 3, 6], 'aug': [0, 4, 8], '5': [0, 7, 12],
    'maj7': [0, 4, 7, 11], 'min7': [0, 3, 7, 10], '7': [0, 4, 7, 10], 'm9': [0, 3, 7, 10, 14], 'maj9': [0, 4, 7, 11, 14],
    'add9': [0, 4, 7, 14], 'madd9': [0, 3, 7, 14], 'min11': [0, 3, 7, 10, 14, 17], '6': [0, 4, 7, 9], 'm6': [0, 3, 7, 9],
    '9': [0, 4, 7, 10, 14], '7b9': [0, 4, 7, 10, 13], '7sus4': [0, 5, 7, 10], 'm7b5': [0, 3, 6, 10], 'dim7': [0, 3, 6, 9],
    'maj7#11': [0, 4, 7, 11, 18], 'quartal': [0, 5, 10], 'quartal4': [0, 5, 10, 15], 'cluster': [0, 1, 2],
}
SCALES = {
    'major': [0, 2, 4, 5, 7, 9, 11], 'minor': [0, 2, 3, 5, 7, 8, 10], 'dorian': [0, 2, 3, 5, 7, 9, 10],
    'phrygian': [0, 1, 3, 5, 7, 8, 10], 'lydian': [0, 2, 4, 6, 7, 9, 11], 'mixolydian': [0, 2, 4, 5, 7, 9, 10],
    'locrian': [0, 1, 3, 5, 6, 8, 10], 'harmonic': [0, 2, 3, 5, 7, 8, 11], 'melodic': [0, 2, 3, 5, 7, 9, 11],
    'hijaz': [0, 1, 4, 5, 7, 8, 10], 'wholetone': [0, 2, 4, 6, 8, 10], 'blues': [0, 3, 5, 6, 7, 10],
    'penta': [0, 2, 4, 7, 9], 'minpenta': [0, 3, 5, 7, 10], 'hirajoshi': [0, 2, 3, 7, 8], 'insen': [0, 1, 5, 7, 10],
    # 宫 商 角 徵 羽
    'gong': [0, 2, 4, 7, 9], 'shang': [0, 2, 5, 7, 10], 'jue': [0, 3, 5, 8, 10], 'zhi': [0, 2, 5, 7, 9], 'yu': [0, 3, 5, 7, 10],
}


def chord(root, quality='maj', inversion=0):
    if quality not in CHORDS:
        raise NTFError('score_parameters', f'未知和弦 {quality}；可用：{", ".join(CHORDS)}')
    notes = [midi(root) + i for i in CHORDS[quality]]
    for _ in range(inversion):
        notes.append(notes.pop(0) + 12)
    return notes


def scale(root, name='minor'):
    if name not in SCALES:
        raise NTFError('score_parameters', f'未知音阶 {name}；可用：{", ".join(SCALES)}')
    s, r = SCALES[name], midi(root)
    return lambda degree: r + 12 * (degree // len(s)) + s[degree % len(s)]


def steps(pattern, step=0.25, start=0):
    """'x..x..x.' → beat positions of the hits; spaces and | are ignored."""
    hits, i = [], 0
    for c in pattern:
        if c in ' |':
            continue
        if c == 'x':
            hits.append(start + i * step)
        i += 1
    return hits


# ─────────────────────────────── basics ───────────────────────────────
def rng(seed=1):
    state = [seed & 0xFFFFFFFF]

    def nxt():  # mulberry32, the same generator as the JavaScript side
        state[0] = (state[0] + 0x6D2B79F5) & 0xFFFFFFFF
        t = state[0]
        t = ((t ^ (t >> 15)) * (1 | t)) & 0xFFFFFFFF
        t = (t + (((t ^ (t >> 7)) * (61 | t)) & 0xFFFFFFFF) ^ t) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return nxt


def noise(sec, seed=7):
    # random.Random(seed).random() is reproducible across Python versions and runs in C
    r = random.Random(seed).random
    return array('f', map(_sub1, map(_mul, (r() for _ in range(N(sec))), repeat(2.0))))


def _sub1(v):
    return v - 1.0


_TABLE = 4096
_tables = {}


def _wavetable(wave, freq):
    """Band-limited single cycle: harmonics below Nyquist only (cached per wave and harmonic count)."""
    top = max(1, int(SR * 0.45 / max(freq, 1)))
    if wave == 'sine':
        top = 1
    top = min(top, 64)
    key = (wave, top)
    if key not in _tables:
        terms = []
        for k in range(1, top + 1):
            if wave == 'saw':
                terms.append((k, -2 / (math.pi * k) * (-1) ** k))
            elif wave == 'square' and k % 2:
                terms.append((k, 4 / (math.pi * k)))
            elif wave == 'tri' and k % 2:
                terms.append((k, 8 / (math.pi * k) ** 2 * (-1) ** ((k - 1) // 2)))
            elif wave == 'sine' and k == 1:
                terms.append((1, 1.0))
        _tables[key] = array('f', [sum(a * math.sin(TAU * k * i / _TABLE) for k, a in terms) for i in range(_TABLE)])
    return _tables[key]


def osc(n, freq, wave='sine', phase=0.0):
    """Oscillator. freq is Hz or a function of the sample index; wave is sine, saw, square or tri."""
    if wave not in ('sine', 'saw', 'square', 'tri'):
        raise NTFError('score_parameters', f'未知波形 {wave}；可用 sine、saw、square、tri')
    if not callable(freq):
        if n <= 0:
            return buf(0)
        table, inc, p0 = _wavetable(wave, freq), freq * _TABLE / SR, (phase % 1) * _TABLE
        # phase accumulation, truncation, wrap and lookup all run as C iterators
        index = map(_mod, map(int, accumulate(repeat(inc, n - 1), initial=p0)), repeat(_TABLE))
        return array('f', map(table.__getitem__, index))
    table = _wavetable(wave, freq(0))
    out, p, scale_ = buf(n), (phase % 1) * _TABLE, _TABLE / SR
    for i in range(n):
        out[i] = table[int(p) % _TABLE]
        p += freq(i) * scale_
    return out


def exp_env(n, decay, attack=0.002):
    a, k = max(1, N(attack)), -1 / (SR * max(decay, 1e-6))
    exp = math.exp
    return array('f', [min(1.0, i / a) * exp(i * k) for i in range(n)])


def adsr(n, a=0.005, d=0.1, s=0.7, r=0.1, gate=None):
    A, D, R = max(1, N(a)), max(1, N(d)), max(1, N(r))
    G = n if gate is None else N(gate)
    out, rel = buf(n), s
    for i in range(n):
        if i < G:
            v = i / A if i < A else 1 - (1 - s) * (i - A) / D if i < A + D else s
            rel = v
        else:
            v = rel * max(0.0, 1 - (i - G) / R)
        out[i] = v
    return out


def mul(a, b):
    """Elementwise product; b is a number or a sequence (shorter sequences count as zero beyond their end)."""
    if isinstance(b, (int, float)):
        return array('f', map(_mul, a, repeat(float(b), len(a))))
    out = array('f', map(_mul, a, b))
    if len(out) < len(a):
        out.extend(buf(len(a) - len(out)))
    return out


def add_into(dst, src, at=0, g=1.0):
    """Add src (times g) into dst starting at sample at; parts outside dst are dropped."""
    o = int(round(at))
    s0, s1 = max(0, -o), min(len(src), len(dst) - o)
    if s1 <= s0:
        return dst
    part = src[s0:s1] if g == 1 else array('f', map(_mul, src[s0:s1], repeat(float(g), s1 - s0)))
    dst[o + s0:o + s1] = array('f', map(add, dst[o + s0:o + s1], part))
    return dst


def drive(b, amt=0.5):
    k = 1 + amt * 6
    n, tanh = math.tanh(k), math.tanh
    return array('f', [tanh(v * k) / n for v in b])


def fade(b, in_s=0.005, out_s=0.01):
    b = array('f', b)
    I, O, n = N(in_s), N(out_s), len(b)
    for i in range(min(I, n)):
        b[i] *= i / I
    for i in range(min(O, n)):
        b[n - 1 - i] *= i / O
    return b


def reverse(b):
    out = array('f', b)
    out.reverse()
    return out


def peak_norm(b, peak=1.0):
    m = max((abs(v) for v in b), default=0)
    return mul(b, peak / m) if m else b


def biquad(b, kind='lowpass', cutoff=1000.0, q=0.707):
    """RBJ biquad. cutoff may be a function of the sample index (re-evaluated every 32 samples)."""
    out = buf(len(b))
    cf = cutoff if callable(cutoff) else (lambda i: cutoff)
    x1 = x2 = y1 = y2 = 0.0
    b0 = b1 = b2 = a1 = a2 = 0.0
    cos, sin = math.cos, math.sin
    for i, x in enumerate(b):
        if i % 32 == 0:
            f = min(max(cf(i), 10.0), SR * 0.45)
            w = TAU * f / SR
            cw, al = cos(w), sin(w) / (2 * q)
            if kind == 'highpass':
                n0, n1, n2 = (1 + cw) / 2, -(1 + cw), (1 + cw) / 2
            elif kind == 'bandpass':
                n0, n1, n2 = al, 0.0, -al
            else:
                n0, n1, n2 = (1 - cw) / 2, 1 - cw, (1 - cw) / 2
            d0 = 1 + al
            b0, b1, b2, a1, a2 = n0 / d0, n1 / d0, n2 / d0, -2 * cw / d0, (1 - al) / d0
        y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, x, y1, y
        out[i] = y
    return out


def lowpass(b, f, q=0.707):
    return biquad(b, 'lowpass', f, q)


def highpass(b, f, q=0.707):
    return biquad(b, 'highpass', f, q)


def bandpass(b, f, q=1.0):
    return biquad(b, 'bandpass', f, q)


def stereo(L, R):
    return {'L': L, 'R': R}


# ─────────────────────────────── drums ───────────────────────────────
def kick(tone=48, start=165, pitch_decay=0.045, decay=0.42, click=0.5, drive_amt=0.35):
    n = N(decay * 3)
    b = mul(osc(n, lambda i: tone + (start - tone) * math.exp(-i / SR / pitch_decay)), exp_env(n, decay, 0.001))
    if click > 0:
        add_into(b, mul(highpass(noise(0.012, 3), 2500), exp_env(N(0.012), 0.003, 0.0005)), 0, click * 0.6)
    return fade(drive(b, drive_amt), 0.0005, 0.02)


def snare(tone=185, decay=0.18, snappy=0.75, seed=11):
    n = N(decay * 3)
    body = osc(n, lambda i: tone * (1 + 0.5 * math.exp(-i / SR / 0.01)))
    add_into(body, osc(n, tone * 1.6), 0, 0.5)
    body = mul(body, exp_env(n, 0.07))
    add_into(body, mul(bandpass(highpass(noise(n / SR, seed), 1200), 5200, 0.6), exp_env(n, decay)), 0, snappy * 2.2)
    return fade(drive(body, 0.2), 0.0005, 0.02)


def clap(decay=0.22, seed=5):
    n = N(decay * 3 + 0.03)
    nz, env = bandpass(noise(n / SR, seed), 1300, 0.9), buf(n)
    for o in (0, 0.011, 0.022):
        s = N(o)
        for i in range(s, n):
            env[i] = max(env[i], math.exp(-(i - s) / SR / 0.007))
    s = N(0.03)
    for i in range(s, n):
        env[i] = max(env[i], 0.6 * math.exp(-(i - s) / SR / decay))
    return fade(mul(mul(nz, env), 3), 0.0005, 0.02)


def hat(open=False, decay=None, tone=1.0, seed=9):
    decay = decay if decay is not None else (0.32 if open else 0.045)
    n = N(decay * 3 + 0.01)
    metal = buf(n)
    for r in (2, 3, 4.16, 5.43, 6.79, 8.21):
        add_into(metal, osc(n, min(40 * tone * r * 10.3, SR * 0.45), 'square'), 0, 1 / 6)
    add_into(metal, noise(n / SR, seed), 0, 0.6)
    return fade(mul(mul(highpass(bandpass(metal, 10000, 0.8), 7000), exp_env(n, decay, 0.0005)), 2.2), 0.0003, 0.01)


def crash(dur=2.4, seed=13):
    n = N(dur)
    b = highpass(noise(dur, seed), 3500)
    for r in (3.1, 4.7, 6.3, 8.9):
        add_into(b, osc(n, 420 * r, 'square'), 0, 0.08)
    return fade(mul(lowpass(b, 12000), exp_env(n, dur / 3.5, 0.001)), 0.0005, 0.1)


def tom(note='A2', decay=0.35):
    f, n = hz(note), N(decay * 3)
    return fade(mul(osc(n, lambda i: f * (1 + 0.6 * math.exp(-i / SR / 0.03))), exp_env(n, decay)), 0.0005, 0.02)


def shaker(decay=0.06, attack=0.008, tone=1.0, seed=15):
    n = N(attack + decay * 3)
    return fade(mul(bandpass(highpass(noise(n / SR, seed), 4000 * tone), 7500 * tone, 0.7), exp_env(n, decay, attack)), 0.0005, 0.01)


def rim(tone=1.0, decay=0.018, seed=17):
    n = N(decay * 4 + 0.005)
    b = mul(osc(n, 1750 * tone, 'tri'), exp_env(n, decay, 0.0002))
    add_into(b, mul(bandpass(noise(n / SR, seed), 3200 * tone, 1.4), exp_env(n, decay * 0.5, 0.0002)), 0, 1.2)
    return fade(b, 0.0002, 0.005)


# ───────────────────────────── tonal voices ─────────────────────────────
def bass(note, dur, wave='saw', cutoff=600, q=1.2, env_amt=3, env_decay=0.16, drive_amt=0.45, sub=0.6, release=0.04):
    f, n = hz(note), N(dur + release)
    b = osc(n, f, wave)
    if sub:
        add_into(b, osc(n, f / 2), 0, sub)
    out = biquad(b, 'lowpass', lambda i: cutoff * (1 + env_amt * math.exp(-i / SR / env_decay)), q)
    return drive(mul(out, adsr(n, 0.003, 0.1, 0.85, release, dur)), drive_amt)


def sub(note, dur, release=0.08, harm=0.15):
    f, n = hz(note), N(dur + release)
    b = osc(n, f)
    if harm:  # 2nd and 3rd harmonics so phone speakers still carry the line
        add_into(b, osc(n, f * 2), 0, harm)
        add_into(b, osc(n, f * 3), 0, harm / 2)
    return mul(b, adsr(n, 0.01, 0.05, 0.95, release, dur))


def pad(notes, dur, voices=3, cents=14, cutoff=1800, q=0.6, attack=0.5, release=1.2, wave='saw', seed=21, wobble=0.15):
    """Detuned stereo pad; returns {'L', 'R'}."""
    notes = [midi(x) for x in (notes if isinstance(notes, (list, tuple)) else [notes])]
    n, r = N(dur + release), rng(seed)
    L, R = buf(n), buf(n)
    for note in notes:
        for v in range(voices):
            det = (v / (voices - 1) - 0.5) * 2 * cents if voices > 1 else 0
            o, p = osc(n, hz(note) * 2 ** (det / 1200), wave, r()), (v / (voices - 1) if voices > 1 else 0.5)
            add_into(L, o, 0, math.cos(p * math.pi / 2))
            add_into(R, o, 0, math.sin(p * math.pi / 2))
    g = 0.9 / math.sqrt(len(notes) * voices)
    env = mul(adsr(n, attack, 0.3, 0.9, release, dur), g)
    cf = (lambda i: cutoff * (1 + wobble * math.sin(TAU * 0.13 * i / SR))) if wobble else cutoff
    return stereo(mul(biquad(L, 'lowpass', cf, q), env), mul(biquad(R, 'lowpass', cf, q), env))


def pluck(note, dur, bright=0.55, damp=0.996, seed=3):
    """Karplus-Strong string: low bright with high damp approaches nylon or guqin."""
    f, n = hz(note), N(dur)
    D = SR / f
    m = max(2, int(D))
    frac = D - m
    line = lowpass(noise(m / SR + 0.001, seed), 800 + bright * 9000)[:m]
    out, ring, idx, prev = buf(n), array('f', line), 0, 0.0
    for i in range(n):
        a = ring[idx]
        s = a + (ring[(idx + 1) % m] - a) * frac
        out[i] = s
        ring[idx] = damp * 0.5 * (s + prev)
        prev = s
        idx = (idx + 1) % m
    return fade(peak_norm(out, 0.8), 0.001, min(0.1, dur / 4))


def keys(notes, dur, decay=1.4, index=2.5, release=0.25):
    """FM electric piano."""
    notes = [midi(x) for x in (notes if isinstance(notes, (list, tuple)) else [notes])]
    n = N(dur + release)
    out, sin, exp = buf(n), math.sin, math.exp
    for note in notes:
        f = hz(note)
        b = array('f', [sin(TAU * f * t + (index * exp(-t / 0.4) + 0.3) * sin(TAU * f * t)) + 0.15 * sin(TAU * f * 14 * t) * exp(-t / 0.02)
                        for t in (i / SR for i in range(n))])
        add_into(out, mul(b, exp_env(n, decay, 0.002)), 0, 1 / len(notes))
    return mul(out, adsr(n, 0.001, 0.01, 1, release, dur))


def bell(note, dur=2.0, ratio=3.5, index=4, decay=1.2):
    f, n, sin, exp = hz(note), N(dur), math.sin, math.exp
    b = array('f', [sin(TAU * f * t + index * exp(-t / (decay * 0.4)) * sin(TAU * f * ratio * t)) for t in (i / SR for i in range(n))])
    return fade(mul(b, exp_env(n, decay, 0.001)), 0.0005, 0.05)


def lead(note, dur, wave='saw', cutoff=3200, q=0.9, vibrato=0.12, rate=5.5, detune=7, release=0.12):
    f, n = hz(note), N(dur + release)

    def fr(c):
        return lambda i: f * 2 ** ((vibrato * min(1, max(0, (i / SR - 0.2) / 0.3)) * math.sin(TAU * rate * i / SR) + c / 100) / 12)
    b = osc(n, fr(detune / 2), wave)
    add_into(b, osc(n, fr(-detune / 2), wave, 0.37), 0, 1)
    return mul(biquad(mul(b, 0.5), 'lowpass', cutoff, q), adsr(n, 0.01, 0.15, 0.8, release, dur))


MALLETS = {
    'marimba': {'decay': 0.5, 'strike': 0.25, 'partials': [(1, 1, 1), (3.99, 0.35, 0.25), (10.65, 0.12, 0.08)]},
    'xylo': {'decay': 0.28, 'strike': 0.4, 'partials': [(1, 1, 1), (3, 0.5, 0.45), (6, 0.2, 0.2)]},
    'vibes': {'decay': 1.6, 'strike': 0.15, 'trem': 5.5, 'partials': [(1, 1, 1), (4, 0.3, 0.35), (10.2, 0.08, 0.12)]},
    'glock': {'decay': 1.3, 'strike': 0.2, 'partials': [(1, 1, 1), (2.76, 0.45, 0.5), (5.4, 0.25, 0.3), (8.93, 0.12, 0.18)]},
    'kalimba': {'decay': 0.9, 'strike': 0.3, 'partials': [(1, 1, 1), (6.27, 0.22, 0.12), (17.55, 0.06, 0.04)]},
    'steel': {'decay': 0.9, 'strike': 0.2, 'partials': [(1, 1, 1), (2, 0.55, 0.7), (3, 0.3, 0.5), (4.02, 0.16, 0.35)]},
    'wood': {'decay': 0.06, 'strike': 0.6, 'partials': [(1, 1, 1), (2.63, 0.45, 0.6), (4.4, 0.2, 0.4)]},
}


def mallet(note, dur=1.2, material='marimba', decay=None, bright=0.5, seed=101):
    """Struck bars and tines by modal synthesis."""
    if material not in MALLETS:
        raise NTFError('score_parameters', f'未知材质 {material}；可用：{", ".join(MALLETS)}')
    m, f, n, r = MALLETS[material], hz(note), N(dur), rng(seed)
    d = decay if decay is not None else m['decay']
    out = buf(n)
    for ratio, level, ds in m['partials']:
        if f * ratio > SR * 0.45:
            continue
        add_into(out, mul(osc(n, f * ratio, 'sine', r()), exp_env(n, d * ds, 0.0008)), 0, level if ratio == 1 else level * (0.4 + 1.2 * bright))
    if m.get('strike'):
        s = N(0.02)
        add_into(out, mul(bandpass(noise(0.02, seed), min(f * 4, 9000), 1.5), exp_env(s, 0.004, 0.0003)), 0, m['strike'] * bright * 2)
    if m.get('trem'):
        out = array('f', [v * (1 - 0.35 * (0.5 + 0.5 * math.sin(TAU * m['trem'] * i / SR))) for i, v in enumerate(out)])
    return fade(peak_norm(out, 0.8), 0.0003, min(0.05, dur / 4))


# ───────────────────────────── sound design ─────────────────────────────
def riser(dur=2.0, start=150, end=3200, noise_amt=0.6, seed=31):
    n = N(dur)
    sw = osc(n, lambda i: start * (end / start) ** (i / n), 'saw')
    nz = biquad(noise(dur, seed), 'bandpass', lambda i: 400 * 30 ** (i / n), 1.2)
    b = array('f', [(sw[i] * 0.35 + nz[i] * noise_amt * 2) * (i / n) ** 2 for i in range(n)])
    return fade(highpass(b, 120), 0.01, 0.005)


def downlifter(dur=1.5, start=2500, end=80, seed=33):
    n = N(dur)
    sw = osc(n, lambda i: start * (end / start) ** (i / n))
    nz = biquad(noise(dur, seed), 'lowpass', lambda i: 6000 * 0.02 ** (i / n), 0.8)
    return fade(array('f', [(sw[i] * 0.4 + nz[i] * 0.9) * (1 - i / n) ** 1.6 for i in range(n)]), 0.002, 0.05)


def whoosh(dur=0.6, start=350, end=4500, peak=0.7, pan=0.8, seed=41):
    """Stereo whoosh, loudest at peak × dur: place it at cut − peak × dur."""
    n = N(dur)
    P = max(1, peak * n)
    bp = biquad(noise(dur, seed), 'bandpass', lambda i: start * (end / start) ** (i / P) if i < P else end * (start / end) ** ((i - P) / max(1, n - P)), 1.4)
    L, R = buf(n), buf(n)
    for i in range(n):
        x = i / P if i < P else 1 - (i - P) / max(1, n - P)
        e = math.sin(math.pi / 2 * x) ** 2.2 * 2.5
        p = (i / n - 0.5) * pan
        L[i] = bp[i] * e * math.cos((p + 1) * math.pi / 4)
        R[i] = bp[i] * e * math.sin((p + 1) * math.pi / 4)
    return stereo(L, R)


def impact(size=1.0, seed=51):
    dur = 1.6 * size
    n = N(dur)
    b = mul(osc(n, lambda i: 30 + 40 * math.exp(-i / SR / 0.09)), exp_env(n, 0.55 * size, 0.001))
    add_into(b, mul(osc(n, lambda i: 110 + 80 * math.exp(-i / SR / 0.02)), exp_env(n, 0.09, 0.0005)), 0, 0.5)
    add_into(b, mul(lowpass(noise(dur, seed), 3500), exp_env(n, 0.18 * size, 0.0005)), 0, 0.7)
    return fade(drive(b, 0.5), 0.0005, 0.1)


def boom(size=1.0, seed=51):
    return lowpass(impact(size, seed), 180)


def click(tone=1.0, seed=61):
    n = N(0.03)
    b = mul(highpass(noise(0.03, seed), 2000), exp_env(n, 0.0018, 0.0002))
    add_into(b, mul(osc(n, 2600 * tone), exp_env(n, 0.004, 0.0002)), 0, 0.7)
    return fade(b, 0.0001, 0.005)


def tick(tone=1.0):
    n = N(0.03)
    return fade(mul(osc(n, 4400 * tone), exp_env(n, 0.006, 0.0002)), 0.0001, 0.005)


def pop(note='C6', decay=0.07):
    f, n = hz(note), N(decay * 4)
    return fade(mul(osc(n, lambda i: f * (1 - 0.4 * math.exp(-i / SR / 0.012))), exp_env(n, decay, 0.001)), 0.0005, 0.01)


def blip(note='E6', dur=0.06):
    n = N(dur + 0.02)
    return fade(mul(lowpass(osc(n, hz(note), 'square'), 5000), adsr(n, 0.001, 0.02, 0.6, 0.02, dur)), 0.0005, 0.005)


def swipe(dur=0.22, up=True, seed=71):
    n = N(dur)
    b = biquad(noise(dur, seed), 'bandpass', lambda i: 1500 * 5 ** (i / n) if up else 7500 * 0.2 ** (i / n), 2)
    return array('f', [v * math.sin(math.pi * i / n) * 2 for i, v in enumerate(b)])


def glitch(dur=0.25, seed=81, bits=4):
    r, n = rng(seed), N(dur)
    b, step, q = buf(n), max(1, N(1 / 64)), 2 ** bits
    for s in range(0, n, step):
        if r() < 0.35:
            continue
        kind, f = r(), 200 + r() * 3000
        for i in range(s, min(n, s + step)):
            v = (1.0 if math.sin(TAU * f * (i - s) / SR) >= 0 else -1.0) if kind < 0.5 else r() * 2 - 1
            b[i] = round(v * q) / q * 0.6
    return fade(b, 0.0005, 0.005)


def shimmer(dur=1.5, root='E6', seed=91, count=9):
    r, n, base = rng(seed), N(dur), midi(root)
    b, ladder = buf(n), [0, 2, 4, 7, 9, 12, 14, 16, 19]
    for _ in range(count):
        st = N(r() * dur * 0.6)
        f = hz(base + ladder[int(r() * len(ladder))])
        add_into(b, mul(osc(n - st, f), exp_env(n - st, 0.25 + r() * 0.4, 0.004)), st, 0.25)
    return b


def ambience(dur, kind='room', amount=1.0, seed=131):
    """A bed for a place or medium: room, tape, vinyl, wind, rain. Returns {'L', 'R'}."""
    n = N(dur)

    def side(s):
        r, nz = rng(s), noise(dur, s)
        if kind == 'room':
            b = lowpass(nz, 350)
            return mul(add_into(b, highpass(noise(dur, s + 3), 6000), 0, 0.03), 1.3)
        if kind == 'tape':
            h = lowpass(highpass(nz, 2500), 12000)
            return array('f', [v * 0.3 * (1 + 0.15 * math.sin(TAU * 0.7 * i / SR)) for i, v in enumerate(h)])
        if kind == 'vinyl':
            b, c = mul(lowpass(highpass(nz, 3000), 9000), 0.06), buf(n)
            for i in range(n):
                if r() < 18 / SR:
                    a = (0.3 + r() * 0.7) * (-1 if r() < 0.5 else 1)
                    for k in range(min(24, n - i)):
                        c[i + k] += a * math.exp(-k / 4)
            add_into(b, highpass(c, 900), 0, 0.9)
            return add_into(b, lowpass(noise(dur, s + 7), 45), 0, 0.5)
        if kind == 'wind':
            p = [r() * TAU for _ in range(3)]
            w = biquad(nz, 'bandpass', lambda i: 500 * 2 ** (0.9 * math.sin(0.13 * TAU * i / SR + p[0]) + 0.5 * math.sin(0.31 * TAU * i / SR + p[1])), 1.1)
            return array('f', [v * 0.85 * (0.6 + 0.4 * math.sin(0.09 * TAU * i / SR + p[2])) for i, v in enumerate(w)])
        if kind == 'rain':
            b, d = mul(lowpass(highpass(nz, 600), 7000), 0.25), buf(n)
            for i in range(n):
                if r() < 400 / SR:
                    a = (0.2 + r() * 0.8) * (-1 if r() < 0.5 else 1)
                    for k in range(min(60, n - i)):
                        d[i + k] += a * math.exp(-k / 9)
            return add_into(b, bandpass(d, 3500, 0.8), 0, 0.8)
        raise NTFError('score_parameters', f'未知环境声 {kind}；可用 room、tape、vinyl、wind、rain')
    return stereo(fade(mul(side(seed), amount), 0.3, 0.3), fade(mul(side(seed + 1000), amount), 0.3, 0.3))


# ─────────────────────────────── reverb ───────────────────────────────
def _comb(x, delay, g):
    """y[n] = x[n] + g·y[n−D], computed one delay-length block at a time."""
    y = array('f', x)
    for s in range(delay, len(y), delay):
        e = min(len(y), s + delay)
        y[s:e] = array('f', map(add, y[s:e], map(_mul, y[s - delay:e - delay], repeat(g, e - s))))
    return y


def _allpass(x, delay, g=0.5):
    """Schroeder all-pass y[n] = −g·x[n] + x[n−D] + g·y[n−D], block-wise like _comb."""
    y = array('f', map(_mul, x, repeat(-g, len(x))))
    for s in range(0, len(y), delay):
        e = min(len(y), s + delay)
        if s >= delay:
            y[s:e] = array('f', map(add, y[s:e], map(add, x[s - delay:e - delay], map(_mul, y[s - delay:e - delay], repeat(g, e - s)))))
    return y


def reverb(L, R, room=0.84, width=1.0):
    """Freeverb tunings with undamped combs; damping is a low-pass on the wet bus, applied in FFmpeg."""
    k, combs, alls = SR / 44100, (1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617), (556, 441, 341, 225)
    fb = 0.7 + 0.28 * min(max(room, 0.0), 1.0)

    def run(x, spread):
        x = array('f', map(_mul, x, repeat(0.015, len(x))))
        out = buf(len(x))
        for c in combs:
            out = array('f', map(add, out, _comb(x, int(round((c + spread) * k)), fb)))
        for a in alls:
            out = _allpass(out, int(round((a + spread) * k)))
        return out
    wl, wr = run(L, 0), run(R, 23)
    a, b = 2.5 * (1 + width) / 2, 2.5 * (1 - width) / 2          # Freeverb's wet scaling
    return (array('f', map(add, map(_mul, wl, repeat(a, len(wl))), map(_mul, wr, repeat(b, len(wr))))),
            array('f', map(add, map(_mul, wr, repeat(a, len(wr))), map(_mul, wl, repeat(b, len(wl))))))


# ─────────────────────────────── session ───────────────────────────────
INSTRUMENTS = ('kick', 'snare', 'clap', 'hat', 'crash', 'tom', 'shaker', 'rim', 'bass', 'sub', 'pad', 'pluck', 'keys', 'bell',
               'lead', 'mallet', 'riser', 'downlifter', 'whoosh', 'impact', 'boom', 'click', 'tick', 'pop', 'blip', 'swipe',
               'glitch', 'shimmer', 'ambience')
TOOLS = ('osc', 'noise', 'adsr', 'exp_env', 'mul', 'add_into', 'drive', 'fade', 'reverse', 'peak_norm', 'biquad',
         'lowpass', 'highpass', 'bandpass', 'stereo', 'midi', 'hz', 'chord', 'scale', 'rng')


class Bus:
    def __init__(self, session, name, gain=1.0, pan=0.0, reverb=0.0, highpass=None, lowpass=None, duck=0.0, width=1.0):
        for value, what in ((gain, 'gain'), (reverb, 'reverb'), (duck, 'duck')):
            if not isinstance(value, (int, float)) or value < 0:
                raise NTFError('score_parameters', f'总线 {name} 的 {what} 须为非负数。')
        self.session, self.name, self.gain, self.pan, self.reverb = session, name, gain, pan, reverb
        self.highpass, self.lowpass, self.duck, self.width = highpass, lowpass, min(duck, 1.0), width
        self.L, self.R = buf(session.n), buf(session.n)
        self.used = False

    def add(self, sound, t, gain=1.0, pan=0.0):
        """Place a mono array or a {'L', 'R'} pair at t seconds; t may be negative (the start is cut)."""
        at = int(round(t * SR))
        p = max(-1.0, min(1.0, pan + self.pan))
        if isinstance(sound, dict):
            gl = gain * min(1.0, math.cos((p + 1) * math.pi / 4) * math.sqrt(2))
            gr = gain * min(1.0, math.sin((p + 1) * math.pi / 4) * math.sqrt(2))
            add_into(self.L, sound['L'], at, gl)
            add_into(self.R, sound['R'], at, gr)
        else:
            add_into(self.L, sound, at, gain * math.cos((p + 1) * math.pi / 4))
            add_into(self.R, sound, at, gain * math.sin((p + 1) * math.pi / 4))
        self.used = True
        return self


class Session:
    SR = SR

    def __init__(self, duration):
        self.duration = float(duration)
        self.n = N(self.duration)
        self.buses, self.ducks, self.gaps = [], [], []
        self.space_options = {'room': 0.84, 'damp': 0.3, 'width': 1.0}
        self.master_options = {'lufs': -16.0, 'ceiling_db': -1.5}
        self.bpm, self.beats_per_bar = 120.0, 4
        for name in INSTRUMENTS + TOOLS:
            setattr(self, name, globals()[name])

    def tempo(self, bpm, beats_per_bar=4):
        if not bpm or bpm <= 0:
            raise NTFError('score_parameters', 'BPM 须为正数。')
        self.bpm, self.beats_per_bar = float(bpm), int(beats_per_bar)
        return self

    def beat(self, n=1):
        return n * 60 / self.bpm

    def bar(self, n=1):
        return n * self.beats_per_bar * 60 / self.bpm

    def steps(self, pattern, step=0.25, start=0):
        return [self.beat(b) for b in steps(pattern, step, start)]

    def swing(self, beat_pos, amount=1 / 3, grid=0.5):
        k = beat_pos / grid
        return self.beat(beat_pos + (amount * grid if int(round(k)) % 2 == 1 and abs(k - round(k)) < 1e-6 else 0))

    def humanize(self, t, ms=8, seed=1):
        h = int(hashlib.sha256(f'{seed}:{t:.6f}'.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        return t + (h - 0.5) * 2 * ms / 1000

    def bus(self, name, **options):
        if any(b.name == name for b in self.buses):
            raise NTFError('score_parameters', f'总线 {name} 重复定义。')
        b = Bus(self, name, **options)
        self.buses.append(b)
        return b

    def duck(self, t, depth=1.0, release=0.25):
        self.ducks.append((t, depth, release))

    def space(self, room=0.84, damp=0.3, width=1.0):
        self.space_options = {'room': room, 'damp': damp, 'width': width}

    def master(self, lufs=-16.0, ceiling_db=-1.5):
        """Loudness the mix is brought to before the peak limiter (compose normalises the film again)."""
        if not -30 <= lufs <= -8 or not -6 <= ceiling_db <= 0:
            raise NTFError('score_parameters', 'master 的 lufs 取 −30 到 −8，ceiling_db 取 −6 到 0。')
        self.master_options = {'lufs': float(lufs), 'ceiling_db': float(ceiling_db)}

    def gap(self, start, end, floor_db=-60):
        """A held breath: everything, reverb tails included, drops to floor_db between start and end."""
        if end <= start:
            raise NTFError('score_parameters', 'gap 的结束时间须晚于开始时间。')
        self.gaps.append((start, end, 10 ** (floor_db / 20)))


def _duck_envelope(session):
    env = array('f', repeat(1.0, session.n))
    for t, depth, release in session.ducks:
        s = int(round(t * SR))
        if s >= session.n:
            continue
        a, length = N(0.005), min(session.n - max(s, 0), N(release * 6))
        for i in range(length):
            k = s + i
            if k < 0:
                continue
            v = 1 - depth * (min(1.0, i / max(1, a)) if i < a else math.exp(-(i - a) / (release * SR)))
            if v < env[k]:
                env[k] = v
    return env


def _gap_envelope(session):
    env = array('f', repeat(1.0, session.n))
    ramp = N(0.03)
    for start, end, floor in session.gaps:
        s, e = int(round(start * SR)), int(round(end * SR))
        for k in range(max(0, s - ramp), min(session.n, e + ramp)):
            if k < s:
                v = 1 - (1 - floor) * (k - (s - ramp)) / ramp
            elif k < e:
                v = floor
            else:
                v = floor + (1 - floor) * (k - e) / ramp
            env[k] = min(env[k], v)
    return env


def _write_raw(path, L, R):
    inter = array('f', bytes(8 * len(L)))
    inter[0::2], inter[1::2] = L, R
    if sys.byteorder != 'little':
        inter.byteswap()
    with open(path, 'wb') as handle:
        inter.tofile(handle)


def render(score_file, output, *, duration=None, stems_dir=None):
    """Run a score file (`DUR` and `score(S)`) and write a 48 kHz stereo WAV. Returns a summary."""
    score_file = Path(score_file).resolve()
    sys.path.insert(0, str(score_file.parent))
    try:
        namespace = runpy.run_path(str(score_file), run_name='__ntf_score__')
    except NTFError:
        raise
    except Exception as exc:  # the score is user code: report where it failed
        raise NTFError('score_failed', f'配乐脚本运行出错：{type(exc).__name__}: {exc}', {'file': str(score_file)}) from exc
    finally:
        sys.path.remove(str(score_file.parent))
    fn = namespace.get('score')
    dur = duration if duration is not None else namespace.get('DUR')
    if not callable(fn):
        raise NTFError('score_parameters', '配乐脚本需要定义 score(S) 函数。', {'file': str(score_file)})
    if not isinstance(dur, (int, float)) or isinstance(dur, bool) or not math.isfinite(dur) or not 0 < dur <= 1200:
        raise NTFError('score_parameters', '配乐脚本须定义 DUR（0–1200 秒），或用 --duration 指定。', {'file': str(score_file)})
    session = Session(dur)
    try:
        fn(session)
    except NTFError:
        raise
    except Exception as exc:
        raise NTFError('score_failed', f'配乐脚本运行出错：{type(exc).__name__}: {exc}', {'file': str(score_file)}) from exc
    buses = [b for b in session.buses if b.used]
    if not buses:
        raise NTFError('score_parameters', '配乐脚本没有往任何总线里放声音。')
    duck = _duck_envelope(session) if session.ducks and any(b.duck for b in buses) else None
    gate = _gap_envelope(session) if session.gaps else None
    send_l, send_r = buf(session.n), buf(session.n)
    for b in buses:
        if duck is not None and b.duck:
            env = array('f', [1 - b.duck * (1 - v) for v in duck])
            b.L, b.R = array('f', map(_mul, b.L, env)), array('f', map(_mul, b.R, env))
        if b.reverb:
            add_into(send_l, b.L, 0, b.reverb * b.gain)
            add_into(send_r, b.R, 0, b.reverb * b.gain)
    tracks = [(b.name, b.L, b.R, b.gain, b.highpass, b.lowpass) for b in buses]
    if any(b.reverb for b in buses):
        opts = session.space_options
        wl, wr = reverb(send_l, send_r, opts['room'], opts['width'])
        tracks.append(('reverb', wl, wr, 1.0, None, 18000 - 15000 * min(max(opts['damp'], 0.0), 1.0)))
    if gate is not None:
        tracks = [(name, array('f', map(_mul, L, gate)), array('f', map(_mul, R, gate)), g, hp, lp) for name, L, R, g, hp, lp in tracks]
    with tempfile.TemporaryDirectory(prefix='.score-', dir=Path(output).parent) as staging:
        cmd, chains = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y'], []
        for i, (name, L, R, g, hp, lp) in enumerate(tracks):
            raw = Path(staging) / f'{i}.f32'
            _write_raw(raw, L, R)
            cmd += ['-f', 'f32le', '-ar', str(SR), '-ac', '2', '-i', str(raw)]
            steps_ = ([f'highpass=f={hp:g}'] if hp else []) + ([f'lowpass=f={lp:g}'] if lp else []) + [f'volume={g:g}']
            chains.append((name, ','.join(steps_)))
        graph, labels, outputs = [], [], []
        for i, (name, chain) in enumerate(chains):
            if stems_dir:
                graph.append(f'[{i}:a]{chain},asplit=2[m{i}][s{i}]')
                outputs.append((f'[s{i}]', Path(stems_dir) / f'{i + 1:02d}-{name}.wav'))
            else:
                graph.append(f'[{i}:a]{chain}[m{i}]')
            labels.append(f'[m{i}]')
        graph.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0,"
                     f"highpass=f=24,atrim=end={session.duration:.6f}[out]")
        mix = Path(staging) / 'mix.wav'
        cmd += ['-filter_complex', ';'.join(graph), '-map', '[out]', '-c:a', 'pcm_f32le', '-ar', str(SR), str(mix)]
        if stems_dir:
            Path(stems_dir).mkdir(parents=True, exist_ok=True)
            for label, target in outputs:   # stems are pre-master: 32-bit float keeps their peaks
                cmd += ['-map', label, '-c:a', 'pcm_f32le', str(target)]
        _ffmpeg(cmd, '配乐混音失败。')
        # master: measure the mix, bring it to the target loudness, then catch the peaks
        measured = _ffmpeg(['ffmpeg', '-hide_banner', '-nostdin', '-i', str(mix), '-af',
                            'loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'], '配乐响度测量失败。')
        found = re.search(r'"input_i"\s*:\s*"(-?[\d.]+|-inf)"', measured.stderr)
        level = float(found.group(1)) if found and found.group(1) != '-inf' else None
        opts = session.master_options
        gain_db = 0.0 if level is None else max(-40.0, min(40.0, opts['lufs'] - level))
        ceiling = 10 ** (opts['ceiling_db'] / 20)
        def finish(limiter):
            return subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-i', str(mix), '-af',
                                   f'volume={gain_db:.3f}dB,{limiter},atrim=end={session.duration:.6f}',
                                   '-c:a', 'pcm_s16le', '-ar', str(SR), str(output)], capture_output=True, text=True, timeout=900)
        limiter = f'alimiter=limit={ceiling:.4f}:attack=5:release=60'
        done = finish(limiter + ':level=disabled')       # newer FFmpeg would otherwise raise the output to the ceiling
        if done.returncode and 'level' in done.stderr:
            done = finish(limiter)
        if done.returncode:
            raise NTFError('media_command_failed', '配乐母带处理失败。', {'stderr': done.stderr[-3000:]})
    return {'duration_seconds': round(session.duration, 3), 'mix_lufs_before_master': level, 'master_gain_db': round(gain_db, 2),
            'master': session.master_options, 'buses': [name for name, *_ in tracks],
            'ducks': len(session.ducks), 'gaps': [[a, b] for a, b, _ in session.gaps],
            'stems': [str(t) for _, t in outputs] if stems_dir else []}


def _ffmpeg(cmd, message):
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if done.returncode:
        raise NTFError('media_command_failed', message, {'stderr': done.stderr[-3000:]})
    return done


def _fingerprint(score_file, duration):
    from .io import file_digest
    folder = score_file.parent
    files = sorted(p for p in folder.rglob('*') if p.is_file() and p.suffix in ('.py', '.json', '.js', '.txt', '.csv')
                   and not any(part.startswith(('.', '__')) for part in p.relative_to(folder).parts))
    payload = repr([[p.relative_to(folder).as_posix(), file_digest(p)] for p in files] + [duration, file_digest(Path(__file__))])
    return hashlib.sha256(payload.encode()).hexdigest()


def score_project(project, file, *, select=None, duration=None, stems=False, force=False):
    from .project import check_id
    from .io import atomic_json, file_digest
    slot = check_id(select or 'film.score', 'selection slot')
    path = Path(file).expanduser()
    path = (path if path.is_absolute() else project.root / path).resolve()
    if not path.is_relative_to(project.root.resolve()) or not path.is_file() or path.suffix != '.py':
        raise NTFError('score_parameters', '配乐脚本须是项目内的 .py 文件。', {'file': str(path)})
    if duration is not None and (isinstance(duration, bool) or not math.isfinite(duration) or duration <= 0):
        raise NTFError('score_parameters', '--duration 须为正的秒数。')
    if shutil.which('ffmpeg') is None:
        raise NTFError('ffmpeg_missing', '需要 FFmpeg 才能混音。')
    rel = path.relative_to(project.root.resolve()).as_posix()
    fingerprint = _fingerprint(path, duration)
    if not force and not stems:
        for asset in project.state['assets'].values():
            source = asset.get('source', {})
            if source.get('type') == 'score' and source.get('fingerprint') == fingerprint:
                target = project.path(asset['path'])
                if target.is_file() and file_digest(target) == asset['sha256']:
                    project.select(slot, [asset['id']])
                    return {'status': 'reused', 'file': rel, 'selection_slot': slot, 'asset_id': asset['id'], 'path': asset['path']}
    job = project.root / 'work' / ('score_' + uuid.uuid4().hex[:12])
    job.mkdir(parents=True)
    partial = job / 'score.wav'
    summary = render(path, partial, duration=duration, stems_dir=job / 'stems' if stems else None)
    destination = project.root / 'assets/audio' / ('score_' + uuid.uuid4().hex[:16] + '.wav')
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial.replace(destination)
    asset = project.register_file(destination, 'audio', {'type': 'score', 'file': rel, 'fingerprint': fingerprint}, slot)
    result = {'status': 'rendered', 'file': rel, 'selection_slot': slot, 'asset_id': asset['id'], 'path': asset['path'], **summary}
    if stems:
        result['stems'] = [Path(s).relative_to(project.root).as_posix() for s in summary['stems']]
    atomic_json(job / 'score.json', result)
    return result


if __name__ == '__main__':  # pragma: no cover - handy for listening to a score outside a project
    if len(sys.argv) < 3:
        print('usage: python -m notetofilm_local.synth SCORE.py OUT.wav', file=sys.stderr)
        sys.exit(2)
    print(render(sys.argv[1], sys.argv[2]))
    os._exit(0)
