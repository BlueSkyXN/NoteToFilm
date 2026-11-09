# 明确合成清单

所有媒体先导入项目；path 使用项目内相对路径。下面是假定文件已经存在的结构示例，不是可替代真实媒体的占位成片。

```json
{
  "output": {"width":1280,"height":720,"fps":30},
  "scenes": [{
    "id":"s01",
    "visuals":[{"path":"assets/images/intro.png","kind":"image","fit":"contain"}],
    "audio":{"path":"assets/audio/intro.mp3"},
    "audio_policy":"edge_tts"
  }]
}
```

视频视觉项使用 kind=video；trim_start、duration_seconds 与明确的 hold 决定使用范围。真实媒体长度与用户方案不一致时先修正安排，不静默裁断旁白。

一幕可组合多条素材，分别写采用起点和长度；各段长度之和应满足镜头窗口。模型多返回一帧不自动扩大窗口。后期图解、准确关键词和旁白字幕保持独立，改文字时复用已通过验收的视频。

## 视频采用范围与变速

```json
{"path":"assets/videos/clip.mp4","kind":"video","trim_start":2,
 "source_duration_seconds":6,"duration_seconds":4,"speed":"fit"}
```

这段选择源片第 2 至 8 秒，完整播放到 4 秒输出窗口。`speed` 可为 0.01–100 的数值倍率，或 `fit`；默认 1。`fit` 需要可确定的输出窗口，可以来自该视觉项、单镜 duration_seconds 或实际旁白。按完整输出帧计算最终倍率，时间表记录 `source_used_seconds`、`source_end_seconds`、速度与实际输出时长。

省略 `source_duration_seconds` 时从 trim_start 使用到源片末尾；数值速度且未指定输出长度时，由源区间除以速度确定。数值速度下输出窗口更短会明确裁取对应源区间；更长须显式 hold 或补素材。图片不接受视频变速参数。

native/mix 中采用的原声同步变速并保持音高；独立旁白保持原速。变速不能用于截掉旁白或掩盖错误动作，仍需观看实际结果。

## 跨镜转场

在后一个镜头上设置进入它的转场：

```json
{"id":"s02","transition":{"type":"fade","duration_seconds":0.3}}
```

该片段仅说明字段，实际镜头仍须提供 visuals、声音策略和时间。支持 cut，以及 fade、dissolve、wipeleft/wiperight、slideleft/slideright。默认 cut 保持原有行为；首镜不能设置与前镜的重叠转场。

转场将前后两个镜头重叠，视频与原音轨使用相同窗口；全片时长等于各镜头时长之和减去重叠时长。转场长度向上对齐到完整帧，每镜需保留至少一帧非重叠部分。字幕、定时文字和背景轨按调整后的全片时间安排。

程序会检查独立旁白是否同时讲话、两镜字幕是否重叠。需要两段旁白同时出现时可明确 `allow_narration_overlap:true`，字幕仍须安排在可读窗口。通常先用尾部停顿和下一镜的开头余量容纳转场，再看实际衔接。`timing --apply` 和 compose 时间表均计入转场重叠。

`--plan-only` 返回安排而不进行实际编码。要求 MP4 时必须完成实际合成并取得输出文件。
# 图片、视频与独立音轨混排

以下素材先通过 `ntf import` 导入到采用位置。使用 `--plan-only` 检查实际时长，再执行合成。`mix` 默认压低原声；需要准确声音比例时直接写音量。

```json
{
  "output": {"width": 1280, "height": 720, "fps": 30, "subtitles_mode": "sidecar"},
  "scenes": [
    {
      "id": "s01",
      "visuals": [{"selection": "s01.image"}],
      "audio": {"selection": "s01.audio"},
      "audio_policy": "edge_tts"
    },
    {
      "id": "s02",
      "visuals": [{"selection": "s02.video", "trim_start": 0, "hold": true}],
      "audio": {"selection": "s02.audio"},
      "audio_policy": "mix",
      "native_volume": 0.25,
      "narration_volume": 1.0
    }
  ]
}
```

这里 `edge_tts` 表示采用独立旁白音轨；音频可以是已导入的现成文件，合成命令不会因此调用 TTS。若视频比旁白短，只有写明 `hold: true` 才延长末帧。修改一镜声音配置后再次合成，会复用原始媒体并重新编码整条视频。

## 字幕烧录与定时配字

subtitles_mode 为 burn 时，subtitle_renderer 可选 auto、libass、pillow。auto 在仅烧录字幕且 FFmpeg 提供 subtitles 滤镜时使用 libass；缺少滤镜或需要 text_overlays 时使用 Pillow。Pillow 是可选 render 依赖，需提供 subtitle_font_file。字体路径可相对项目目录或为本机可读绝对路径，字体应覆盖实际文字；字体文件不随插件分发。

```json
{
  "output": {
    "width": 1280, "height": 720, "fps": 24,
    "subtitles_mode": "burn", "subtitle_renderer": "pillow",
    "subtitle_font_file": "assets/fonts/your-font.ttf", "subtitle_font_size": 13
  },
  "scenes": [{
    "id": "s01", "duration_seconds": 6,
    "visuals": [{"path": "assets/videos/clip.mp4", "kind": "video"}],
    "audio": {"path": "assets/audio/voice.mp3", "start_seconds": 0.2},
    "audio_policy": "edge_tts", "subtitles_path": "assets/audio/voice.srt",
    "text_overlays": [{
      "text": "<填写准确屏幕文字>", "start_seconds": 1, "end_seconds": 5,
      "position": "top-left"
    }]
  }]
}
```

字幕时间从真实 SRT/VTT 读取，并跟随 audio.start_seconds 或明确的 subtitles_offset_seconds；text_overlays 使用镜内时间，独立于旁白字幕。position 支持 top-left、top-right、top-center、bottom-left、bottom-right。subtitle_font_size 沿用 ASS 单位，Pillow 按画幅高度换算，13在720p时约33像素。Pillow只换行，不重估字幕时点；渲染后检查字体、遮挡与音画同步。

烧录与配字的依赖在编码前检查。--plan-only 仍可计算时间安排，不能证明当前机器已具备字体或烧录依赖。

## 背景轨与全片响度

在顶层background_audio指定已导入的资产、采用位置或项目内path，独立于每镜的原声/旁白策略。例：

```json
{
  "output": {"width":1280,"height":720,"fps":24,"audio_loudness_lufs":-17,"audio_true_peak_db":-2},
  "background_audio": {"selection":"film.background","volume":0.15,"start_seconds":0,"loop":true,"fade_in_seconds":1,"fade_out_seconds":2},
  "scenes": [{"id":"s01","duration_seconds":6,"visuals":[{"path":"assets/videos/clip.mp4"}],"audio":{"path":"assets/audio/voice.mp3"},"audio_policy":"edge_tts"}]
}
```

背景轨可用trim_start和duration_seconds选择范围；无loop时默认使用可用片段与全片剩余窗口中较短的一段，超出素材的显式片长需要主动开启loop。淡入淡出必须装入背景片长。每镜silent静音其自身音轨，独立背景轨仍按全片配置叠加。

默认不归一化。显式设置audio_loudness_lufs后使用EBU R128响度处理，目标范围-70至-5 LUFS；audio_true_peak_db范围-9至0 dBTP，默认-2。背景轨在最终AAC编码前混合，字幕烧录沿用已合成的音轨。

该参数触发合成时的响度处理，最终编码后的 LUFS 与真峰值仍需实测。需要更精确校准时使用 [交付命令](delivery.md) 中的 `ntf normalize` 双遍处理。
