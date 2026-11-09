# 最终文件验收与本地审阅

技术检查使用 `ntf inspect FINAL_FILE --decode --audio-check`，按交付要求添加尺寸、帧率、时长和音轨验收参数。完整解码后，以缩小 JPEG 抽帧定位开头、结尾、字幕和衔接，再连续播放关键动作、转场并试听。记录实际查看范围；可解码、非空音轨和响度合格不能替代内容审阅。

内容检查包含：事件顺序和时态、人物和物件连续性、技术关系、动作是否可读、重复画面的用途、字幕遮挡、准确文字的阅读时间、旁白发音及截断。分别记录技术检查和内容检查，说明未检查的部分。

## 双遍响度校准

使用 `ntf normalize`。它复用现有 FFmpeg/ffprobe，复制视频码流，只重编码第一条音轨为 AAC，生成新的 MP4。输入应是已合成的单视频、单音轨成片；其他轨道不会自动保留。

指定原成片、新输出及响度目标：

```bash
ntf normalize FILM.mp4 --output FILM-final.mp4 \
  --lufs -17 --true-peak -2 --lra 11 --report loudness.json
```

命令先测量，再带测量参数执行 `loudnorm`，最后复测编码后的文件。报告区分目标值和实测值，AAC 编码后仍可能存在小偏差；按实际交付容差判断。静音或缺少音轨时明确报错；源文件和已有输出不覆盖。已满足响度要求时无需重复处理。

## 可拖动的审阅入口

最终成片如果经过响度或其他后处理，明确指定该文件，避免自动选到较早的 render：

```bash
ntf preview PROJECT --video FILM-final.mp4 --timeline TIMELINE.json --output REVIEW_DIR
ntf serve --directory REVIEW_DIR --port 0
```

`TIMELINE.json` 使用本次合成返回的时间表；响度处理保留画面时间，若另行改变剪辑则使用对应的新时间表。命令检查总时长、镜头 ID 和窗口；使用时间表的真实顺序生成审阅卡片。

使用 `ntf serve` 返回的本地地址。服务支持 GET/HEAD 和单段 HTTP byte range，只监听 `127.0.0.1`，不列目录，不跟随越过根目录的符号链接。停止时向进程发送 Ctrl-C。`preview` 返回的 `serve_argv` 也可直接执行。

只服务 `preview` 导出的独立目录，原始项目的 state、work、连接配置和任务快照不进入审阅交付。打开页面后检查视频能播放、能拖到中段和结尾；审阅页序号、镜头总数、章节与正式分镜当前顺序一致。

最终返回 MP4、审阅入口和必要字幕，说明文字、声音来源与仍需确认的具体内容。`normalize` 产生的新文件通过 `preview --video --timeline` 明确采用，保留原成片记录。
