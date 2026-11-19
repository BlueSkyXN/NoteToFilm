# 技能布局与设计方法归属

七个顶层技能按工作职责提供入口，玩法作为导演技能内按需读取的方法。Skill 目录保持客户端可发现的平铺结构；编排、内容设计、素材制作和后期交付通过职责区分。

## 入口职责

| 技能 | 负责的决定和产出 | 何时可直接进入 |
|---|---|---|
| workflow | 选择阶段、依赖、状态恢复与完成范围 | 完整制作、局部修改、中断后继续 |
| prepare | 事实、来源、原图和材料用途 | 材料尚未整理或需要补充来源 |
| direct | 叙事方式、制作路线、视觉语言、章节和正式分镜 | 选玩法、改故事感、改风格、设计音画 |
| image | 图像及参考素材的生成、复用、采用和质量检查 | 画面目标已明确，或独立生图 |
| video | 输入模式、任务提交恢复、原片与可用范围 | 事件目标已明确，或续查已提交任务 |
| audio | 实际配音、读法、时间边界与字幕 | 正式旁白已确定，或独立配音 |
| compose | 剪辑窗口、文字与声音后期、合成、验收和审阅入口 | 已有足够素材与顺序，可直接成片 |

同一 Agent 可连续执行。单项生图、配音、任务恢复和现有素材合成无需经过整套设计流程。

## 目录结构

```text
NoteToFilm/
├── .agents/skills/
│   ├── notetofilm-workflow/       # 阶段路由与执行组织
│   ├── notetofilm-prepare/        # 材料及来源
│   ├── notetofilm-direct/         # 方案与分镜
│   │   ├── SKILL.md
│   │   ├── assets/
│   │   │   ├── design-brief.template.md  # 设计摘要、美术设定、段落卡、转场对、音画表与草图粗剪
│   │   │   └── style-recipe.template.md  # 可复用的风格配方
│   │   └── references/
│   │       ├── design-map.md      # 片型 × 制作路线 × 视觉语言 × 声音
│   │       ├── formats.md         # 片型配方：十种片型的结构、开头、手法与坑
│   │       ├── story-design.md    # 叙事方式、事实依据、段落与节拍、节奏和时长
│   │       ├── script.md          # 旁白与画面文字
│   │       ├── art-direction.md   # 美术设定、风格比较、构图分区、参考编号与一致性
│   │       ├── sound-design.md    # 四层声音与声音方向
│   │       ├── visual-language.md # 画风、动作、运镜和转场的总体原则
│   │       ├── techniques/        # 手法卡：camera.md（C01–C14）、info-motion.md（M01–M16）、transitions.md（T01–T15）
│   │       ├── shot-freedom.md    # 单镜约束、动作三状态和镜头覆盖
│   │       ├── examples.md        # 正式分镜字段示例
│   │       ├── pitfalls.md        # 常见默认做法、修正与返工诊断
│   │       ├── styles/            # 风格库：INDEX.md 与各风格文件（人物与场景、影像、证据与拼贴、图形与讲解）
│   │       └── routes/
│   │           ├── evidence-led.md
│   │           ├── image-led.md
│   │           ├── video-led.md
│   │           ├── footage-led.md
│   │           └── hybrid.md     # 按章节组合上述路线
│   ├── notetofilm-image/
│   │   └── references/{image-design,prompts}.md、providers/cpa-images.md
│   ├── notetofilm-video/
│   │   └── references/
│   │       ├── modes.md
│   │       ├── action-prompts.md  # 动作镜头与运镜写法
│   │       ├── providers/uniapi-seedance.md
│   │       ├── resume.md
│   │       └── footage-review.md
│   ├── notetofilm-audio/
│   │   └── references/voice-and-subtitles.md
│   └── notetofilm-compose/
│       ├── assets/code-animation/  # 代码动画骨架：index.html、timing.js、motion.js、kit.js
│       └── references/{timeline,manifest,motion,code-animation,code-recipes,motion-craft,toolbox,sound-mix,delivery}.md
├── shared/                       # 运行说明的维护源
│   ├── runtime.md
│   ├── project-format.md
│   └── commands.md
├── scripts/sync_skill_references.py
├── scripts/build_binary.py       # 构建 dist/ntf
└── runtime/notetofilm_local/      # ntf 执行代码
    ├── config.py                 # 路由解析与连接来源（环境变量、.env、Codex 配置）
    ├── inspection.py             # inspect 媒体探测与 --scan
    ├── motion.py / motion_render.py # 图层动效、关键帧与素材登记
    ├── compose.py / timing.py    # 变速、转场与音画窗口
    ├── loudness.py               # normalize 双遍响度
    ├── sheet.py                  # sheet 按时间抽帧的联系表
    ├── compare.py                # compare 多画面并排、叠合与局部放大
    ├── web_render.py             # web-render 网页动画逐帧渲染（data/text_hook.js 供文字检查）
    └── review_server.py          # serve 可拖动审阅服务
```

图中省略各技能共同的 `agents/openai.yaml` 以及 `references/runtime.md`、`project-format.md`、`commands.md`。这些引用随各技能分发，避免依赖相邻技能目录；源文件统一在 `shared/` 维护。

## 玩法怎么分

[设计选择图](../.agents/skills/notetofilm-direct/references/design-map.md) 是唯一的设计路线入口。先选片型和讲述方式，再选证据图解、图片驱动、视频驱动或现有素材剪辑，最后定视觉语言和声音。段落里的具体手法按问题查手法卡（观察方式、信息变化、衔接方式），卡号和目的写进段落卡。混合编排按章节组合这些路线。画风和模型各自独立：灰阶棱面不限定输入必须是图，故事叙事也不限定必须让模型生成人物表演。

导演先给出事件或解释任务、必须保持的事实、允许发挥的部分及验收点。媒体技能将其转成当前通道真实支持的请求。后期按实际素材与声音安排窗口；模型参数放进原有项目字段，路线名称留在制作说明或备稿，不扩展运行 schema。

## 文件放在哪里

- 入口 `SKILL.md`：触发范围、关键决定和需要时读取的资料；纯设计时不提前加载接口与 CLI 全表。
- `direct/references/routes/`：不同画面来源与控制方式的制作方法。叙事结构和视觉语言由相应公共设计资料维护。
- 媒体技能 `references/providers/`：已有独立篇幅的供应商协议、能力边界与验证范围。新增模型先判断能否沿用现有协议说明。
- 技能 `assets/`：实际要复制到制作备稿或产物中的模板。音画表和风格配方是可选备稿，正式旁白仍以主分镜为准。导演的 `assets/shot-studies/` 放[因果草图](../.agents/skills/notetofilm-direct/references/shot-studies.md)的动图和可改写的 Pillow 制作源。
- `runtime/`：NoteToFilm CLI 的源码，可重复的制作能力通过 `ntf` 参数调用。技能说明引用命令；实现和行为测试在 CLI 中统一维护。
- `shared/`：共同运行说明；业务材料、媒体、私有配置和本机路径留在源码外。

需要新增玩法时优先给对应路线补选择条件；当已有方法无法覆盖且有稳定输入、产出与验收流程时再增加路线文档。只有出现独立的用户触发和工作职责，才考虑新建顶层 Skill。

## 运行与分发边界

NoteToFilm 当前形态是 CLI（`ntf`）加 Skill；Web 工作台暂不维护，以后可能增加 Server 等形态。CLI 源码与技能在同一仓库维护，`.agents/skills/` 是技能的唯一维护源；安装器复制这些文件并生成每台机器的运行定位。

| 位置 | 职责 | 依赖 |
|---|---|---|
| `.agents/skills/` | Agent 的阶段选择和制作方法 | 客户端工具与实际 `ntf` 入口 |
| `scripts/ntf.py` | 从源码启动命令 | `runtime/notetofilm_local/` |
| `runtime/notetofilm_local/` | 项目状态、媒体适配、处理与交付 | 标准库、按功能选用的媒体依赖 |
| `shared/` | 三份公共运行说明的维护源 | 同步生成各 Skill 的自包含引用 |
| `scripts/install.py` | 独立运行环境与七个技能的安装 | 根目录 `pyproject.toml`、`plugin.json` 和正式源码 |
| `scripts/package.py` | CLI 与 Skill 源码包 | 显式组件清单 |
| `tests/cli/` | CLI、媒体与分发安装回归 | `scripts/check_cli.py` 严格入口 |

CLI 与 Web 的 `app/` 相互独立。Web 保留现有服务、数据库及验证入口，当前不合并两套状态管理。路由配置使用 `configs/` 样例；地址与凭据来自环境变量、仓库根目录 `.env` 或即时读取的 Codex 配置，详见[通道配置说明](company-protocols.md)。制作项目由用户指定目录管理。

新增 CLI 命令时修改 `runtime/` 及对应测试；调整制作方法时修改相关 Skill；公共入口说明只修改 `shared/` 再同步。分发与安装验证会移走解压源码，再从独立入口完成真实合成，检查这些边界。

## 维护与验证

更新 shared 后在源码根目录执行：

```bash
python3 scripts/sync_skill_references.py --write
python3 scripts/sync_skill_references.py --check
```

同步工具只管理源码中的三份公共引用。安装器继续生成各机器的实际运行位置；不要用源码同步替换已安装的定位文件。

技能校验检查入口元数据、整个技能内的相对引用、共享副本、打包包含项与私有文件排除。路线评审用具体请求检查入口选择和所需阅读资料；叙事质量在实际成片中审阅。
