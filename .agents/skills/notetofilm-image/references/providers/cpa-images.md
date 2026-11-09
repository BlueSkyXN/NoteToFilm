# CPA 图像通道

使用 `openai-images` 图像路由时，根据实际配置选择模型、地址和认证引用。图像与视频采用独立连接时分别配置，不串用凭据。

## 模型与能力核对

用 `ntf routes --config FILE` 核对精确模型 ID、账号、模式与路由能力。模型清单列出某ID，只证明网关收录。

当错误显示模型、账号或请求不匹配时，停止同通道剩余请求，检查正文和Retry-After，不反复重发或直接归因“参考编辑不支持”。

## 原生请求形状

按连接配置的基址和路径组合 `images/generations` 与 `images/edits` 端点；HTTP使用`User-Agent: NoteToFilm-local/0.1`。

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
