# NoteToFilm 文档

按要做的事找入口。

| 我想…… | 读这里 |
|---|---|
| 了解 NoteToFilm、先跑起来、安装到客户端 | [仓库 README](../README.md) |
| 从安装走到第一支能看的片子，再加入视频生成 | [入门](tutorial.md) |
| 理解它怎么工作：Agent、Skill、`ntf` 的分工，项目从材料到成片的过程 | [工作原理](architecture.md) |
| 接入自己的图像、视频网关 | [通道配置说明](company-protocols.md)，从开头的接入步骤开始 |
| 查命令和参数 | [命令说明](../shared/commands.md)，或 `ntf <命令> --help` |
| 查项目文件和分镜字段 | [项目文件](../shared/project-format.md) |
| 命令报错了 | [常见错误与处理](troubleshooting.md) |
| 改代码、加命令、发版 | [开发与发版](development.md) |
| 改 Skill、新增设计方法 | [技能布局](skill-layout.md) |
| 看版本变化 | [更新记录](../CHANGELOG.md) |
| 看许可与第三方来源 | [LICENSE](../LICENSE)、[第三方参考与许可](../THIRD_PARTY_NOTICES.md) |

`docs/` 只放面向人的说明。制作方法（导演、风格、生图、视频、配音、合成手法）写在 `.agents/skills/` 各 Skill 的 `references/` 中，命令与项目格式写在 `shared/`，这些是写给 Agent 的资料，人也可以直接读。Web 工作台的说明在仓库根目录的 `WEB.md`，目前暂不维护，源码包不包含 Web 部分。
