# 开发与发版

面向修改 NoteToFilm CLI 与 Skill 的开发者。开发范围、目录职责和协作规则以仓库根目录的 `AGENTS.md` 为准（源码包不含此文件）；Web 工作台（`app/` 等）暂不维护。

## 准备环境

需要 Python 3.11 及以上，以及带 libx264、libmp3lame、aac、png 编码器的 FFmpeg 和 ffprobe。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[audio,render,test]'
```

可选依赖：

| extra | 用途 | 额外要求 |
|---|---|---|
| `web` | `ntf web-render`（Playwright） | 本机 Google Chrome，或 `.venv/bin/python -m playwright install chromium` |
| `build` | `scripts/build_binary.py`（PyInstaller） | — |
| `yaml` | 读取 YAML 路由配置 | — |

下文命令都用装好上述依赖的解释器执行（示例为 `.venv/bin/python`）。系统 `python3` 若缺少 edge-tts、Pillow 或 PyYAML，严格回归会在依赖检查处退出。

构建后端要求 setuptools 77 及以上。普通 `pip install` 会在隔离环境中自动取得；使用 `--no-build-isolation` 时，当前环境的 setuptools 需要满足这个版本。

## 回归

```bash
.venv/bin/python scripts/check_cli.py
```

严格回归依次检查 Python 版本、测试依赖、FFmpeg 编码器、`shared/` 与七个 Skill 的同步状态，再运行 `tests/cli/` 全部测试。要求测试数大于零，且没有失败、错误或跳过。模型通道与 TTS 使用替身，不联网，不产生费用。

只跑部分测试：

```bash
PYTHONPATH=runtime:tests/cli .venv/bin/python -m unittest test_company_protocols -k config_init
```

### 回归不覆盖的部分

| 部分 | 怎么验证 |
|---|---|
| `web-render` 的真实浏览器渲染 | 测试只覆盖参数检查和辅助逻辑。按下方步骤手动渲染骨架页 |
| 真实模型通道 | 需要网络与私有连接，会产生费用，须事先获得授权；结果记入路由的 `capabilities.evidence` |
| 画面与叙事质量 | 用真实小样生成联系表（`ntf sheet`）查看 |

手动验证 `web-render`（在仓库根目录执行，临时制作项目建在仓库外）：

```bash
W=$(mktemp -d)
.venv/bin/python scripts/ntf.py init "$W/proj" --title web-render
mkdir -p "$W/proj/animation"
cp -R .agents/skills/notetofilm-compose/assets/code-animation "$W/proj/animation/s01"
.venv/bin/python scripts/ntf.py web-render "$W/proj" --page animation/s01 --scene s01 --preview-time 1 --preview-time 3.5 --text-check
.venv/bin/python scripts/ntf.py web-render "$W/proj" --page animation/s01 --scene s01
```

预期：预览返回 `deterministic: true`，文字检查没有问题项；渲染得到 1280×720、30fps、7 秒的无声视频，再次执行返回 `status: reused`。

## 常见改动

| 改动 | 需要同时做的事 |
|---|---|
| 新增或修改命令 | 改 `runtime/`，在 `tests/cli/` 补测试，更新 `shared/commands.md` 并同步，改相关 Skill，在 `CHANGELOG.md` 记一条 |
| 改公共说明 | 只改 `shared/` 的三份文件，再执行 `.venv/bin/python scripts/sync_skill_references.py --write` |
| 改 Skill | `.agents/skills/` 是唯一源码。相对链接必须指向文件（布局测试会检查）；职责划分见[技能布局](skill-layout.md) |
| 新增模型或通道 | 更新 `runtime/notetofilm_local/data/models.json` 与 `configs/` 样例；能力按供应商文档、网关接受的请求、适配器已实现的字段、实测结果四层记录，未测的组合写明未测；协议变化同步[通道配置说明](company-protocols.md) |
| 新增依赖 | 放进可选 extra，说明用途；基础命令保持只依赖标准库 |
| 复用第三方代码或文本 | 在根目录 `THIRD_PARTY_NOTICES.md` 登记来源、协议、位置并附原许可文本；只复用与 GPL-3.0-or-later 兼容的内容 |

真实连接地址和密钥只放仓库根目录 `.env`（已被 git 忽略），生图连接读取 Codex 配置。过程记录放 `local/`，不提交。

## 端到端制作验证

改完 Skill 后，用一条真实素材从头到尾做一遍，看指导文字是否够用。验证做得好不好，取决于执行的 Agent 只依靠 Skill：

- 由新会话执行，只给材料和一句任务，例如“用 notetofilm-workflow 把这份材料做成横版视频”；不提供以前版本的分镜、成片或复盘，也不让它读取 `local/` 下同一材料的旧产物。
- 维护者事后对照复盘，把卡住、靠猜或做出默认选择的地方，记成对 Skill 或 CLI 的具体修改。
- 付费生成先确定预算；用 `ntf status PROJECT --usage` 核对各模型的提交状态、登记素材数和生成视频秒数，按通道的计费方式折算，实验结束后再用账号用量核对。
- 记录、产物和预算放在 `local/<日期>-<主题>/`，不提交；材料涉及业务时也只放在那里。

同一份材料多次验证时，后几轮已经看过前面的结果，只能证明改进有效，不能证明在新题材上同样适用；隔轮换用新材料。

## CI

`.github/workflows/tests.yml` 有两个任务：

| 任务 | 触发 | 内容 |
|---|---|---|
| `cli-regression` | 推送、PR、手动 | Ubuntu 24.04、Python 3.11；安装 FFmpeg 与 `.[audio,render,test]`，检查 `ntf --version` 与 `install-info`，运行 `check_cli.py`，打源码包 |
| `offline-regression` | 只在手动运行工作流时 | Web 的回归、前端语法检查和 Docker 镜像构建 |

## 发版

1. 定版本号。按语义化版本：0.x 阶段新增功能升次版本号，只有修复时升修订号。
2. 同步修改三处版本号：`pyproject.toml`、`runtime/notetofilm_local/__init__.py`、`plugin.json`。测试会核对三者一致。
3. 在 `CHANGELOG.md` 把"未发布"改成发布日期。
4. 运行严格回归。
5. 构建可执行程序并确认版本：`.venv/bin/python scripts/build_binary.py`，再执行 `dist/ntf --version`。
6. 发布附件按 CLI 标签存放在 `dist/cli-v<版本>/`。用 `.venv/bin/python scripts/package.py --output "dist/cli-v<版本>/notetofilm-local-<版本>.zip"` 生成源码 ZIP。将扩展名换成 `.tar.gz` 可生成另一种源码包。将本版的 wheel 和 `SHA256SUMS` 放在同一目录。
7. 开 PR，等 `cli-regression` 通过后合并。
8. 打标签。仓库已有的 `v0.2.0`、`v0.3.0` 是 Web 版本，CLI 版本使用 `cli-v<版本>`（如 `cli-v0.3.0`），避免重名。
