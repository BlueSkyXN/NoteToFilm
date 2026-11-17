# 离线媒体示例

示例使用程序生成的 PNG、FFmpeg 测试视频和正弦测试音，约 4.6 秒。它用于检查媒体处理链路，不访问模型、Edge TTS 或公司接口。

在仓库根目录执行，选择一个新目录：

```bash
python3 examples/create_media_fixture.py --output /path/to/new-demo --render
python3 scripts/ntf.py inspect /path/to/new-demo/output/video.mp4 --decode
```

需要 Python 3.11+、FFmpeg 和 ffprobe。默认输出旁挂字幕。需要烧录时传入 `--subtitles-mode burn`；当前 FFmpeg 没有字幕滤镜时，安装 `render` 可选依赖，并用 `--font-file /path/to/font.ttf` 指定包含字幕字符的实际字体。

输出内容：

| 路径 | 内容 |
|---|---|
| `assets/` | 测试图案、视频、测试音和字幕输入 |
| `compose.json` | 可重新使用的混合媒体合成清单 |
| `FIXTURE.json` | 输入来源与测试含义 |
| `output/video.mp4` | 640×360、15fps 的 H.264／AAC 成片 |
| `output/subtitles.srt` | 按明确测试时间编写的字幕 |
| `output/timeline.json` | 采用区间、场景窗口、声音策略和媒体规格 |
| `output/segments/` | 编码中间文件 |

四幕依次覆盖独立音轨、视频原声与末帧延长、原声混音和静音。清单中的 `audio_policy: edge_tts` 选择独立旁白的混音路径；该示例输入为本地测试音。

只准备输入和预检结果时省略 `--render`。需要用安装后的 CLI 验证时，先 `ntf init PROJECT`，将生成器的 `--output` 指向该项目，再执行：

```bash
ntf compose PROJECT --manifest PROJECT/compose.json
ntf status PROJECT
```

每次合成保留独立版本。合成清单的完整字段与声音规则见 compose Skill 的 `references/manifest.md`。
