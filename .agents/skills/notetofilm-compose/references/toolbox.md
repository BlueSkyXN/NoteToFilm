# 本机工具箱：ffmpeg、ImageMagick 与 Python

`ntf` 管项目状态、采用关系和成片。`ntf` 命令没有覆盖的画面处理，可以直接用本机工具做出素材文件，再用 `ntf import PROJECT FILE --select SLOT` 登记，合成清单按 `selection` 引用。先用 `ntf install-info` 和 `command -v magick` 等确认工具存在。命令写进项目备稿，改了输入后能重新生成；输出写到新文件，不覆盖已登记的素材。

## 画面内布局（分屏、画中画、宫格）

`ntf motion` 能把多个图片、视频放进画面的不同区域，但视频层不带声音。需要保留其中一路原声时，用 ffmpeg 直接合成布局，`-map` 选要保留的声音：

```bash
# 左右分屏，保留左边的声音；force_original_aspect_ratio=decrease 加 pad 是完整放入、留边，
# 改成 increase 加 crop=640:720 是裁满
ffmpeg -i left.mp4 -i right.mp4 -filter_complex \
 "[0:v]scale=640:720:force_original_aspect_ratio=decrease,pad=640:720:(ow-iw)/2:(oh-ih)/2,setsar=1[l];\
  [1:v]scale=640:720:force_original_aspect_ratio=decrease,pad=640:720:(ow-iw)/2:(oh-ih)/2,setsar=1[r];\
  [l][r]hstack=inputs=2[v]" -map "[v]" -map 0:a -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest split.mp4

# 画中画：小窗加 4 像素白边放右下角，保留小窗的声音
ffmpeg -i main.mp4 -i inset.mp4 -filter_complex \
 "[1:v]scale=384:-2,pad=iw+8:ih+8:4:4:color=white[p];[0:v][p]overlay=W-w-40:H-h-40[v]" \
 -map "[v]" -map 1:a -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest pip.mp4

# 四宫格，无声
ffmpeg -i a.mp4 -i b.mp4 -i c.mp4 -i d.mp4 -filter_complex \
 "[0:v]scale=640:360,setsar=1[a];[1:v]scale=640:360,setsar=1[b];[2:v]scale=640:360,setsar=1[c];[3:v]scale=640:360,setsar=1[d];\
  [a][b][c][d]xstack=inputs=4:layout=0_0|w0_0|0_h0|w0_h0[v]" -map "[v]" -an -c:v libx264 -pix_fmt yuv420p grid.mp4
```

导入后在合成清单里用 `audio_policy: "native"` 保留这路声音，或用 `mix` 叠加旁白。每路先用 `ntf sheet` 看原片、定好采用区间（`-ss`、`-t` 截取），再做布局。需要标签、箭头或逐步显露时，把布局视频作为 `ntf motion` 的视频层，再叠 draw 图层，声音在合成时按上面的方式取原片。

## 素材加工

```bash
ffmpeg -i clip.mp4 -vn -c:a pcm_s16le native.wav                  # 抽出原声，作为独立音频导入
ffmpeg -sseof -0.1 -i clip.mp4 -frames:v 1 -update 1 last.png      # 取最后一帧，作首帧或审看
ffmpeg -ss 2.5 -i clip.mp4 -frames:v 1 still.png                   # 取指定时刻的一帧
ffmpeg -i green.mp4 -i bg.mp4 -filter_complex "[0:v]colorkey=0x00FF00:0.3:0.1[k];[1:v][k]overlay[v]" \
 -map "[v]" -an -c:v libx264 -pix_fmt yuv420p keyed.mp4            # 绿幕抠像后叠到背景上
```

### 局部去字

生成视频里的端口编号、条码或伪文字，在固定镜头中可以只模糊那一块。先用 `ntf sheet` 和放大的关键帧确定区域与时段，`crop` 的宽、高、x、y 与 `overlay` 的位置相同，`enable` 限定时段：

```bash
ffmpeg -i clip.mp4 -filter_complex \
 "[0:v]split[a][b];[b]crop=360:56:295:568,boxblur=10:2[bl];[a][bl]overlay=295:568:enable='between(t,10.4,15.3)'[v]" \
 -map "[v]" -map 0:a -c:v libx264 -crf 17 -pix_fmt yuv420p -c:a copy clean.mp4
```

处理后用 `ntf compare clip.mp4@时刻 clean.mp4@时刻 --crop 区域 --cell-width 640` 放大对比，确认字已看不清、模糊块不显眼。镜头在推拉或横移时文字位置一直变化，固定区域遮不住，改为重新生成或换镜头。

### 房间底噪与停顿电平

生成视频的原生声音常常大段静音；图解页本身没有声音。句间停顿掉到 -90 dB 时听起来像断线，可以铺一层很轻的房间底噪作为 `background_audio`：

```bash
ffmpeg -f lavfi -i "anoisesrc=color=brown:amplitude=0.5:seed=7:sample_rate=48000:duration=30" \
 -af "highpass=f=50,lowpass=f=900,volume=-21dB,aformat=channel_layouts=stereo,afade=t=in:d=0.05,afade=t=out:st=29.95:d=0.05" roomtone.wav
ffmpeg -i roomtone.wav -af astats=metadata=0 -f null - 2>&1 | grep 'RMS level'   # 目标约 -46 dB
```

导入后 `--select film.background`，清单里 `"background_audio": {"selection": "film.background", "volume": 1.0, "loop": true}`。合成后用 `ntf inspect FILM --scan` 确认各静音区间的 `digital_silence_seconds` 为 0。抽测某一时刻的电平用采样精确的截取：`ffmpeg -i film.mp4 -map 0:a -af "atrim=start=20.7:duration=0.6,volumedetect" -f null -`；把 `-ss`、`-t` 放在 `-i` 前截取不到一秒的片段时，读数可能不准。

本机 FFmpeg 若没有 `drawtext` 和 `subtitles` 滤镜，文字用合成清单的 `text_overlays`、`ntf motion` 或 ImageMagick 生成。

## 图片排版（ImageMagick 7）

```bash
# 左侧放画面、右侧放准确文字的说明卡；中文字体用本机实际存在的字体文件
magick -size 1280x720 xc:'#F2F0EA' \( shot.png -resize 600x \) -geometry +60+150 -composite \
 -font /path/to/cjk-font.ttc -pointsize 44 -fill '#1E2328' -annotate +700+200 '标题' \
 -pointsize 26 -fill '#5A6068' -annotate +700+260 '说明文字' panel.png

# 把透明背景的物件（例如 GPT Image 用 background: transparent 生成的 PNG）叠到指定位置
magick panel.png object.png -geometry +900+380 -composite composed.png

magick a.png b.png +append side.png            # 横向拼接；-append 为纵向
magick in.png -resize 1280x720^ -gravity center -extent 1280x720 filled.png   # 裁满到 16:9
magick in.png -trim +repage trimmed.png        # 去掉透明或纯色边
```

## Python

NoteToFilm CLI 的 Python 环境带 Pillow。系统 Python 常见的 numpy、OpenCV、scipy、matplotlib 也能用于一次性处理：例如用 matplotlib 画准确的图表再导入，用 OpenCV 做颜色统计或光流检查。脚本放在项目内，输出作为新素材导入；用到的库写进备稿，不当作 CLI 依赖。
