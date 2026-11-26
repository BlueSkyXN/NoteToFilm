# NoteToFilm · CLI 与 Skill 制片工具

用一个 Agent 和七个 Skill 整理材料、设计分镜、制作图片／视频／配音，再通过 `ntf` 完成剪辑、字幕、声音后期与 MP4 交付。项目、素材和历史成片保存在本机；图像、视频和 Edge TTS 按配置访问外部服务。

NoteToFilm 目前有两种形态：**NoteToFilm CLI**（命令 `ntf`）加七个 Skill，是当前的开发重点；Web 工作台（`app/`，说明见 `WEB.md`）暂不维护。以后可能增加 Server 等形态，`ntf` 专指命令行形态。

CLI 源码位于 `runtime/notetofilm_local/`（Python 包名沿用 `notetofilm-local`），七个 Skill 的唯一源码位于 `.agents/skills/`。CLI 版本为 **0.5.1**，制作项目 schema 保持 **1**。工作原理、网关接入、错误处理和开发说明见[文档索引](docs/README.md)。

## 从仓库运行

需要 Python 3.11+，媒体处理需要 FFmpeg 和 ffprobe。已有包含所需依赖的 Python 环境可以直接复用：

```bash
python3 scripts/ntf.py --help
python3 scripts/ntf.py install-info
```

如需建立专用开发环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[audio,render]'
.venv/bin/python scripts/ntf.py install-info --require-audio --require-render
```

`audio` 提供 Edge TTS；`render` 提供 Pillow，用于图层动效和文字渲染。JSON／TOML 配置使用标准库；读取 YAML 时增加 `yaml` 可选依赖。基础命令不要求安装 Web 的 FastAPI、Uvicorn 或 Hugging Face 客户端。

离开仓库执行时传入 `scripts/ntf.py` 的绝对路径。后文 `ntf` 表示这一源码入口、安装器返回的命令或下面构建的 `dist/ntf`。

### 构建可执行程序

```bash
python3 -m pip install -e '.[audio,render,build]'
python3 scripts/build_binary.py
dist/ntf --version
```

`dist/ntf` 指向 `dist/ntf-runtime/ntf`，运行时不需要 Python。构建环境中已安装的 edge-tts、Pillow、PyYAML 一并打包，FFmpeg 仍使用本机安装。移动程序时，将 `ntf` 链接和整个 `ntf-runtime/` 放在同一目录。首次启动时系统会检查其中的库文件，需要几秒，之后启动很快。网页动画渲染不随程序打包，使用源码入口或安装器环境并装上 `web` 可选依赖。

## 先合成一条离线样片

在具备媒体依赖的环境中，从仓库根目录执行：

```bash
python3 examples/create_media_fixture.py --output /path/to/new-demo --render
python3 scripts/ntf.py inspect /path/to/new-demo/output/video.mp4 --decode --expect-width 640 --expect-height 360 --expect-fps 15 --expect-duration 4.6 --expect-audio yes
```

输出约 4.6 秒的 H.264／AAC 视频，包含图片与视频混排、裁剪、末帧延长、旁挂字幕和四种声音策略。素材来自程序生成的图案和测试音，整个示例不调用模型或配音服务。每次选择新目录；字幕烧录与详细输出见 [离线媒体示例](examples/MEDIA_FIXTURE.md)。

## 使用七个 Skill

在本仓库中，支持项目技能的客户端可从 `.agents/skills/` 发现入口。可以直接交给 Agent：

> 使用 notetofilm-workflow，把这些材料做成横版讲解视频。整理来源，设计正式分镜，优先复用已有素材，按需要制作图像、视频片段与旁白，最后输出 MP4 和审阅页。

| Skill | 负责的工作 |
|---|---|
| `notetofilm-workflow` | 阶段、依赖、局部修改和中断后继续 |
| `notetofilm-prepare` | 材料、来源、原图和制作目标 |
| `notetofilm-direct` | 叙事、制作路线、画风、正式旁白和分镜 |
| `notetofilm-image` | 生图、参考编辑、图片复用与采用 |
| `notetofilm-video` | 视频片段提交、查询、下载与选片 |
| `notetofilm-audio` | Edge TTS、读法、实际时长和字幕边界 |
| `notetofilm-compose` | 动效、剪辑、文字与声音后期、成片检查和审阅 |

一个 Agent 可以按需依次读取各技能。只做生图、配音或现有素材合成时，可以直接进入对应 Skill。职责与资料归属见 [技能布局](docs/skill-layout.md)。

## 安装到其他客户端

在源码根目录运行，目标路径由使用者选择，且与源码目录分开：

```bash
python3 scripts/install.py \
  --skills-dir /path/to/client/skills \
  --runtime-dir /path/to/notetofilm-runtime \
  --with-audio --with-render
```

安装器为 CLI 建立独立 Python 环境，复制七个 Skill，并在每个 Skill 的 `references/runtime.md` 开头记录实际命令与同套件技能的位置。使用输出的 `ntf_command` 运行；安装后源码可移走。客户端按自身要求重新加载技能。

省略 `--with-audio --with-render` 时，基础安装不下载依赖，仍可处理现有媒体；联网配音、图层动效及 Pillow 文字处理需相应依赖。只安装命令时改用 `--runtime-only`，省略 `--skills-dir`。

相同路径更新整套工具与技能时增加 `--upgrade`，只替换属于本安装器的目录。已有 runtime-only 安装可使用 `--runtime-only --upgrade --code-only` 只更新代码，复用解释器和依赖；启动检查失败时恢复旧包。

## 配置图像与视频通道

```bash
ntf config-init /path/to/routes.json
ntf routes --config /path/to/routes.json
```

初始文件包含七条待配置路由；需要按实际网关确认地址、认证、模型、协议和能力后使用。`configs/` 提供通用结构及协议样例。协议和能力由配置声明，支持 `openai-images`、`ark-video`、`newapi-video`、`gemini-veo`；各模型实际可用模式取决于所选服务。

地址与凭据不写进路由配置和 Skill，按顺序取得：

1. 已设置的环境变量（如 `NTF_UNIAPI_BASE_URL`、`NTF_UNIAPI_API_KEY`），优先级最高。
2. 仓库根目录的 `.env`（已被 git 忽略），格式为每行 `NAME=value`；命令启动时读取，不覆盖已有环境变量。
3. 路由连接写 `"codex_provider": "selected"` 时，每次请求即时读取 Codex 配置中当前 provider 的 `base_url` 与令牌；也可写具体 provider 名称。`configs/cpa-uniapi.example.json` 的生图连接按此方式与 Codex 共用。

`ntf routes --config FILE` 显示每条路由的地址来源和凭据来源。仍可用 `--connections-file /path/to/connections.private.json` 为单次调用绑定私有连接。业务材料和生成媒体放在源码之外。请求、模式及失败处理见 [通道配置说明](docs/company-protocols.md)。

提交结果不明时先检查动作状态；已取得任务 ID 时继续原任务查询与下载。`--retry` 明确创建新尝试，`--force` 明确重做已完成动作，两者都可能产生新费用。

## 制作项目与修改

| 文件或目录 | 内容 |
|---|---|
| `project.json` | 制作说明、声音、画幅和默认路由 |
| `sources/`、`materials.md` | 原始资料、来源索引与可讲事实 |
| `storyboard.json` | 唯一正式分镜；`views/` 提供阅读版 |
| `workflow.json` | 当前动作及依赖 |
| `state.json` | 已执行尝试、素材、采用关系和状态 |
| `assets/` | 实际取得的图像、视频与音频 |
| `renders/` | 各版成片、清单和时间表 |

Agent 维护材料与正式分镜；运行代码执行计划并登记实际结果。更改分镜后重新 `ntf plan`，再用 `ntf ready`／`ntf status` 查看受影响动作。只修改旁白时保留可复用画面；新候选与新成片保留旧版本。同一项目的写状态命令串行执行，远端已提交任务可以并行处理。

支持按现有图音直接合成、图片与视频混排、图层关键帧、裁切与变速、跨镜转场、字幕配字、背景轨、混音、双遍响度校准和审阅页。内容事实、动作连续性、节奏与观看效果在导演及审片阶段核对：`ntf sheet` 按时间生成带镜头标注的联系表，供 Agent 查看全片、剪点和指定时段；`ntf inspect --scan` 标出冻结、黑场和静音区间。需要准确又连续的图解动画时，可以写一个按时间绘制的网页，用 `ntf web-render` 逐帧渲染为项目素材（需要 `web` 可选依赖与 Chromium 或 Chrome）。

## 开发、验证与打包

```bash
python3 -m pip install -e '.[audio,render,test]'
python3 scripts/check_cli.py
version=X.Y.Z  # 替换为待发布的 CLI 版本号
python3 scripts/package.py --output "dist/cli-v${version}/notetofilm-local-${version}.zip"
```

命令请用装好上述依赖的解释器执行；环境准备、回归不覆盖的部分与发版步骤见[开发与发版](docs/development.md)。严格入口要求测试数大于零、无失败且无跳过，包含真实本地媒体处理、协议与恢复测试，以及从源码包安装七个 Skill 和真实 CLI、移走源码后再合成与检查的验证。模型与 TTS 使用测试替身。

公共说明只在 `shared/` 修改，再运行：

```bash
python3 scripts/sync_skill_references.py --write
python3 scripts/sync_skill_references.py --check
```

分发器按 CLI 组件清单收集 CLI 源码、技能、配置样例、示例生成器、文档和测试。ZIP 与 tar.gz 都保留仓库布局；不复制 Web 应用、已安装环境、制作项目或 `local/`。解压后从其中的 `README.md` 开始。

GitHub Actions 在推送和 PR 时运行 `cli-regression`，执行同一个 `scripts/check_cli.py`。Web 的既有回归由 `scripts/check_tests.py` 执行，在 Actions 中手动触发 `offline-regression` 运行。

## 当前边界

- 自动化检查覆盖协议处理、项目状态与媒体技术规格；真实服务连通性及内容质量需要按实际环境验收。
- Edge TTS 需要联网，服务返回时间边界后才能生成对应字幕；缺少边界时保留缺项。
- 复杂摄影动作与人物／设备连续性由素材及生成服务承担，按镜头选择参考与可用区间。
- 当前没有拖拽时间线、跨设备账号或集中调度服务；本地项目状态由 CLI 管理。

## 许可

NoteToFilm 以 GPL-3.0-or-later 发布，全文见 [LICENSE](LICENSE)。从第三方复用或改编的代码和文本遵循原作者的协议，来源与位置见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
