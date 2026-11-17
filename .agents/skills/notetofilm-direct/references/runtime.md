# 定位 NoteToFilm CLI

文档中的 `ntf` 指 NoteToFilm 的命令行形态（NoteToFilm CLI）。Skill 通过它管理项目、调用模型通道、处理媒体和交付；`ntf --version` 显示 `NoteToFilm CLI <版本>`。

## 在 NoteToFilm 仓库中使用

完整源码位于仓库的 `runtime/notetofilm_local/`，统一入口是 `scripts/ntf.py`。核对这两个位置存在后，使用已有、具备相应依赖的 Python 执行 `python scripts/ntf.py install-info`，后续用同一入口替代文档中的 `ntf`。离开仓库执行时，传入该脚本的绝对路径。仓库里已构建的 `dist/ntf` 不需要 Python，也可直接使用；它不含网页动画渲染（`web-render`），该命令用源码入口执行。

项目技能的源码在 `.agents/skills/`，公共运行说明由 `shared/` 维护并同步。不要从 Skill 目录拼接 CLI 位置，也不要遍历用户目录寻找其他插件。

## 使用已安装的入口

通过 `scripts/install.py` 安装时，安装器把实际 `ntf`、Python 和同套件技能的位置写入本文件开头；优先使用其中的位置并执行 `ntf install-info`。其他安装方式使用其提供的命令路径。

优先复用当前已验证的 CLI 和依赖，不为每次制作新建 venv、重装工具或注册 Skill。只有实际缺少依赖且当前任务需要时，才按用户授权补充环境。合成需要 FFmpeg/ffprobe；配音需要 Edge TTS；Pillow 用于动效及文字渲染。可用 `install-info --require-audio --require-render` 检查。

源码入口和已安装入口都不可用时，先完成材料与导演任务，指出缺少的运行条件；取得实际媒体后再报告生成完成。

## 配置与制作项目

`ntf config-init FILE` 生成七条未配置路由。通用样例在仓库 `configs/`；图像与视频使用独立连接时，分别引用地址和凭据。使用前读取通道说明并用 `ntf routes --config FILE` 核对；模板中的 evidence 区分服务实测与运行代码联通，模型 ID 不决定接口协议。

连接地址与凭据不写入 Skill、路由配置或制作项目。`ntf` 按以下顺序取得：已设置的环境变量；NoteToFilm 根目录的 `.env`（被 git 忽略，命令启动时读取，不覆盖已有环境变量；`NTF_ENV_FILE` 可指定其他文件）；路由连接声明 `codex_provider` 时，在每次请求时读取 Codex 配置（`$CODEX_HOME/config.toml` 或 `~/.codex/config.toml`）中该 provider 的 `base_url` 与令牌，`selected` 表示 Codex 当前选用的 provider。用 `ntf routes --config FILE` 查看每条路由的 `connection_source` 与 `credential` 来源，不输出具体值。真实素材和具体业务案例保存在用户指定的制作项目。

## 安装与更新

需要把整套技能交付给其他客户端时，从仓库运行 `python3 scripts/install.py --skills-dir /path/to/client/skills --runtime-dir /path/to/tool --with-audio --with-render`。两个目标目录与源码分开，技能目录由用户指定。

只交付 CLI 时使用 `--runtime-only` 并省略 `--skills-dir`。安装器返回实际 `ntf_command`；工具拥有独立 Python 环境，主机仍需 Python 3.11+ 和 FFmpeg/ffprobe。

已有本安装器管理的 runtime-only 工具时，从新版本源码运行 `python3 scripts/install.py --runtime-only --upgrade --code-only --runtime-dir /path/to/tool`。该模式复用解释器、启动器和依赖，只替换代码及版本记录；成功保留 `code-backups/`，启动检查失败恢复原包。不要同时传入 `--with-audio`、`--with-render` 或 `--skills-dir`。完成后用原命令检查 `--version` 与 `install-info`；已注册技能的安装使用普通 `--upgrade` 流程。
