# 当前项目文件

使用 JSON，`schema_version` 为 `1`。JSON 中不要填写凭据。读取用户实际文件，不从旧对话补写项目事实。

| 文件 | 正式内容与写入方式 |
|---|---|
| `project.json` | 项目 ID、`brief`、默认声音与输出设置。初始化用 `ntf init`；材料 Agent 更新已知说明，保留其他字段。 |
| `sources/index.json` | 材料 Agent 维护来源 ID、文件相对路径或链接、原文位置。 |
| `materials.md` | 材料 Agent 写可讲内容、来源、原图与缺项。 |
| `storyboard.json` | 导演 Agent 写正式镜头与旁白；通过 `ntf storyboard PROJECT --file FILE` 保存并生成阅读版。 |
| `workflow.json` | 当前具体动作与直接依赖。用 `ntf plan` 生成，或用 `--file` 提交明确计划。 |
| `state.json` | 命令登记动作、尝试、素材、采用关系与成片。不要由多个 Agent 各自读改写整份文件。 |
| `renders/` | 每次实际输出及其时间表、媒体选择。保留旧结果。 |

主分镜使用 `scenes[].id` 作为固定镜头 ID，数组位置表示顺序。正式旁白只维护 `narration`；阅读版不是第二份正文。分镜驱动的工作流改稿后再次 `ntf plan`；独立候选加显式合成清单的路线同步更新主分镜、配音和清单，并保留已有动作 ID 与采用关系。

基本镜头字段：`id`、`narration`、`screen_text`、`visual_prompt`、`visual_type`（`still` 或 `video`）。视频镜头按需增加 `video_prompt`、`video_mode`、`route`、`references`、`start_frame`、`end_frame`、`duration_seconds`。声音策略为 `edge_tts`、`native`、`mix` 或 `silent`。时间单位为秒。

`source_id` 表示原始资料；`asset_id` 表示可制作媒体。原图采用时先 `ntf import`，使用返回的素材 ID；不要把来源 ID 填成图像素材 ID。文件先导入项目再引用，不把外部绝对路径和临时下载地址写进正式分镜。

制作输入可引用 `{ "asset_id": "实际ID" }`、`{ "selection": "s01.image" }`、`{ "path": "assets/项目内文件.png" }`，或 `{ "storyboard_ref": { "scene_id": "s01", "field": "narration", "default": "" } }`。命令在执行前解析。多参考图使用有序对象列表，并保留 `position`、`role` 与 `instruction`；首尾帧独立记录。

素材 ID 与镜头 ID 不相互代替。一份素材可以被多镜复用，新候选不覆盖旧文件，采用关系通过 `ntf select` 更新。导入文件与原材料复制应留在项目目录内。

阅读版镜头展示01、02等连续顺序，正式id仍用于动作和素材引用。章节与方向说明可保留在分镜的扩展字段。需要运行代码实际加入定时文字时使用text_overlays：text、start_seconds、end_seconds、position；screen_text本身是导演要求，不自动推断文字出现时点。

素材引用中的media_duration_seconds是实测来源长度；visuals[].duration_seconds是明确要求使用的剪辑长度。二者独立，模型多返回一帧不应自动扩大镜头窗口。独立旁白的narration_start_seconds控制镜内开始时间；使用现成audio对象时在audio.start_seconds设置。

视频视觉项可选 source_duration_seconds 与 speed，分别约束源区间和播放速度；speed=fit 将完整源区间适配到输出窗口。镜头 transition 是进入该镜头的重叠转场，会影响后续全片时点；以实际合成时间表为准。动效清单作为制作输入保存在工作文件中，ntf motion 的结果仍登记为普通视频素材，可由 visuals 引用，无需改变项目 schema。
