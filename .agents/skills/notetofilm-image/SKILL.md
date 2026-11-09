---
name: notetofilm-image
description: "按分镜或单独画面要求制作图片，支持配置中的普通生图和多参考图生图。用于生成、替换、复用镜头图片或给视频制作参考图；调用实际通道并登记取得的媒体。"
---

# 图像制作

1. 读 [本机入口](references/runtime.md)、[命令](references/commands.md) 和 [项目格式](references/project-format.md)。单独生图也建立最小项目，不要求先编写无关旁白。
2. 读取指定镜头或用户明确画面要求。按 [画面与参考](references/image-design.md) 确定图片用于成片、外观参考还是首帧，并分开主体、构图、准确文字与风格。已选择纯文生视频的段落无需先做图。
3. 用 `ntf routes --config FILE` 读取实际图像通道。采用 CPA 时读 [CPA 图像通道](references/providers/cpa-images.md)，核对精确模型名、编辑请求与参考边界。其他通道读取实际配置及相应协议资料。
4. 原图先 `ntf import`，保留返回 ID。多参考图按实际顺序传对象列表，并说明每张图的作用。普通外观参考与视频首尾帧不是同一种约束。
5. 工作流任务读取 `ntf ready` 中的具体图像动作并执行 `ntf run`。单项生成使用 `ntf generate PROJECT --request FILE --config FILE`；项目请求与原生 HTTP 请求分别按对应通道说明填写。
6. 若用户明确选用当前客户端图像工具，由 Agent 调用并取得实际文件，再用 `ntf import` 登记。不要把公司通道失败自动改成客户端工具调用。
7. 保留原件，先另存缩小的 JPEG 再查看，核对动作空间、相邻镜头区别和错误字符。返回实际图片、尺寸、素材 ID 与参考用途；采用时 `ntf select PROJECT SLOT ASSET_ID`，保留其他候选。

需要更改数字、屏幕标题或原意时先更新正式分镜。不能可靠生成的文字和关系，用实际可用排版能力制作整张 PNG；只改变背景风格不需要重写旁白。
