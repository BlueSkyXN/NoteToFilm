# 常见错误与处理

`ntf` 出错时向 stderr 输出 `{"error": {"code", "message", "details"}}`，退出码为 2。`ntf run` 执行的动作若失败、结果不明或中断，退出码同样为 2，详情在输出的 `executed` 中。先按 `code` 在下表查找；表中没有的错误码，读 `message` 和 `details`。

模型通道返回的错误另带 `details.diagnostic`，其中 `category`、`summary` 和 `next_action` 说明错误类别与建议，见文末[通道错误类别](#通道错误类别)。

## 安装与依赖

| code | 原因 | 处理 |
|---|---|---|
| `audio_dependency_missing` | 没装 Edge TTS | 安装 `audio` extra，或安装器加 `--with-audio` |
| `render_dependency_missing`、`text_dependency_missing` | 动效、联系表、子帧模糊或 Pillow 字幕需要 Pillow | 安装 `render` extra，或安装器加 `--with-render` |
| `web_dependency_missing` | 没装 Playwright | 安装 `web` extra |
| `web_browser_missing` | 找不到无头浏览器 | 安装 Google Chrome，或执行 `python -m playwright install chromium` |
| `media_tool_missing` | 找不到 `ffmpeg` 或 `ffprobe` | 安装 FFmpeg 并确认在 `PATH` 中；`ntf install-info` 显示实际找到的路径 |
| `subtitle_filter_missing` | 当前 FFmpeg 没有 subtitles 滤镜 | 改用 Pillow 绘制字幕（`subtitle_renderer: pillow`，安装 `render` extra 并提供 `subtitle_font_file`），或换带 subtitles 滤镜的 FFmpeg |
| `text_filter_missing` | Pillow 字幕需要 FFmpeg 的 overlay 滤镜，当前版本没有 | 换带 overlay 滤镜的 FFmpeg |
| `text_font_required`、`font_missing`、`font_invalid` | 绘制文字需要可读取的字体文件 | 指定包含所用字符的字体文件；`ntf install-info --font-file FONT` 可检查 |

## 配置与连接

| code | 原因 | 处理 |
|---|---|---|
| `config_exists` | `config-init` 的目标文件已存在 | 直接编辑该文件，或换一个文件名 |
| `config_format` | `config-init` 只写 JSON；读取 YAML 需要 PyYAML | 用 `.json` 文件名；读 YAML 时安装 `yaml` extra |
| `config_invalid`、`config_version` | 配置文件无法读取或结构不对 | 对照 `configs/` 中的样例检查 `routes`、`connections` |
| `config_credentials` | 配置里直接写了密钥或认证头 | 配置只写环境变量名（`auth.env`、`header_envs`），密钥放 `.env` |
| `route_missing` | 指定的路由不在配置中 | `ntf routes --config FILE` 查看可用路由 |
| `model_missing` | 路由没有写模型 ID | 填写网关接受的精确模型或部署 ID |
| `adapter_unconfigured` | 路由没有选择适配器 | 按网关实际接口填写 `adapter`，不会根据模型名推断 |
| `auth_unconfirmed` | 认证方式仍是 `unconfirmed` | 填写 `bearer`、`header` 或 `none` |
| `capability_unknown` | 能力、参考图上限或 `supports_mask` 未确认 | 按网关约定填写能力；未实测的组合不要标为可用 |
| `connection_missing` | 路由没有可用地址 | 在 `.env` 或环境变量中设置对应的 `*_BASE_URL`，或为连接声明 `codex_provider`；`ntf routes` 显示每条路由的来源 |
| `credential_missing` | 认证引用的环境变量没有值 | 在 `.env` 或环境变量中设置；`ntf routes` 的 `credential` 为 `missing` 时就是这个问题 |
| `codex_config_missing`、`codex_config_invalid`、`codex_provider_missing` | 读不到 Codex 配置，或其中没有指定的 provider、`base_url` | 检查 `~/.codex/config.toml`（或 `$CODEX_HOME`），也可以改用环境变量提供地址与令牌 |
| `connection_invalid`、`url_invalid`、`endpoint_origin` | 地址带了凭据、查询参数，或提交与查询路径指向其他域名 | 地址只写协议、域名和前缀；绝对路径必须与配置地址同源 |
| `connections_format`、`connections_binding` | `--connections-file` 文件格式不对、连接 ID 对不上，或路由没有声明专用的 `auth.env` | 文件需为 `{"connections": {"ID": {"base_url", "credentials": {"api_key"}}}}`，ID 与路由配置一致，路由声明 `auth.env` |

## 生成请求

| code | 原因 | 处理 |
|---|---|---|
| `request_invalid`、`request_format`、`request_kind` | 请求结构不对，或用 `generate` 请求配音 | `generate` 用扁平 JSON：`kind`（`image` 或 `video`）、`route`、`mode`、`prompt`，再加实际需要的参考和参数；配音用 `ntf audio` |
| `route_modality`、`unsupported_mode` | 图片请求用了视频路由，或模式不属于该类型 | 图片模式：`text_to_image`、`reference_to_image`；视频模式：`text_to_video`、`image_to_video`、`reference_to_video`、`first_last_to_video` |
| `mode_inputs` | 参考图、首尾帧与模式不匹配，或 `mask` 用在了 `reference_to_image` 以外 | 图生视频给 `start_frame`，首尾帧给 `start_frame` 与 `end_frame`，参考图模式给 `references` |
| `unsupported_parameter` | 适配器不能发送这个参数，或一次请求要了多个视频 | 删掉该参数；视频每个动作只出一个结果，多个候选拆成多个动作 |
| `parameter_missing`、`parameter_combination`、`parameter_conflict` | 缺少必填参数、组合不被支持，或 `parameters` 与 `output` 给了不同的值 | 按路由能力声明调整；同一参数只写一处 |
| `reference_limit`、`reference_order`、`reference_role`、`reference_invalid` | 参考图超过上限、`position` 与数组顺序不一致，或 `role`、`instruction` 不是字符串 | 减少参考图；`position` 从 1 开始，与数组顺序相同；`role`、`instruction` 写成文字 |
| `mask_invalid` | 蒙版不是 PNG，或与第一张参考图尺寸不同 | 用同尺寸 PNG，透明区域为要修改的部分 |
| `path_outside_project`、`reference_missing` | 引用了项目外的文件或读不到 | 先 `ntf import` 导入项目，再用返回的素材 ID 或项目内路径 |

## 执行、续做与重做

| code | 原因 | 处理 |
|---|---|---|
| `submission_unknown` | 提交后没拿到任务 ID，无法确认网关是否受理 | 不要直接重发。先在网关记录或用量中核对；确认没有受理后再用 `ntf run --retry` |
| `action_busy` | 另一个本地进程正在处理这个动作 | 等它结束，用 `ntf status` 查看 |
| `already_complete` | 动作已经完成 | 需要新版本时加 `--force`，会产生新费用 |
| `action_exists` | `generate` 的 `action_id` 已存在 | 用 `ntf run --action ID` 继续；有意重做时加 `--force` |
| `no_resumable_task` | `--poll-only` 时没有可续查的任务 | 去掉 `--poll-only` 正常执行 |
| `stale_plan` | 项目设置改了，计划已过期 | 重新 `ntf plan`；已提交的远端任务用 `--poll-only` 取回 |
| `manual_action` | 这个动作需要 Agent 先准备输入 | 按动作说明写好输入文件，再继续 |
| `result_not_ready` | 任务还没有可下载的结果 | 稍后 `ntf run` 继续查询 |
| `job_mismatch`、`job_route_mismatch` | 查询返回的任务与记录不符，或路由已被改动 | 保留原记录，核对网关；续查使用原路由快照 |
| `upstream_status`、`upstream_format` | 网关返回了无法识别的状态或结构 | 保留任务 ID，稍后再查；持续出现时核对网关版本 |
| 退出码 2 且状态为 `unknown` | 生成请求在结果不明时中断 | 同 `submission_unknown`：先核对，再决定是否 `--retry` |

## 项目与素材

| code | 原因 | 处理 |
|---|---|---|
| `not_a_project` | 目录里没有 `project.json` | 先 `ntf init`，或检查路径 |
| `storyboard_format`、`duplicate_scene`、`invalid_id` | 分镜结构不对、镜头 ID 重复或含非法字符 | 镜头 ID 只用字母、数字、点、下划线和连字符 |
| `missing_narration`、`missing_visual_prompt`、`missing_video_prompt` | `ntf plan` 发现镜头缺必要字段 | 补齐旁白或画面描述，或改用已有素材、静音／原声策略 |
| `missing_input`、`unknown_asset` | 引用的素材或分镜字段不存在 | 用 `ntf status` 查看实际素材 ID 与镜头 ID |
| `asset_modified` | 已登记的素材在磁盘上被改动 | 用 `ntf import` 登记新版本，不要直接覆盖文件 |
| `empty_selection` | 采用时没有指定素材 | 用 `ntf select` 指定实际存在的素材 |
| `selection_index` | `generate` 的 `select_index` 超出本次返回的候选数 | 改成有效序号，或之后用 `ntf select` 采用 |
| `output_exists`、`output_input_collision` | 输出目录已存在，或会覆盖源文件 | 换一个新的输出目录 |

## 合成

| code | 原因 | 处理 |
|---|---|---|
| `compose_invalid`、`compose_unsupported` | 合成清单的字段或取值不对 | 按 `message` 中的字段名修正；清单写法见 compose Skill 的 `manifest.md` |
| `narration_would_be_truncated` | 镜头时长短于实际旁白 | 加长镜头，或用 `ntf timing` 按实测旁白回填时长 |
| `transition_too_long`、`transition_narration_overlap`、`transition_subtitle_overlap`、`transition_text_overlap` | 转场太长，或与旁白、字幕、配字重叠 | 缩短转场，或调整旁白开始时间与字幕时段 |
| `text_does_not_fit` | 字幕或配字比画面还高 | 调小字号或缩短文字 |
| `media_duration_unknown` | 读不到视频或旁白时长 | 用 `ntf inspect --decode` 检查该文件是否完整 |
| `render_duration_mismatch` | 输出时长与时间表不符 | 检查素材是否完整、变速参数是否合理，再重新合成 |
| `timing_requires_split` | 有镜头超过 `--max-seconds` | 先拆分镜头，再回填时长 |

## 网页动画

| code | 原因 | 处理 |
|---|---|---|
| `web_page_invalid` | 页面不在项目内，或找不到 `index.html` | 把页面目录放进项目，`--page` 用项目内相对路径 |
| `web_page_not_ready` | 页面没有提供 `window.render(t)`，或 `window.READY` 一直不为 true | 按 compose Skill 的代码动画骨架补齐约定 |
| `web_page_error` | 页面脚本报错或资源加载失败 | 修正脚本；字体和图片放在页面目录内 |
| `web_render_parameters` | 参数越界 | `--dpr` 1–3，`--subframes` 1–8，`--shutter` (0, 1]，`--grain` 0–40 |
| `web_render_mismatch` | 导出视频与计划时长不符 | 检查 `window.DUR` 或 `--duration` |
| 预览返回 `deterministic: false` | 画面不只由时间决定 | 按 `nondeterministic` 列出的时刻，查跨帧状态、随机数、实时时钟或晚到的资源 |

## 不算错误、但值得注意

- `inspect --scan` 报告的冻结、黑场和静音只是提示。静态画面和有意停留同样会出现，结合设计判断。
- `web-render --grain` 会让文件大幅变大：实测一段 7 秒 720p 画面从 42 KB 变成约 57 MB，合成重新编码后仍约 28 MB。用法见 compose Skill 的 `motion-craft.md` 第 9 节。

## 通道错误类别

`details.diagnostic.category` 的取值：

| 类别 | 含义 | 建议 |
|---|---|---|
| `authentication` | 认证被拒绝 | 检查凭据是否有效、认证头格式是否符合网关约定 |
| `permission` | 凭据没有该模型或操作的权限 | 核对模型、分组和通道权限；例如没有权限的模型 ID 会返回 403 |
| `quota` | 额度不足 | 核对凭据额度与计费限制 |
| `rate_limit` | 频率或并发受限 | 参考 Retry-After 等待或降低并发，再决定是否新建请求 |
| `invalid_request` | 请求参数被拒绝 | 按错误中的参数名修正 |
| `content_rejected` | 内容或素材被拒绝 | 查看服务给出的拒绝原因 |
| `model_unavailable` | 模型不可用 | 核对精确模型 ID 和网关的模型映射 |
| `resource_not_found` | 404 | 用请求 ID 核对网关命中的渠道和路径；仅凭 404 不能确定根因 |
| `unsupported_operation` | 操作或格式不受支持 | 核对路径、方法和请求编码 |
| `upstream_failure` | 服务端故障 | 先核查已有任务或用量，确认状态后再决定是否重新提交 |
| `request_timeout`、`connection_error` | 等待超时或连接中断 | 生成请求先核查，查询和下载可继续已有任务 |
| `dns_error`、`tls_error` | 域名解析或证书失败 | 检查域名、DNS、代理和证书信任配置 |
| `redirect` | 接口要求跳转，未自动跟随 | 核对配置的地址与路径 |
| `invalid_response`、`invalid_media` | 响应或媒体格式不符合约定 | 保留任务 ID，核对网关记录；已取得结果时优先恢复下载 |
| `task_failed` | 远端任务明确失败 | 查看失败原因再决定后续处理 |
| `business_error`、`http_error` | 其他业务错误或未归类的 HTTP 错误 | 结合错误码、正文和请求 ID 核对网关记录 |
| `local_io`、`local_error` | 结果已返回，本地处理失败 | 检查输出目录权限与磁盘空间，复用已取得的结果 |
