---
name: notetofilm-workflow
description: "从材料制作完整视频，或修改、继续本地视频项目。用于需要安排材料、脚本分镜、图像、视频、配音和合成的跨阶段任务；读取项目现状并执行到用户要求的结果。"
---

# 本地视频工作流

## 开始

1. 先读 [本机入口](references/runtime.md) 和 [命令](references/commands.md)。确定本次目标、项目位置、结束阶段及指定镜头。
2. 没有项目时执行 `ntf init PROJECT --title TITLE`。已有项目先执行 `ntf status PROJECT`，读取正式文件；不要从旧对话重建已经存在的分镜。
3. 需要写入内容时读 [项目格式](references/project-format.md)。根据当前输入按 [阶段路由](references/routing.md) 读取相应已安装 Skill。通过客户端提供的位置或安装后本机入口的清单定位，不拼接同胞目录。

## 推进

4. 材料不足时先 prepare；需要确定叙事、玩法、风格或分镜时进入 direct，由它选择制作路线。已有确定方案时直接进入所需媒体阶段。workflow 管理阶段、状态与依赖，设计方法集中在 direct 中按需读取。
5. 先确定声音与文字由谁制作：模型原生声音、独立旁白或混音，字幕与画面关键词分别安排。将选择落实到视频参数和合成策略，分别记录原生声音能力与本次是否采用。
6. 按 [依赖与修改](references/dependencies.md) 选择制作顺序。分镜驱动的制作在正式分镜保存后执行 `ntf plan PROJECT`；特殊依赖使用 `--file FILE`。探索方向时可先用独立 `generate` 取得候选，再更新正式分镜并用显式清单合成。
7. 需要按旁白定片长时，先 `ntf run PROJECT --kind audio`，再 `ntf timing PROJECT --apply` 按实测校准并重新 plan。视频先行探索时，先选有效动作，再按真实配音安排剪辑窗口。读取所需媒体 Skill，按 `ntf ready PROJECT` 执行具体动作；公司通道调用传实际配置文件。
8. 使用 `ntf run PROJECT --action ID --config FILE --wait-seconds 20` 执行或查询；批次用kind/scene、submit-only/poll-only、max-new-actions与stop-on-error控制。私有连接通过connections-file在源码外读取。只要旧动作仍可查询就继续它，不用新提交模拟轮询。
9. 每次取得实际文件后登记结果，审阅可用范围，再查看状态和下一步。同一项目写 state 的 CLI 串行执行；远端任务可通过批次提交后继续在服务端并行，只读媒体检查可并行。最终合成等待已采用的实际媒体。
10. 改变正式旁白、事实或屏幕文字时回到导演方法，保存主记录。分镜工作流重新 plan；独立候选路线更新正式分镜和合成清单，保留已有动作与素材。只重做实际受影响的部分。

## 完成

成片按 compose Skill 的交付检查核查规格、事件连续性、字幕与声音。后处理后用 `ntf preview PROJECT --video FINAL_FILE --output DIR` 明确导出最终文件。按用户要求在材料、分镜、素材或 MP4 完成后结束，给出实际路径与未完成项。只有模型任务 ID 或提示词时，描述为已提交或已设计。

沿用用户对当前任务已有的次数、费用和通道授权；超出范围或需要新的业务取舍时再确认。连续失败时保留成功素材，按具体错误停止或调整该方向，避免把整批重跑当作恢复。

当前协议尚未配置时，继续完成不依赖该通道的内容、已知媒体和计划，指出缺少的具体连接信息。不要擅自切到官方接口、其他模型或另一家服务。
