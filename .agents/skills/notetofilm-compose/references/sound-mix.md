# 声音后期：底声、音效与音乐让位

旁白由每镜的 `audio` 和 `audio_policy` 处理；环境底声、音效和音乐在合成清单里只有一条 `background_audio`，按固定音量叠加，不会在旁白处自动压低。所以先把这三层按时间预混成一条底声文件，导入后作为 `background_audio`，音量设 `1.0`，电平在预混时定好。

## 四层的顺序

1. 旁白：先确认在普通音量下清楚，`ntf inspect FILM --audio-check` 看响度和真峰值。
2. 环境底声：让停顿处不掉成无声。来源可以是用户录音、实测有声的模型原声，或工具箱里的房间底噪。
3. 音效：只放在有物理或信息原因的动作上（通知到达、放稳、扫描）。时间取段落卡和动画 `timing.js` 里的同一个事件时点，换成全片时间（镜头起点加镜内秒数）。
4. 音乐：用户提供或已授权的曲子，或用 `ntf score` 写的原创配乐（见下文“代码合成配乐”）；旁白期间让位，语义段落结束后再回升。讲解片里没有合适的音乐时不配。

## 时间规则

- 动作音效落在动作发生的那一帧；“嗖”这类转场声的最响点对准切点，所以要提前放（本页的呼啸声最响处在 0.42 秒，放在切点前 0.42 秒）。
- 关键句前后不堆音效；两段旁白之间的短停顿里不让音乐反复升降，整个语义段落保持低位。
- 下一场的环境声可以在切点前进入（声音先行），上一场的环境声可以延续过切点（声音延续）。
- 片尾留一点自然的尾音，最后一个字和音乐不同时被切断。

## 简单音效

没有现成音效时，本机 FFmpeg 可以合成几种干净的提示音。它们是占位和简单讲解片够用的声音；需要真实材质（纸箱、金属、脚步）时用用户提供或有授权的音效。

```bash
# 两音提示（消息到达），约 0.42 秒
ffmpeg -f lavfi -i "sine=frequency=880:duration=0.18:sample_rate=48000" -f lavfi -i "sine=frequency=1320:duration=0.30:sample_rate=48000" \
 -filter_complex "[0:a]afade=t=out:st=0.04:d=0.14[a];[1:a]afade=t=out:st=0.05:d=0.25,adelay=120:all=1[b];[a][b]amix=inputs=2:duration=longest:normalize=0,volume=0.5,aformat=channel_layouts=stereo" chime.wav
# 轻触（点击、吸附），0.04 秒
ffmpeg -f lavfi -i "anoisesrc=color=white:duration=0.04:seed=3:sample_rate=48000" -af "highpass=f=1800,afade=t=out:st=0:d=0.04:curve=exp,volume=0.6,aformat=channel_layouts=stereo" click.wav
# 落位轻响（放稳、到位），0.35 秒
ffmpeg -f lavfi -i "sine=frequency=95:duration=0.35:sample_rate=48000" -f lavfi -i "anoisesrc=color=brown:duration=0.12:seed=5:sample_rate=48000" \
 -filter_complex "[0:a]afade=t=out:st=0:d=0.35:curve=exp[a];[1:a]lowpass=f=500,afade=t=out:st=0:d=0.12[b];[a][b]amix=inputs=2:duration=longest:normalize=0,volume=0.8,aformat=channel_layouts=stereo" thud.wav
# 呼啸（甩镜、穿越），0.6 秒，最响处在 0.42 秒
ffmpeg -f lavfi -i "anoisesrc=color=pink:duration=0.6:seed=9:sample_rate=48000" -af "highpass=f=250,lowpass=f=3500,afade=t=in:st=0:d=0.42:curve=exp,afade=t=out:st=0.42:d=0.18,volume=0.7,aformat=channel_layouts=stereo" whoosh.wav
```

改频率、时长和 `seed` 可以让本片的提示音和别的片子不一样。需要成套的提示音、转场声、环境声或整首配乐时，用下文的 `ntf score`。房间底噪的做法见 [本机工具箱](toolbox.md)。

## 代码合成配乐

无口播的宣传片、片头、落版和方向小样，节奏由音乐组织，画面卡在拍上。没有现成曲子时，用 `ntf score` 写一首原创配乐：一个 Python 脚本定义 `DUR` 和 `score(S)`，音符、鼓点和音效都按秒数放，脚本与代码动画读同一份时间表，切点、重拍和音效自然对齐。只用标准库，固定种子，同样的脚本得到同样的声音；20 秒的配乐约需十几秒合成。乐器配方和接口改编自 garden-skills motion-showreel 的内置合成器。

```python
"""animation/score.py：和画面共用 animation/timeline.json"""
import json
from pathlib import Path
TL = json.loads((Path(__file__).parent / 'timeline.json').read_text())
DUR, T = TL['dur'], TL['T']

def score(S):
    S.tempo(TL.get('bpm', 120))                      # S.beat(n)、S.bar(n) → 秒
    drums = S.bus('drums', gain=0.9)
    bass = S.bus('bass', gain=0.6, duck=0.5)
    music = S.bus('music', gain=0.5, reverb=0.3, highpass=180, duck=0.6)
    sfx = S.bus('sfx', gain=0.8, reverb=0.15)
    for t in S.steps('x.x.x.x.x.x.x.x.', 0.5):                 # 每拍一下底鼓，共八拍
        drums.add(S.kick(), t); S.duck(t, 0.8)                  # 侧链：bass、music 在底鼓处让位
    bass.add(S.bass('D2', S.bar(2)), 0)
    music.add(S.pad(S.chord('D3', 'm9'), S.bar(2)), 0)
    sfx.add(S.whoosh(0.6, peak=0.7), T['cut'] - 0.6 * 0.7)      # 最响点对准切点
    S.gap(T['drop'] - S.beat(0.5), T['drop'])                  # 重拍前真的空半拍，混响尾巴一起收
    drums.add(S.impact(), T['drop'])
```

```bash
ntf score PROJECT --file animation/score.py --select film.background
ntf inspect PROJECT/assets/audio/score_….wav --audio-check --drop 8.0 --output work/qa-score-v1
```

清单里写 `"background_audio": {"selection": "film.background", "volume": 1.0}`。

接口要点（参数名用 Python 写法，如 `pitch_decay`、`env_amt`、`drive_amt`；上升音效的起止频率写 `start`、`end`）：

| 类别 | 写法 |
|---|---|
| 节奏与和声 | `S.tempo(bpm, beats_per_bar=4)`、`S.beat(n)`、`S.bar(n)`、`S.steps('x..x', step=0.25)`、`S.swing(n)`、`S.humanize(t, ms=8)`；`S.midi('C#4')`、`S.hz('A4')`、`S.chord(root, 'm9', inversion)`、`S.scale(root, 'dorian')(degree)`，五声调式有 `gong shang jue zhi yu` |
| 总线 | `S.bus(name, gain, pan, reverb, highpass, lowpass, duck)`；`bus.add(sound, t, gain=1, pan=0)`，t 可以为负 |
| 全片 | `S.duck(t, depth, release)` 侧链触发点；`S.space(room=0.84, damp=0.3, width=1)` 共享混响；`S.gap(start, end)` 静半拍；`S.master(lufs=-16, ceiling_db=-1.5)` |
| 鼓 | `kick` `snare` `clap` `hat(open=)` `crash` `tom(note)` `shaker` `rim` |
| 低音与和声 | `bass(note, dur)` `sub(note, dur, harm=0.15)` `pad(notes, dur, voices=3, cutoff=1800)` `keys(notes, dur)`（FM 电钢琴） |
| 旋律 | `pluck(note, dur, bright, damp)`（拨弦，低 bright 高 damp 接近尼龙弦、古琴） `mallet(note, dur, material='marimba')`（xylo、vibes、glock、kalimba、steel、wood） `bell(note, dur)` `lead(note, dur)` |
| 音效 | `riser(dur)` `downlifter(dur)` `whoosh(dur, peak=0.7)` `impact(size)` `boom()` `click()` `tick()` `pop(note)` `blip(note)` `swipe(dur)` `glitch(dur)` `shimmer(dur, root)` |
| 环境 | `ambience(dur, kind='room')`，kind 可选 tape、vinyl、wind、rain |
| 底层 | `osc(n, freq, wave)` `noise(sec, seed)` `adsr` `exp_env` `biquad` `lowpass` `highpass` `bandpass` `drive` `fade` `reverse` `mul` `add_into`，自己做这支片子独有的声音 |

乐器返回单声道数组，`pad`、`whoosh`、`ambience` 返回 `{'L', 'R'}`。内置音色是素材：改参数、换种子、叠两层，往往比默认值更像这支片子的声音。

写法要点：

- **先定声音方向**（direct 的声音设计）：对标、音乐角色、曲线和母题写进备稿，再写脚本。没有方向时合成配乐会收敛成同一首歌：A 小调、120 BPM 四拍底鼓、每个重拍撞击加镲、钟声落版、锯齿铺底当万能垫子。同一目录做过的片子，至少换掉曲线、配器或调式中的两项。
- **时间来自时间表**：音效落在动作那一帧；呼啸声的最响点在 `peak × dur`，放在切点之前这么久；吸气 → 爆发的曲线用 `S.gap` 在重拍前空半拍，空完后的第一个声音是全片最重要的声音之一。
- **低频要收住**：铺底和旋律总线加 `highpass` 150–250；底鼓衰减不超过 0.45 秒；贝斯低于 MIDI 40 时手机外放听不见，靠 `sub` 的 `harm` 或锯齿波的泛音带出来。混响只发送给 music 和 sfx（0.15–0.35），鼓和贝斯保持干声。
- **侧链是一种风格**：`duck` 的泵感属于电子舞曲；电影感、手作、东方写意的片子不开侧链。
- **母带**：混好后自动拉到 −16 LUFS，峰值限制在 −1.5 dBFS；合成时 compose 再按清单统一响度。

检查：`ntf inspect FILE --audio-check --drop 重拍秒数 --output DIR` 给出倍频程平衡、重拍前的凹陷量和波形、频谱图。凹陷不到 4 dB 说明鼓或铺底没停；低频比 1 kHz 高出 14 dB 以上会轰。打开 `audio_wave.png` 看音量起伏是否和所选曲线一致（吸气 → 爆发在重拍处最满，累加一路变厚，抽空处断崖），`audio_spectrum.png` 看低频是否一直轰着、高频是否完全没有。哪一轨出了问题，加 `--stems` 重渲，逐条听或看分轨。Agent 听不到声音，交付时写明听感未经人耳确认，请用户开声音看一遍。

## 按时间表预混底声

先用 `ntf compose PROJECT --manifest FILE --plan-only` 得到全片的时间安排。脚本所需的 `duration_seconds` 和 `scenes` 可从命令输出的 JSON 或合成后的 `timeline.json` 读取。把下面的脚本存进项目（例如 `work/premix_bed.py`），用 NoteToFilm CLI 的 Python 或系统 Python 运行，只依赖标准库和 FFmpeg。

```python
"""按合成时间表预混一条底声：房间底噪、定时音效，以及在旁白处让位的音乐。"""
import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--timeline', required=True)                 # compose --plan-only 的输出或 timeline.json
p.add_argument('--output', required=True)                   # 新文件，不覆盖已导入的素材
p.add_argument('--room')                                    # 房间底噪，循环铺满全片
p.add_argument('--music')                                   # 用户提供或已授权的音乐
p.add_argument('--music-gain-db', type=float, default=-18)  # 没有旁白时的音乐电平
p.add_argument('--duck-db', type=float, default=-10)        # 旁白期间再降低多少
p.add_argument('--ramp', type=float, default=0.6)           # 降低与恢复的过渡秒数
p.add_argument('--merge-gap', type=float, default=1.5)      # 两段旁白间隔短于此值时音乐不回升
p.add_argument('--sfx', action='append', default=[])        # 秒数:文件:增益dB，可重复
a = p.parse_args()
output = Path(a.output)
output_exists = f'输出文件 {output} 已存在，请为 --output 指定新文件名。'
if output.exists() or output.is_symlink():
    p.error(output_exists)

timeline = json.load(open(a.timeline, encoding='utf-8'))
total = float(timeline['duration_seconds'])
windows = sorted([s['start_seconds'] + s['audio']['start_seconds'],
                  s['start_seconds'] + s['audio']['start_seconds'] + s['audio']['duration_seconds']]
                 for s in timeline['scenes'] if s.get('audio'))
merged = []
for start, end in windows:
    if merged and start - merged[-1][1] < a.merge_gap:
        merged[-1][1] = max(merged[-1][1], end)
    else:
        merged.append([start, end])

cmd, filters, labels = ['ffmpeg', '-v', 'error', '-nostdin', '-n'], [], []
fmt = 'aformat=sample_rates=48000:channel_layouts=stereo'
def add(path, loop=False):
    cmd.extend((['-stream_loop', '-1'] if loop else []) + ['-i', path])
    return cmd.count('-i') - 1
if a.room:
    filters.append(f'[{add(a.room, loop=True)}:a]{fmt},atrim=end={total}[room]'); labels.append('[room]')
if a.music:
    r, level = a.ramp, '0'
    for s, e in merged:   # 每段旁白前后 r 秒内线性降低和恢复，取各段的最大值
        term = f'clip(min((t-{s - r:.3f})/{r},({e + r:.3f}-t)/{r}),0,1)'
        level = term if level == '0' else f'max({level},{term})'
    gain = f'{10 ** (a.music_gain_db / 20):.5f}*(1-{1 - 10 ** (a.duck_db / 20):.5f}*{level})'
    filters.append(f"[{add(a.music)}:a]{fmt},atrim=end={total},volume='{gain}':eval=frame[music]"); labels.append('[music]')
for k, item in enumerate(a.sfx):
    at, rest = item.split(':', 1); path, db = rest.rsplit(':', 1)
    filters.append(f'[{add(path)}:a]{fmt},volume={db}dB,adelay={round(float(at) * 1000)}:all=1[s{k}]'); labels.append(f'[s{k}]')
filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0,apad,atrim=end={total}[bed]")

with tempfile.TemporaryDirectory(prefix='.premix-', dir=output.parent) as staging:
    rendered = Path(staging) / output.name
    subprocess.run(cmd + ['-filter_complex', ';'.join(filters), '-map', '[bed]', '-c:a', 'pcm_s16le', str(rendered)], check=True)
    try:
        destination = output.open('xb')
    except FileExistsError:
        p.error(output_exists)
    try:
        with destination, rendered.open('rb') as source:
            shutil.copyfileobj(source, destination)
    except BaseException:
        output.unlink(missing_ok=True)
        raise

print(json.dumps({'output': a.output, 'duration_seconds': total, 'narration_windows': merged}, ensure_ascii=False))
```

```bash
ntf compose PROJECT --manifest work/manifest.json --plan-only > work/plan.json
python3 work/premix_bed.py --timeline work/plan.json --output work/bed-v1.wav \
  --room work/roomtone.wav --music sources/music.wav \
  --sfx 7.4:work/chime.wav:-6 --sfx 15.58:work/whoosh.wav:-8 --sfx 21.5:work/thud.wav:-4
ntf import PROJECT work/bed-v1.wav --select film.background
```

预混输出已存在时，换用一个新文件名。清单里写 `"background_audio": {"selection": "film.background", "volume": 1.0}`，再正式合成。片子的剪辑、旁白或转场改了，先重跑 `--plan-only` 取得新的镜头时间，再预混一个新版本。

起点参数：音乐在无旁白处约 −18 dB，旁白期间再降 6–12 dB，过渡 0.3–1 秒。旁白片按结果核对：说话时配乐合计比人声低 15 dB 以上，铺底长音更低，或者说话时停掉、只在开头、转折和结尾出现；压在说话上的音效比人声低 10 dB 以上。这些是第一次试混的起点，按曲子的鼓点、旋律和低频调整，突出的鼓点和旋律即使平均电平低也会干扰人声。只有室内底噪时不必设让位。

## 检查

- `ntf inspect FILM --decode --audio-check` 看整体响度和真峰值；`ntf inspect FILM --scan --timeline TIMELINE` 的静音区间核对底声是否连续，`digital_silence_seconds` 应只出现在有意的黑场或静默处。
- 合成把每镜时长取整到帧，镜头多时成片会比时间表总长多出零点几秒。配乐或底声只写到时间表总长，片尾就会出现一小段数字静音。底噪多铺约 1 秒，音乐的收尾仍按时间表安排。
- 验证音乐让位时，用同一份时间表单独预混两条音乐检查轨。只传 `--music`，一条使用计划中的 `--duck-db`，另一条设 `--duck-db 0`，分别输出到新文件。用 `ffmpeg -i work/music-duck.wav -map 0:a:0 -af "atrim=start=20.7:duration=0.6,astats=metadata=0" -f null -` 读取 `RMS level dB`。两条轨都截取时间表中同一个旁白内部的窗口，按实际位置调整 `start` 和 `duration`。成片的混合音轨用于检查整体响度和旁白清晰度。
- 旁白片听着“有底噪”“音效乱”时，先把三层分开量：按时间表把各镜配音放回原位，合成一条旁白轨；配乐和音效按预混时的增益和让位各算一条；再按 0.5 秒窗口算各自电平。看说话的时段：配乐的能量平均比人声低多少（目标 15 dB 以上），音效有几处和人声相差不到 10 dB、落在哪几秒。铺底长音只比人声低几 dB 时，听起来就是背景噪声；比人声还响的音效，多半是给镜头运动配的气流声。单个窗口可以用上面的 `astats` 读法核对。
- 说话时去掉配乐以后，句子之间常掉成数字零，戴耳机听像断音。铺一层很轻的房间底噪（工具箱“房间底噪”），比人声低 20 dB 以上就够，再用 `--scan` 确认 `digital_silence_seconds` 归零。
- 能试听的人用耳机和手机扬声器各听一次：第一句话是否完整进入，镜头切换时环境声是否突变，关键数字是否被音乐盖住，片尾是否自然结束。Agent 听不到声音时，在交付说明里写明听感未经人耳确认。
