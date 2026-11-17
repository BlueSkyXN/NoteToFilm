# 最终文件验收与本地审阅

技术检查使用 `ntf inspect FINAL_FILE --decode --audio-check`，按交付要求添加尺寸、帧率、时长和音轨验收参数。可解码、非空音轨和响度合格不能替代内容审阅。

## 按时间看成片

联系表把视频按时间抽帧排成网格，每格标注源时间和镜头 ID；`sheet.json` 列出每帧对应的字幕。用当前客户端读取图片，按下面的顺序看：

1. 全片：`ntf sheet FINAL_FILE --output DIR --timeline TIMELINE --fps 1`，短片可用 2。先只看画面，判断每段的变化能否看出来；再对照字幕与旁白。
2. 剪点：`ntf sheet FINAL_FILE --output DIR --timeline TIMELINE --cuts --fps 8` 查看每个剪点或转场前后。对照转场对：A 镜结束时的状态在 B 镜是否成立，对象的位置、方向和数量是否连续。
3. 关键变化：段落卡写明的关键时点，用 `--start`、`--end` 配合较高帧率复看。
4. 定位提示：`ntf inspect FINAL_FILE --scan --timeline TIMELINE` 标出冻结、黑场和静音区间。静态证据和有意停留也会显示为冻结，结合段落卡判断是有意停留还是空等；意外的黑场、静音和断音回到对应镜头处理。

每次查看写入新的空目录，旧记录保留，便于对照修改前后。联系表能发现状态回退、对象跳变、字幕遮挡和画面与旁白不符；帧间运动是否平滑、有无微抖，以及声音听感，需要人连续播放确认。没有人看过时，在汇报中写明这几项未检查。

内容检查包含：事件顺序和时态、人物和物件连续性、技术关系、动作是否可读、重复画面的用途、字幕遮挡、准确文字的阅读时间、旁白发音及截断。抽几句旁白对照联系表，看画面与旁白所说是否矛盾。分别记录技术检查和内容检查，写明看过的范围和未检查的部分。

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
