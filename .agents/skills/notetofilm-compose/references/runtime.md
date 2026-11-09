# 定位本机运行代码

## 项目内运行入口

在 NoteToFilm 项目中，从仓库根目录检查 `local/bin/ntf`。入口存在时，以它作为下文的 `ntf` 命令，先执行 `local/bin/ntf install-info` 检查依赖；该入口由本机维护，保存在 Git 忽略的 `local/` 中。

该入口不存在时，使用已安装且可用的 `ntf`，或按下文选择源码入口。

实验时可直接使用用户指定的源码目录，无需先安装 Skill 或注册插件。使用具备所需依赖的 Python 执行 `python scripts/ntf.py install-info`，同一入口可执行全部子命令。在源码根目录执行 `PYTHONPATH=runtime python3 -m notetofilm_local install-info`；后续用同一入口替代文档中的 `ntf`。切换工作目录时将 PYTHONPATH 指向已知源码根下的 runtime 绝对路径。

使用 `scripts/install.py` 安装后，安装器会把本机 `ntf` 命令、Python 环境与同套件技能的准确位置写入本文件。

已经通过其他方式安装运行包时，使用该安装过程给出的命令路径并执行 `ntf install-info`。不要遍历用户目录寻找其他插件，也不要依赖 `../../runtime/` 或同胞 Skill 的相对路径。

优先复用当前已验证的稳定 CLI 和依赖，不为每次制作新建 venv、重装工具或注册 Skill。工具原有的专用依赖环境继续由其安装器管理；只有实际缺少依赖且当前任务需要时，才按用户授权补充环境。

源码入口或已安装入口都不可用时，先完成材料与导演任务，再准备运行环境。媒体生成需要相应通道，合成需要 FFmpeg/ffprobe；这些条件按实际步骤检查。不要把仅写出计划描述为已生成视频。

`ntf config-init FILE` 生成六条未配置路由。图像与视频使用独立连接时，两条连接分别引用地址与凭据。使用前读取通道说明并用 `ntf routes --config FILE` 核对；模板中的 evidence 区分服务实测与运行代码联通。模型 ID 不决定接口协议。

真实素材和具体业务案例不写入 Skill 文件；材料按用户指定的制作项目管理，连接信息与凭据继续使用已有配置。

只交付CLI时可运行`python3 scripts/install.py --runtime-only --runtime-dir /path/to/tool --with-audio --with-render`。安装器返回稳定的ntf_command，一般为工具目录下bin/ntf；使用该入口即可，无需激活环境或引用主项目Python路径。工具专用依赖环境由安装器管理，仍需本机Python 3.11+及FFmpeg/ffprobe。runtime-only不复制或注册技能。

已有本安装器管理的 runtime-only 工具时，从新版本源码目录执行 `python3 scripts/install.py --runtime-only --upgrade --code-only --runtime-dir /path/to/tool`。该模式只更换运行包和版本记录，复用 Python、启动器和第三方依赖，不调用 pip、不新建环境；成功保留 `code-backups/`，启动检查失败恢复原包。不要带 `--with-audio`、`--with-render` 或 `--skills-dir`。完成后用原命令路径检查 `--version` 与 `install-info`。已注册技能的安装仍使用普通升级流程。
