# NoteToFilm CLI 命令

先读本 Skill 的 `runtime.md`，使用其中给出的实际命令路径。下面的 `ntf` 代表 NoteToFilm CLI 的这条命令。命令输出 JSON；发生错误时读取 `code`、`message` 和具体信息，不把错误输出当成媒体结果。

公司调用失败时读取 `details.diagnostic`：`category` 是错误类别，`submission_outcome` 表示提交结果是否确定，`request_id` 用于关联网关记录，`next_action` 给出处理方向。`reported_layer` 仅记录响应声明的层级；404 不能直接推定模型不支持。生成结果为 unknown 时先核查任务或用量，已有任务 ID 时继续原任务。

| 操作 | 命令 |
|---|---|
| 建项目 | `ntf init PROJECT --title TITLE` |
| 查看运行环境与字幕渲染能力 | `ntf install-info` |
| 查看实际通道 | `ntf routes --config FILE` |
| 导入媒体 | `ntf import PROJECT FILE --select SLOT` |
| 项目声音、画幅、字幕和路由默认值 | `ntf settings PROJECT [--voice VOICE --rate=-8% --width 1280 --height 720 --fps 24]` |
| 保存正式分镜 | `ntf storyboard PROJECT --file FILE` |
| 从分镜生成媒体计划 | `ntf plan PROJECT` |
| 使用指定计划 | `ntf plan PROJECT --file FILE` |
| 估算旁白或应用实测片长 | `ntf timing PROJECT --mode estimate` / `ntf timing PROJECT --apply --min-seconds 4 --max-seconds 15 --preserve-planned` |
| 看当前可执行项 | `ntf ready PROJECT` |
| 看进展与输入变化 | `ntf status PROJECT` |
| 执行或继续具体动作 | `ntf run PROJECT --action ID --config FILE --wait-seconds 20` |
| 明确重做已完成动作 | `ntf run PROJECT --action ID --config FILE --force` |
| 采用指定素材 | `ntf select PROJECT SLOT ASSET_ID` |
| 单独生成媒体 | `ntf generate PROJECT --request FILE --config FILE` |
| 单独配音 | `ntf audio PROJECT --text TEXT --voice zh-CN-XiaoxiaoNeural` |
| 按明确清单合成 | `ntf compose PROJECT --manifest FILE` |
| 只计算合成方案 | `ntf compose PROJECT --manifest FILE --plan-only` |
| 制作参数化动效素材 | `ntf motion PROJECT --manifest FILE [--scene ID]` |
| 动效预检与压缩预览 | `ntf motion PROJECT --manifest FILE --plan-only` / `--preview-only --preview-time SECONDS` |
| 探测媒体、完整解码与JPEG抽帧 | `ntf inspect FILE --decode --frames 3 --output DIR --max-width 960` |
| 标出冻结、黑场和静音区间 | `ntf inspect FILE --scan [--timeline TIMELINE]` |
| 按时间看视频的联系表 | `ntf sheet FILE --output DIR [--timeline TIMELINE] [--fps 2]` |
| 看每个剪点前后 | `ntf sheet FILE --output DIR --timeline TIMELINE --cuts --fps 8` |
| 复看指定时段 | `ntf sheet FILE --output DIR --start 12 --end 16 --fps 8` |
| 网页动画静帧预览与确定性检查 | `ntf web-render PROJECT --page animation/s02 --scene s02 --preview-time 1 --preview-time 3.5` |
| 网页动画渲染为项目素材 | `ntf web-render PROJECT --page animation/s02 --scene s02 [--duration SECONDS]` |
| 导出指定最终成片的审阅页 | `ntf preview PROJECT --video FINAL_FILE --output DIR` |
| 后处理成片携带对应时间表导出 | `ntf preview PROJECT --video FINAL_FILE --timeline TIMELINE --output DIR` |
| 双遍响度校准并保留原片 | `ntf normalize MP4 --output FINAL_MP4 --lufs -17 --true-peak -2 --report REPORT` |
| 启动可拖动的本地审阅服务 | `ntf serve --directory DIR --port 0` |
| 创建待配置样例 | `ntf config-init FILE` |

PROJECT 与文件参数都传具体路径。动作 ID 从计划或 `ready` 结果读取，不依赖“第二项”之类临时位置。无需用户手填 JSON：Agent 根据正式材料写入工作文件再调用。

`run` 的等待时间仅控制当前一次等待，未取得文件时继续查询已有动作，不新建相同任务。提交超时且结果不明时，保留动作与请求信息；只有明确决定重发时才使用 `--retry`，不要把它当成循环轮询参数。

`generate` 的请求是扁平 JSON，包含 `kind`（`image` 或 `video`）、`route`、`mode`、`prompt` 及实际需要的参考和参数；不嵌套 `request`。可指定 `action_id`、`selection_slot` 和 `select_index`。同一 action_id 已存在时继续 `run`，不要再次 `generate`。

需要当前客户端提供的文件读取、生图或视频工具时由 Agent 直接调用。取得实际媒体文件后用 `ntf import` 登记和采用；不要宣称 Python 可以执行任意 `SKILL.md` 或自动访问客户端专有工具。

## 分阶段与外部连接文件

`run --kind audio|image|video|compose`选择阶段；`--scene ID`可重复，使用固定ID。`--submit-only`只启动待执行动作，跳过已有远端任务；`--poll-only`只查询或下载已有任务，不能与retry/force并用。`--max-new-actions N`限制本次创建的动作数；`--stop-on-error`在失败或结果不明后停止本批。恢复始终使用已记录的原任务。

`routes`、`generate`、`run`接受`--config ROUTES`。ROUTES保存模型、协议、能力和认证环境变量名，不含地址和密钥。地址和密钥依次来自环境变量、NoteToFilm 根目录 `.env`，以及连接声明 `codex_provider` 时即时读取的 Codex 配置；`routes` 显示每条路由的来源。需要临时使用另一份私有连接时加 `--connections-file PRIVATE`，它只提供匹配connection ID的base_url及credentials.api_key，仅在当前操作内绑定，不复制私有文件、不导出密钥，也不覆盖模型与协议路径。

`settings`不带修改参数时读取项目默认值。声音可控voice/rate/volume/pitch，画幅可控width/height/fps，文字可控subtitles（sidecar、burn、embed、none）/subtitle-renderer/font-file/font-size，音轨可控audio-tracks（single或dual），路由可控image-route/video-route。修改后重新plan；字体和配字时点仍在合成清单中明确。

`timing --mode estimate`只报告估时，不伪造字幕；默认按约每秒 4.6 个发音单位（中文字、数字各算一个，英文词算两个）并随项目或镜头的 `rate` 换算，`--units-per-second` 可指定固定语速；`timing --apply`要求已有真实音频，以lead/tail、最小/最大片长和preserve-planned选项计算窗口，并更新未采用现有画面的video_parameters.duration_seconds。超限时拒绝整次写入，返回待拆镜项；之后重新plan。

`preview` 只导出审阅页、JPEG 和可播放成片，不复制项目配置或任务快照；默认选择最近成功成片。后处理后用 `--video` 指定最终文件及 `--timeline` 指定相应时间表，或用 `--render` 选择已登记成片。时间表须与最终视频时长和正式分镜 ID 对应，审阅顺序按时间表排列。返回的 `serve_argv` 调用支持 byte range 的 `ntf serve`，只服务独立导出目录。

`normalize` 可设置 `--lufs`、`--true-peak`、`--lra`，可选 `--report` 保存实际响度。先测量、带测量参数处理，再复测 AAC 输出；保留原片和视频码流，不覆盖已有目标。输出只含第一条视频和第一条音轨；双音轨或内封字幕的成片不要用它，改在合成清单中设置 `output.audio_loudness_lufs`。它处理已完成的音轨，配音及混音仍在 audio/compose 阶段完成。

`motion` 使用图层与关键帧清单，输出无声视频并登记到 `motion.<scene_id>`。`--select-prefix` 改采用前缀；`--stage picture` 生成 `<prefix>.<id>.picture` 净画面，`--stage annotate` 复用该采用位置并添加 draw 图层。相同输入可复用，`--force` 另生成新素材。`--plan-only` 不生成媒体，`--preview-only` 只输出缩小 JPEG；详细字段在 compose Skill 的 motion 说明。

同一项目写状态的命令串行执行。需要并发生成时批次提交，让远端任务并行，再串行轮询；不要用多个进程同时改项目状态。独立 `generate` 候选的采用可通过显式合成清单完成，保存动作 ID，避免以重新提交代替继续查询。

## 参数一致性、声音后期与成片判定

生成计划按动作记录相关项目设置。`settings`改变被引用的默认值后，`status`返回plan_current=false及stale_action_ids；`run`在开始受影响的新动作前返回stale_plan，重新plan后继续。字体或画幅只影响合成，默认音色只影响使用默认值的配音。`--poll-only`使用旧任务的原请求和通道快照，即使已经重新规划也可以取回旧结果。明确提交的自定义计划保持其自有参数。

`settings`支持`--background-audio ASSET_ID`、`--background-volume`、`--background-start-seconds`、`--background-trim-start`、`--background-duration`、`--background-loop`、`--background-fade-in/out`。`--no-background-audio`移除背景轨；`--loudness-lufs`和`--true-peak-db`设置全片响度处理，`--no-loudness-normalization`关闭归一化。修改后重新plan。

`inspect --expect-width W --expect-height H --expect-fps FPS --expect-duration SECONDS --duration-tolerance .1 --expect-audio yes`核对实际规格；`--audio-check`测量音量和响度。`--min-mean-dbfs`、`--max-peak-dbfs`控制静音和样本峰值判定，`--expect-loudness-lufs`及`--loudness-tolerance`控制整体响度判定。返回verification.checks；任何指定检查失败时退出码为2。无验收参数时只探测，不声明质量通过。

`sheet` 把视频按时间抽帧排成 JPEG 网格，每格标注该帧的实际源时间；给出 `--timeline` 时同时标注镜头 ID，`sheet.json` 列出每帧对应的字幕。`--cuts` 只取每个剪点或转场前后 `--cut-padding` 秒，`--start/--end` 复看指定时段；单次最多约 600 帧，超出时降低 `--fps` 或缩小时段。输出目录须为空，以保留之前的查看记录。需要 render 依赖中的 Pillow。

`web-render` 打开项目内提供 `window.render(t)` 的页面，按项目画幅和帧率逐帧截图并编码为无声视频，登记后采用到 `web.<scene>`（`--select` 可改）；时长默认读页面的 `window.DUR`。页面脚本里写了 `READY = …` 时，等到 `window.READY === true` 才开始截图；没有写时，`render` 出现即开始。`--preview-time` 可重复，只输出静帧，并按另一种渲染顺序比对画面是否只由时间决定；加 `--text-check` 时报告文字出界、重叠和过小并输出标注图。渲染可加 `--dpr`（超采样，1–3）、`--subframes`（子帧运动模糊，1–8，`--shutter` 调快门比例）和 `--grain`（编码时叠加颗粒，0–40）。页面目录内容与参数不变时复用已有素材，`--force` 另生成新版本。需要 Playwright（web 可选依赖）和 Chromium 或本机 Chrome；页面写法在 compose Skill 的代码动画说明。

`inspect --scan` 报告冻结（默认持续 1 秒以上，`--freeze-seconds`）、黑场和静音（默认 0.5 秒以上，`--silence-seconds`）区间，带 `--timeline` 时标注所在镜头。结果是查看提示，不影响 verification；静态画面和有意停留同样会出现在冻结中。

`install-info --require-audio --require-render --font-file FONT`可检查实际入口的依赖与字体可读性，失败同样返回非零退出码。字体内容、画面语义和叙事效果仍需审阅。
