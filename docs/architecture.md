# 工作原理

NoteToFilm 由三部分协作：Agent 做判断，Skill 提供方法，NoteToFilm CLI（`ntf`）执行并记录。本文说明三者的分工、一条片子从材料到成片经过哪些步骤、项目里每个文件管什么，以及几项关键设计的理由。命令参数见[命令说明](../shared/commands.md)，项目字段见[项目文件](../shared/project-format.md)。

## 三层分工

| 层 | 位置 | 负责 | 不负责 |
|---|---|---|---|
| Agent | 用户使用的客户端（Codex、Claude Code 等） | 读材料、定叙事和画面、写分镜、挑素材、看联系表判断好坏 | 直接改写 `state.json` |
| Skill | `.agents/skills/` 七个目录 | 告诉 Agent 每个阶段怎么判断、常见做法和取舍、什么时候用哪条命令 | 执行任何操作 |
| `ntf` | `runtime/notetofilm_local/` | 维护项目状态、调用模型通道、处理媒体、合成和导出审阅材料 | 判断内容是否合格 |

`ntf` 给出能力和查看提示，例如 `inspect --scan` 标出冻结和静音、`web-render --text-check` 标出文字出界，是否合格由 Agent 依据设计判断。Skill 不设 hook 或强制门禁。

七个 Skill 的职责见[技能布局](skill-layout.md)。

## 一条片子怎么做出来

```text
材料 ──prepare──▶ sources/、materials.md
                     │
               direct│ 写正式分镜
                     ▼
        ntf storyboard ──▶ storyboard.json（+ views/ 阅读版）
                     │
                     ▼
            ntf plan ──▶ workflow.json：每镜的 <镜头>.audio / .image / .video 动作 + film.compose
                     │
          ntf ready / status   查看哪些动作可执行、缺什么输入
                     │
                     ▼
             ntf run ──▶ 提交 → 查询 → 下载 → 登记素材 → 写入采用位
                     │        （image、video 走模型通道，audio 走 Edge TTS）
          ntf select   需要时改选候选
                     │
                     ▼
  film.compose / ntf compose ──▶ renders/：MP4、时间表、字幕
                     │
  ntf sheet / compare / inspect --scan / preview / serve   审片
                     │
          ntf normalize   交付前校准响度（仅单音轨成片）
```

`ntf normalize` 只保留第一条视频和第一条音轨，其他音轨和内封字幕不会进入输出。双音轨或内封字幕的成片，在合成清单中设置 `output.audio_loudness_lufs`，由合成阶段处理响度。

不走整套流程也可以：`ntf generate`（单次生图或生视频）、`ntf audio`（单段配音）、`ntf motion`（参数化动效）、`ntf web-render`（网页动画）、`ntf score`（代码合成的配乐与音效）各自登记素材，再用显式合成清单交给 `ntf compose`。改稿时更新分镜后重新 `ntf plan`，输入没变的动作复用已有结果。

## 项目里有什么

`ntf init` 创建以下结构。项目放在用户指定的目录，与源码分开。

| 路径 | 内容 | 谁写 |
|---|---|---|
| `project.json` | 项目 ID、制作说明 `brief`、默认声音、输出画幅与帧率、默认路由 | `ntf init`、`ntf settings`；Agent 可补充说明 |
| `sources/`、`materials.md` | 原始资料、来源索引、可讲事实 | Agent（prepare） |
| `storyboard.json`、`views/` | 唯一正式分镜；阅读版 | Agent 写文件，`ntf storyboard` 校验保存 |
| `workflow.json` | 当前动作及依赖 | `ntf plan`，或提交明确计划 |
| `state.json` | 动作状态、尝试、素材、采用关系、成片记录 | 只由命令写 |
| `assets/images`、`assets/videos`、`assets/audio`、`assets/layouts` | 实际取得的媒体 | 命令登记 |
| `work/` | 中间文件，如网页渲染的静帧和比对图 | 命令 |
| `renders/` | 每次合成的 MP4、时间表、字幕和清单 | `ntf compose` |

几个概念之间的关系：

- **动作（action）**：一项具体工作，如 `s03.image`。`needs` 列出它依赖的动作。
- **尝试（attempt）**：动作的一次执行，记录请求、路由快照、远端任务 ID 和结果。重做会新增尝试，旧尝试保留。
- **素材（asset）**：登记过的媒体文件，有固定 ID。新候选不覆盖旧文件。
- **采用位（selection slot）**：如 `s03.image`、`web.s02`，指向当前采用的一个或多个素材。合成清单引用采用位，换素材只改采用关系。
- **成片（render）**：一次合成输出，保留历史版本。

动作状态依次为 `pending`、`submitted`、`waiting_download`、`complete`，异常时为 `failed`、`unknown`（付费请求结果不明）或 `interrupted`（本地中断）。

## 模型通道

```text
路由配置（configs/*.json）
  route：模型 ID、适配器、能力声明
  connection：地址与认证的来源
        │
        ▼
适配器（adapters/）：openai-images、newapi-video、ark-video、gemini-veo
        │ submit → poll → fetch
        ▼
公司网关
```

- 能力按路由、按模式声明，未确认的模式和参数在发出请求前就会被拒绝。
- 地址与凭据依次取环境变量、仓库根 `.env`、即时读取的 Codex 配置。
- 每次尝试冻结路由快照（含地址，不含令牌），续查时使用原地址。

协议细节见[通道配置说明](company-protocols.md)。

## 媒体处理

| 模块 | 命令 | 做法 |
|---|---|---|
| `compose.py`、`timing.py` | `compose`、`timing` | FFmpeg 拼接图片与视频、裁切变速、转场、混音；H.264（CRF 20）＋ AAC |
| `text_overlay.py` | `compose` 的字幕与配字 | FFmpeg subtitles 滤镜或 Pillow 逐帧绘制；也可内封为字幕轨 |
| `motion.py`、`motion_render.py` | `motion` | Pillow 绘制参数化图层与关键帧 |
| `web_render.py` | `web-render` | Playwright 驱动 Chrome 或 Chromium，调用页面的 `render(t)` 逐帧截图 |
| `synth.py` | `score` | 只用标准库合成乐器、音效与环境声；总线滤波、混音、母带与限幅交给 FFmpeg |
| `sheet.py`、`compare.py`、`inspection.py` | `sheet`、`compare`、`inspect` | 按时间抽帧拼联系表；多画面并排、叠合与局部放大；探测、全量解码、冻结与低运动（可标有意停留）、剪点与镜长、黑场（区分全黑与深色有内容）与停顿检测（区分极低电平与全声道零样本）；倍频程平衡、重拍前凹陷与波形频谱图 |
| `loudness.py` | `normalize` | 双遍 loudnorm；复制第一条视频，只处理第一条音轨 |
| `preview.py`、`review_server.py` | `preview`、`serve` | 导出审阅页；本地服务支持拖动进度 |
| `config.py` | `routes`、`config-init` | 读取路由配置、连接来源 |
| `project.py`、`workflow.py`、`runner.py`、`usage.py` | `init`、`plan`、`run` 等 | 项目文件、计划生成、执行与登记 |

## 分发形态

- **源码入口**：`python3 scripts/ntf.py`。
- **安装器**：`scripts/install.py` 建立独立 Python 环境，复制七个 Skill，并在每个 Skill 的 `references/runtime.md` 写入实际命令位置。
- **源码包**：`scripts/package.py`，只收集 CLI 与 Skill 相关文件。
- **可执行程序**：`scripts/build_binary.py` 生成 `dist/ntf`，不需要 Python，FFmpeg 仍用本机安装；网页渲染需要源码或安装器环境。

开发与发版步骤见[开发与发版](development.md)。

## 设计取舍

| 决定 | 理由 |
|---|---|
| `state.json` 只由命令写 | 多个 Agent 或多次中断时，状态仍与实际文件一致；同一项目的写状态命令串行执行 |
| 新候选不覆盖旧文件，采用关系单独记录 | 改稿时可以回到任何旧版本，换素材不必重新生成 |
| 付费请求结果不明时不自动重发 | 避免超时后重复扣费；已有任务 ID 时继续查询原任务，重发要显式 `--retry` |
| 能力未确认不发请求 | 模型名称不能说明网关实际支持什么，猜测的参数可能被静默丢弃或报错扣费 |
| 凭据不进路由配置和项目快照 | 配置和项目可以分享、提交；令牌只在请求时读取 |
| 检查结果只做提示 | 静态画面、有意停留也会被标成冻结；好坏需要结合设计判断 |
| 制作项目 schema 保持 1 | 新设计记录先放备稿或已有扩展字段，旧项目无需迁移 |
| 可执行程序用目录模式 | 单文件模式每次启动都要解包，且被系统重新检查，约 6 秒；目录模式只在首次启动时检查 |
