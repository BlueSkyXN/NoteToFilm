# CPA 图像通道

使用 `openai-images` 图像路由时，根据实际配置选择模型、地址和认证引用。图像与视频采用独立连接时分别配置，不串用凭据。路由样例的生图连接声明 `codex_provider: "selected"`，与 Codex 当前选用的 provider 共用地址和令牌，每次请求时读取；设置了 `NTF_CPA_BASE_URL`、`NTF_CPA_API_KEY` 时以环境变量为准。`ntf routes` 可查看实际来源。

## 模型与能力核对

用 `ntf routes --config FILE` 核对精确模型 ID、账号、模式与路由能力。模型清单列出某ID，只证明网关收录。

路由样例 `configs/cpa-uniapi.example.json` 默认使用 `gpt-image-2.6-sunburst`（路由 `cpa-image-2-6-sunburst`），2.5 Flare 与 Sunburst 保留为可选路由。同样请求 1280×720，2.6 Sunburst 实测返回 1280×720，2.5 Flare 曾返回 1672×941；以实际文件尺寸为准安排裁切和合成。

## GPT Image 参数怎么用

这条通道是 OpenAI 原厂 GPT Image，能力按路由声明使用：

| 需要 | 参数与做法 |
|---|---|
| 指定画幅 | `size` 为 `auto` 或 `宽x高`：两边是 16 的倍数，最长边不超过 3840，总像素 655,360–8,294,400，长宽比不超过 3:1。16:9 常用 `1536x864`、`1280x720`、`2048x1152`、`2560x1440`（实测可用）、`3840x2160`；`1920x1080` 的 1080 不是 16 的倍数，会在本地被拒，错误信息给出同比例的最近合法尺寸。竖屏 `864x1536` |
| 质量与速度 | `quality`：`low` 适合草图和方向比较，`medium` 日常，`high` 用于定稿与基准图 |
| 抠图素材 | `background: "transparent"` 配 `output_format: "png"`，得到带透明通道的物件，可直接作为 `ntf motion` 图层或代码动画素材叠在任意背景上 |
| 一次多张候选 | `count` 1–4（原厂最多 10），同一提示词得到多张候选，按 `select_index` 或 `ntf select` 采用 |
| 局部修改 | `reference_to_image` 加 `mask`：PNG，与第一张参考图同尺寸，透明区域是要改的地方。适合加减物件、去字、改颜色和修变形。遮罩是引导而非硬边界，遮罩外也可能被改动，采用前与原图并排对比。改变物件的物理状态（插入深度、开合、位置）成功率低：实测把“半插的模块”改成“插到位”两次都把模块整个抹掉，这类状态变化交给图生视频 |
| 多图合成 | 最多 16 张参考图，提示词按“图片1、图片2”说明各自用途。合成会重新构图；需要保持原构图时改用遮罩修改 |
| 体积 | JPEG 用 `output_compression` 0–100 控制压缩 |

实测范围（2026-11）：1280×720 文生、1536×864 高质量透明背景、单图遮罩修改、两图合成均成功。提示词写明“画面任何地方不出现文字、字母、数字、编号、标签、贴纸、条码、商标或屏幕内容”时，12 张设备与手部特写全部无字。`xhigh`、`max` 质量档与 WebP 输出在本通道未测。2026-11 另测：`images/edits` 曾有一天对带参考图的请求返回 400 `Missing required parameter: 'input'`，第二天恢复，文生图同期正常，遇到时隔一段时间用一次小请求复测；以原图为参考、2560×1440 高质量重画，构图基本不变；以一张人像照片作身份参考、把人物画进指定插画风格，长相保持得很像。

当错误显示模型、账号或请求不匹配时，停止同通道剩余请求，检查正文和Retry-After，不反复重发或直接归因“参考编辑不支持”。

## 原生请求形状

按连接配置的基址和路径组合 `images/generations` 与 `images/edits` 端点；HTTP使用`User-Agent: NoteToFilm-CLI/<版本>`。

普通生图为JSON。参考图编辑支持以下两种形状，按实际已实现的方式发送：

- multipart：文本字段`model`、`prompt`等，参考文件字段为`image[]`，按输入顺序发送。当前原生脚本与`openai-images`适配器采用此方式。
- JSON：`images`必须为对象数组，每项为`{"image_url":"data:image/png;base64,..."}`。不要发送`image:"..."`或`images:["..."]`。CPA本地源码会把multipart文件转换成该对象数组后转发。

```json
{"model":"<图像模型ID>","prompt":"<画面描述>","images":[{"image_url":"data:image/png;base64,..."}]}
```

这段是协议示例；不要把base64或完整凭据输出到日志。JSON方言仅用于解释协议，现有脚本不需要改成JSON编辑才可使用正确模型。

## 项目请求与参考约束

单项请求采用扁平JSON：

```json
{"kind":"image","route":"<图像路由ID>","mode":"reference_to_image","prompt":"<画面描述>","references":[{"selection":"reference.primary","position":1,"role":"appearance","instruction":"<参考用途>"}],"selection_slot":"s02.image"}
```

先导入并采用真实参考文件，再引用素材ID或selection。先读 routes 确认当前配置和参考数量上限。需要多图时核对适配器与通道的实际组合，不静默只传首图或用拼图冒充多参考图。

输出读取 `data[].b64_json` 或图片地址；保留原图，核对解码与实际尺寸。输入外观一致性仍需检查产物，预览先缩小并转JPEG再读取。

mask 与流式中间图按实际适配实现处理。
