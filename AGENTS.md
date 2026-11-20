# NoteToFilm 仓库指令

## 用途

NoteToFilm 让 Agent 把故事或业务材料做成可以继续修改的视频：七个 Skill 负责材料、导演、图片、视频、配音和后期的方法，`ntf` 命令行负责项目状态、模型通道、媒体处理与交付。仓库公开，以 GPL-3.0-or-later 发布（`LICENSE`）。

## 产品形态与命名

- NoteToFilm 当前形态：NoteToFilm CLI（命令 `ntf`，源码 `runtime/notetofilm_local/`）＋七个 Skill；Web 工作台（`app/`）暂不维护；以后可能增加 Server 等形态。
- `ntf` 专指命令行形态。面向人和 Agent 的文字称“NoteToFilm CLI”或“`ntf`”；Python 包名 `notetofilm-local`、模块名 `notetofilm_local` 和插件名保持不变，安装器靠它们识别和升级已有安装。新增形态另起名称，不复用 `ntf`。

## 当前开发范围

- 只开发 CLI＋Skill：`runtime/`、`.agents/skills/`、`shared/`、`scripts/`（`check_tests.py`、`migrate_config.py` 除外）、`tests/cli/`、`configs/`、`examples/`、`docs/`、`README.md`、`CHANGELOG.md`。
- Web 版暂不维护：`app/`、`vendor/`、`WEB.md`、`API.md`、`Dockerfile`、`compose.yml`、`requirements.txt`、`config.example.toml`、`.env.example`、`tests/` 下 `cli/` 以外的文件、`scripts/check_tests.py`、`scripts/migrate_config.py`。用户明确要求时才修改；CLI 的新能力不同步实现到 Web，也不为 Web 调整 CLI 设计。
- Skill 版跑通并稳定制作出成片后，再评估恢复 Web 开发。

## Agent 启动行为

- Codex 以 Git 根为项目根，从仓库根或子目录启动都读取本文件；本仓库没有子目录 AGENTS.md。
- Claude Code 直接加载本文件（仓库和上级目录没有 CLAUDE.md 系列文件）；本仓库不设 CLAUDE.md 桥接文件。
- `.agents/skills/` 是产品的 Skill 源码，不是开发指令；修改它们时按下文 Skill 规则处理。

## 目录地图

| 路径 | 职责 | 本地 AGENTS.md | 何时读 |
|---|---|---:|---|
| `.agents/skills/` | 七个 Skill 的唯一源码；`references/` 按需读取，`assets/` 是复制到备稿或项目的模板 | 否 | 改制作方法、设计指引、模板前读对应 `SKILL.md` 和 `docs/skill-layout.md` |
| `runtime/notetofilm_local/` | `ntf` 实现：项目状态、模型适配器、合成、动效、联系表、网页渲染 | 否 | 新增或修改命令、项目格式、媒体处理前 |
| `shared/` | `runtime.md`、`project-format.md`、`commands.md` 三份公共说明的维护源 | 否 | 改命令说明或项目格式说明时 |
| `scripts/` | 源码入口、安装、打包、同步、严格检查、二进制构建 | 否 | 改分发或验证流程前 |
| `tests/cli/` | CLI、媒体、Skill 布局与分发回归 | 否 | 改 runtime 或 Skill 结构后补测试 |
| `configs/` | 通道与路由配置样例（只含环境变量名） | 否 | 新增模型、协议或路由样例时 |
| `examples/` | 离线媒体样片生成器 | 否 | 改合成行为后核对样片 |
| `docs/` | 面向人的说明：索引、工作原理、开发与发版、常见错误、技能布局、通道配置 | 否 | 改架构、命令错误、发版流程、Skill 职责或通道时，同步对应文档 |
| `app/`、`vendor/`、`tests/`（cli 以外） | Web 工作台及其测试，暂不维护 | 否 | 用户明确要求处理 Web 时 |
| `local/`、`build/`、`dist/`、`data/` | 本机记录、构建产物、运行数据，均不提交 | 否 | — |

## 命令

在仓库根执行。`python3` 指装好开发依赖的解释器（如 `.venv/bin/python`）；系统 Python 缺依赖时严格回归会在依赖检查处退出。`ntf` 下文指 `python3 scripts/ntf.py`、安装器生成的命令或 `dist/ntf`。

| 命令 | 用途 | 环境要求 |
|---|---|---|
| `python3 -m pip install -e '.[audio,render,test]'` | 开发环境 | 需要网络安装依赖 |
| `python3 scripts/check_cli.py` | 严格回归：测试数大于零、无失败、无跳过，含 shared 同步检查与分发安装 | 需要 FFmpeg、ffprobe（含 libx264、libmp3lame、aac、png 编码器）；模型与 TTS 使用替身，不联网 |
| `python3 scripts/sync_skill_references.py --write` / `--check` | 把 `shared/` 同步到七个 Skill 的 `references/` / 只检查 | 无 |
| `python3 scripts/package.py --output "dist/cli-v<版本>/notetofilm-local-<版本>.zip"` | 生成源码分发包 | 发布附件按 CLI 标签存放，也支持输出到仓库外 |
| `python3 scripts/build_binary.py` | 构建 `dist/ntf`（指向 `dist/ntf-runtime/ntf`） | 需要 `.[audio,render,build]`；产物与本机平台对应 |
| `python3 examples/create_media_fixture.py --output /new/dir --render` | 离线样片 | 需要 FFmpeg |
| `ntf web-render PROJECT --page DIR --scene ID` | 网页动画逐帧渲染 | 需要 `.[web]`（Playwright）及 Chromium 或 Google Chrome |
| `ntf run` / `ntf generate` | 真实图片、视频生成 | 需要网络和私有连接；会产生费用 |
| `ntf audio` | Edge TTS 配音 | 需要网络；不收费 |

## 全局规则

- `.agents/skills/` 是 Skill 唯一源码；三份公共说明只在 `shared/` 修改，再运行同步。安装器生成的 `runtime.md` 定位信息不进源码。
- 改 Skill 模板的栏目名、删掉字段或改写被别处引用的段落前，先在 `.agents/skills/` 和 `docs/` 里搜索文字里引用它的地方（例如“设计备稿的对标一栏”），一起改；技能校验只检查链接形式的相对引用。
- 新增或修改 CLI 命令时，同时更新 `runtime/`、`tests/cli/`、`shared/commands.md` 和相应 Skill 说明，并在 `CHANGELOG.md` 记一条。
- Skill 写给 Agent 发挥判断：给适用条件、取舍依据、做法、例子和常见问题。不添加 hook、强制门禁或收尾拦截；运行代码提供能力和查看提示，是否合格由 Agent 依据设计判断。
- 制作项目 schema 保持 `1`。新的设计记录先放备稿或已有扩展字段；必须扩展运行格式时，先说明对旧项目的影响。
- 通道能力分四层记录：供应商文档、网关接受的请求、本地适配器已实现的字段、当前路由的实测结果。只改配置或说明不算实现；未实测的组合写明未测。
- 公开仓库只放通用方法和占位示例。真实连接地址和密钥只放仓库根目录 `.env`（已被 git 忽略；变量名见 `configs/cpa-uniapi.example.json`，如 `NTF_UNIAPI_BASE_URL`、`NTF_UNIAPI_API_KEY`）；生图连接即时读取 Codex 配置（`codex_provider`），不在 `.env` 里配置生图 provider；环境变量优先。账号、私有路径、业务案例名称和客户材料放在仓库外或 `local/`。
- 复用或改编第三方代码和文本时，在根目录 `THIRD_PARTY_NOTICES.md` 登记来源、协议、本仓库位置，并附原许可文本；各目录不另放许可证副本。只复用与 GPL-3.0-or-later 兼容的内容。
- 优先使用标准库和现有依赖；新增依赖放可选 extra（如 `audio`、`render`、`web`、`build`），并说明用途。

## 禁止事项

- 不提交 `local/`、`build/`、`dist/`、`data/`、`.venv/`、任何 `*.private.*` 文件或凭据。
- 不在命令、日志、测试快照或文档中输出完整密钥。
- 不在未获授权时调用会产生费用的生成接口；测试使用替身。
- 不在 `app/` 等 Web 文件中修改代码（见“当前开发范围”）。

## 验证

1. 改动 `runtime/`、`tests/cli/`、`.agents/skills/`、`shared/`、`scripts/` 后运行 `python3 scripts/check_cli.py`，要求输出的 `failures`、`errors`、`skipped` 均为 0。
2. 改动 `shared/` 后先运行 `python3 scripts/sync_skill_references.py --write`。
3. 改动打包或冻结相关代码后运行 `python3 scripts/build_binary.py`，并执行 `dist/ntf --version`。
4. GitHub Actions 的 `cli-regression` 在推送和 PR 时运行同一个 `check_cli.py`（Ubuntu、Python 3.11）；Web 的 `offline-regression` 只在手动触发工作流时运行。
5. 回归不启动浏览器；改动 `web_render.py` 或代码动画骨架后，按 `docs/development.md` 的步骤手动渲染一次骨架页。
6. 合成、动效、联系表等媒体变化另用真实小样检查画面；需要网络、浏览器或付费通道的验证无法执行时，在汇报中写明未验证的部分。

## 给后续 Agent

- 设计方法集中在 `notetofilm-direct`：设计选择、风格库、常见默认做法、段落卡与转场对模板。
- 观看成片用 `ntf sheet`（联系表）和 `ntf inspect --scan`；合成说明在 `notetofilm-compose/references/`。
- 过程记录放 `local/`（全局 gitignore 已忽略），不进提交。
