# 声音后期：底声、音效与音乐让位

旁白由每镜的 `audio` 和 `audio_policy` 处理；环境底声、音效和音乐在合成清单里只有一条 `background_audio`，按固定音量叠加，不会在旁白处自动压低。所以先把这三层按时间预混成一条底声文件，导入后作为 `background_audio`，音量设 `1.0`，电平在预混时定好。

## 四层的顺序

1. 旁白：先确认在普通音量下清楚，`ntf inspect FILM --audio-check` 看响度和真峰值。
2. 环境底声：让停顿处不掉成无声。来源可以是用户录音、实测有声的模型原声，或工具箱里的房间底噪。
3. 音效：只放在有物理或信息原因的动作上（通知到达、放稳、扫描）。时间取段落卡和动画 `timing.js` 里的同一个事件时点，换成全片时间（镜头起点加镜内秒数）。
4. 音乐：只用用户提供或已授权的曲子；旁白期间让位，语义段落结束后再回升。没有可用音乐时不配。

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

改频率、时长和 `seed` 可以让本片的提示音和别的片子不一样。房间底噪的做法见 [本机工具箱](toolbox.md)。

## 按时间表预混底声

先得到全片的时间安排：`ntf compose PROJECT --manifest FILE --plan-only` 输出的 JSON 和合成后的 `timeline.json` 结构相同，都可以用。把下面的脚本存进项目（例如 `work/premix_bed.py`），用 NoteToFilm CLI 的 Python 或系统 Python 运行，只依赖标准库和 FFmpeg。

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

起点参数：音乐在无旁白处约 −18 dB，旁白期间再降 6–12 dB，过渡 0.3–1 秒；这些是第一次试混的起点，按曲子的鼓点、旋律和低频调整，突出的鼓点和旋律即使平均电平低也会干扰人声。只有室内底噪时不必设让位。

## 检查

- `ntf inspect FILM --decode --audio-check` 看整体响度和真峰值；`ntf inspect FILM --scan --timeline TIMELINE` 的静音区间核对底声是否连续，`digital_silence_seconds` 应只出现在有意的黑场或静默处。
- 抽测某一段的电平用采样精确的截取：`ffmpeg -i film.mp4 -map 0:a -af "atrim=start=20.7:duration=0.6,astats=metadata=0" -f null -`，比较旁白段和停顿段，确认音乐在说话时确实低下去了。
- 能试听的人用耳机和手机扬声器各听一次：第一句话是否完整进入，镜头切换时环境声是否突变，关键数字是否被音乐盖住，片尾是否自然结束。Agent 听不到声音时，在交付说明里写明听感未经人耳确认。
