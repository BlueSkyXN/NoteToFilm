# 公司 API 配置与适配边界

本文说明 `ntf` 怎样接入公司网关：选择适配器，提供地址与凭据，声明能力，传入参考图与首尾帧，续做异步任务，以及读取错误记录。

## 接入步骤

1. 选一份起点：`configs/cpa-uniapi.example.json` 是已确认的样例（生图走 CPA，视频走 UniAPI）；接入其他网关时用 `ntf config-init routes.json` 生成七条待配置路由。
2. 按网关的接口约定填写每条路由的 `adapter`、`model`、认证方式和能力。认证只写环境变量名；没有确认的能力保持 `unknown`，请求会在发出前被拒绝。
3. 提供地址和密钥。在仓库根目录的 `.env`（已被 git 忽略）按行写 `NAME=value`，变量名以路由配置为准，样例中视频为 `NTF_UNIAPI_BASE_URL`、`NTF_UNIAPI_API_KEY`。生图连接写了 `"codex_provider": "selected"` 时直接读取 Codex 当前 provider，不需要写进 `.env`。
4. 核对来源：`ntf routes --config FILE`，每条要用的路由 `connection_source` 与 `credential` 都不应为 `missing`。这一步不发请求。
5. 小额实测：用最小参数（如视频 480p、4 秒）执行一次 `ntf generate PROJECT --request FILE --config FILE`，会产生费用。结果记入该路由的 `capabilities.evidence`，未测的参数组合注明未测。

出错时按 `code` 查[常见错误与处理](troubleshooting.md)。下文是各部分的详细说明。

## 先明确公司接口，再选择适配器

`configs/company.example.json` 与 `ntf config-init` 生成的默认配置结构相同，包含全部 7 条待配置路由。内置模型清单登记了 4 个图像 ID 和 3 个视频 ID，名称用于请求的 `model` 字符串。协议、认证与能力分别配置；默认的 `adapter: null`、认证 `unconfirmed` 和能力 `unknown` 会阻止请求，需要按实际服务确认后填写。`configs/protocols.example.json` 展示 3 种明确选择协议后的配置形态，保留未知认证和能力。`configs/cpa-uniapi.example.json` 是已确认的样例：生图走 CPA（GPT Image），视频走 UniAPI（Seedance）；`configs/uniapi.example.json` 的图像与视频路由都走 UniAPI。部署时按实际服务选择模型、适配器与参数，并验证连通性。

当前实现的协议如下。所有请求都发往配置的公司地址；代码没有原厂地址回退。

| adapter | 已实现的请求与结果形态 | 默认路径键 |
| --- | --- | --- |
| `openai-images` | JSON 文生图；multipart `image[]` 多参考编辑，可带 `mask`；同步返回的所有 `data` 候选，支持 `b64_json` 或 URL | `generations: images/generations`；`edits: images/edits` |
| `ark-video` | `content` 文本/图片数组创建任务；读取任务 ID；查询任务状态；下载视频和可选末帧 | `submit: contents/generations/tasks`；`poll: contents/generations/tasks/{task_id}` |
| `newapi-video` | 统一视频任务：顶层 model/prompt/seconds，原厂参数和图片在 metadata；查询 completed 后从内容端点下载；请求尾帧时另查原厂任务记录 | `submit: videos`；`poll: videos/{task_id}`；`content: videos/{task_id}/content`；`native_task: doubao/api/v3/contents/generations/tasks/{task_id}` |
| `gemini-veo` | `instances`、`parameters` 的长任务请求；保存 operation name；轮询 `done`；读取 `generatedSamples[].video.uri` | `submit: models/{model}:predictLongRunning`；`poll: {operation}` |

公司若只调整地址、认证头、提交路径、查询路径，可改配置；若调整上传方式、JSON 字段、任务状态、查询方法、响应嵌套或下载签名流程，需要适配代码。以所选网关的接口约定核对协议和能力。

## 地址、认证和配置文件

配置以 JSON 为默认格式；TOML 使用 Python 标准库，YAML 需要另装 PyYAML。`ntf` 的 `--config` 选定文件，也可设置 `NTF_CONFIG`。`base_url` 可直接写不含凭据的公司地址，或用 `base_url_env` 引用环境变量。Base URL 应含公司要求的完整前缀，例如 `/v1`、`/api/v3`；相对路径包括以 `/` 开头的路径都会追加到此前缀，不会自动删除前缀。

`paths` 可放在 connection 或 route；route 的同名值覆盖 connection。绝对提交/查询 URL 必须仍在同一公司 origin。图像路径占位符为空，Ark 查询使用 `{task_id}`，Gemini 提交使用 `{model}`、查询使用 `{operation}`。

认证按公司的实际约定选择以下一种。配置中保存环境变量名；密钥值通过本地环境提供。

```json
{"type": "bearer", "env": "NTF_COMPANY_API_KEY"}
```

```json
{"type": "header", "header": "X-Company-Key", "env": "NTF_COMPANY_API_KEY"}
```

```json
{"type": "none"}
```

Bearer 的默认前缀为 `Bearer `，可显式配置 `prefix`；header 默认不加前缀。需要额外请求头时，在 connection 中用 `header_envs` 将头名称映射到环境变量名。提交/查询不自动跟随重定向。媒体下载可跟随重定向，只有与公司 Base URL 同源时才带公司认证，跨域对象存储 URL 不会收到公司密钥。

### 地址与凭据的来源

按顺序取得：已设置的环境变量；NoteToFilm 根目录 `.env`（启动时读取，不覆盖已有环境变量，`NTF_ENV_FILE` 可指定文件）；连接声明 `codex_provider`（`selected` 或具体名称）时，每次请求读取 Codex 配置中该 provider 的 `base_url`，令牌取 `experimental_bearer_token` 或 `env_key` 指向的环境变量。Codex 的地址会随路由快照保存以便续查，令牌不保存。`ntf routes` 的 `connection_source` 为 `environment`、`configured`、`codex:<名称>` 或 `missing`，`credential` 为 `environment`、`codex`、`not_required` 或 `missing`。

### 临时换用另一份私有连接

`routes`、`generate`、`run` 可加 `--connections-file PRIVATE.json`，为单次调用换用另一份本机私有连接。它只按相同连接 ID 读取 `connections.NAME.base_url` 与 `connections.NAME.credentials.api_key`，密钥绑定到路由配置 `auth.env` 指定的变量，只在当前调用内生效。模型 ID、适配器和路径仍以路由配置为准，不从该文件顶层的 image/video 字段推断。

## 能力是每条路由、每种模式的声明

能力可直接放在 route 的 `capabilities` 对象中，也可把 `capabilities` 写成相对于配置文件的 JSON 路径。每个模式独立声明是否支持、参考图上限、参数和参数组合。默认没有全局“参考图最多 16 张”的假定。

下面只说明配置结构，刻意保持 `unknown` 和 `supported: null`。公司确认后才能填写 `confirmed`、实际支持值与范围；未知参数不应猜成可用。已确认的路由在 `capabilities.evidence` 分开记录供应商文档、网关接受的请求和 `ntf` 实测结果，写法见 `configs/cpa-uniapi.example.json`。

```json
{
  "status": "unknown",
  "modes": {
    "text_to_image": {
      "supported": null,
      "parameters": {
        "count": {"type": "integer", "minimum": 1},
        "size": {"type": "string"}
      }
    },
    "reference_to_image": {
      "supported": null,
      "max_reference_images": null,
      "parameters": {
        "count": {"type": "integer", "minimum": 1}
      }
    }
  }
}
```

参数规则支持 `type`（string/integer/number/boolean）、`enum`、`minimum`、`maximum`。`required_parameters` 是该模式的必填参数名列表。`constraints` 是组合约束数组；每项的 `when` 是触发条件对象，`require` 将受约束参数名映射到允许值数组。例如指定某个分辨率时，只允许公司确认的若干 `duration_seconds` 值。

图像模式是 `text_to_image`、`reference_to_image`；视频模式是 `text_to_video`、`image_to_video`、`reference_to_video`、`first_last_to_video`。仅在能力文件声明可用还不够：适配器也必须实现所请求参数。未实现或未声明的字段会报错，不能通过把字段写进配置让代码自动支持新协议。

各协议当前可映射的生成参数如下。公司能力文件应只声明该公司路由确实提供的子集。

| adapter | 适配器识别的参数 |
| --- | --- |
| `openai-images` | `count`、`size`、`quality`、`output_format`、`background`、`output_compression`、`input_fidelity`（仅参考编辑）、`moderation`、`user`、`safety_identifier` |
| `ark-video` | `count`（仅 1）、`duration_seconds`、`aspect_ratio`、`resolution`、`seed`、`camera_fixed`、`watermark`、`generate_audio`、`return_last_frame`、`service_tier`、`execution_expires_after` |
| `newapi-video` | `count`（仅 1）、`duration_seconds`、`aspect_ratio`、`resolution`、`generate_audio`、`watermark`、`return_last_frame`、`seed` |
| `gemini-veo` | `count`、`duration_seconds`、`aspect_ratio`、`resolution`、`seed`、`negative_prompt`、`person_generation` |

请求可用 `parameters` 和 `output` 携带这些值；相同参数冲突会报错。`output` 同时给出正整数 `width`、`height` 时，转换为图像 `size: "宽x高"`。`count` 映射成 OpenAI 的 `n` 或 Gemini 的 `sampleCount`；Ark 一次只创建一个任务，多候选应拆为多个 action。`duration_seconds`、`aspect_ratio` 会按协议映射成相应字段。未声称 Gemini 协议支持一个通用 `generate_audio: false` 开关。

## 多参考图和首尾帧

普通参考图使用有序 `references` 数组。`position` 若填写，必须从 1 开始且与数组顺序一致。每项可以带 `role`、`instruction`；这些语义会按顺序写入提示词说明。角色一致性需要在实际结果中检查。

首尾帧使用独立的 `start_frame`、`end_frame` 字段：图生视频需要首帧，首尾帧视频同时需要二者。普通参考图不能偷偷变成首帧。当前 4 种视频模式不混用普通参考与端点帧；如果公司另有支持混合输入的约定，需要明确扩展协议和模式。

| 模式 | 输入要求 | 协议映射 |
| --- | --- | --- |
| `reference_to_image` | 非空普通参考图数组；可选 `mask` | OpenAI multipart `image[]` 按数组顺序提交，`mask` 作为单独字段 |
| `reference_to_video` | 非空普通参考图数组 | Ark `reference_image`；New API `metadata.content` 中 role 为 `reference_image`；Gemini `referenceImages`，每项 `referenceType: asset` |
| `image_to_video` | `start_frame` | Ark `first_frame`；New API role `first_frame`；Gemini `instances[0].image` |
| `first_last_to_video` | `start_frame` 和 `end_frame` | Ark `first_frame` 然后 `last_frame`；New API role `first_frame`、`last_frame`；Gemini `instances[0].image` 与 `lastFrame` |

参考图先导入项目，运行时解析为项目内本地路径。当前接受 PNG、JPEG、WebP，按内容判断类型；绝对路径和符号链接也不能逃出项目根。图片数据通过 multipart 或 data/inlineData 发送，不要求把本地图片预先放到公网。

`mask` 只用于 `reference_to_image`，作用于第一张参考图：必须是 PNG，透明区域为要修改的部分；第一张参考图也是 PNG 时，两者像素尺寸必须相同。路由需在该模式声明 `supports_mask: true`。

## 异步任务与失败续做

适配器的三个接口为 `submit(request, project_root)`、`poll(job)`、`fetch(result, output_dir)`。图像同步结果也保留同样的结果结构。运行器负责把任务 ID、路由快照、规范化结果和下载文件持久化；适配器负责转换协议，不自行编排镜头。

首次解析路由时冻结实际公司 Base URL，并保留 `auth.env` 等密钥引用。恢复任务使用原路由快照、原模型和协议版本查询，不会因为后来改了 Base URL 环境变量就查到另一个接口。认证仍从当前环境读取，便于更换到期密钥。已有任务 ID 时，查询/下载失败可以续做；不会重新提交生成。

如果 POST 超时、返回无法识别的内容或存在其他无法确认是否受理的情况，返回 `submission_unknown`，不自动重发 POST。若成功拿到任务 ID，而可选状态字段暂时无法识别，先返回并保存这个任务句柄，以便后续查询。Ark 与 New API 返回的可选末帧是额外图片产物（role `last_frame`），视频候选选择仍以视频产物为主。New API 的统一查询不含末帧；请求 `return_last_frame` 时，适配器在任务完成后另查原厂任务记录的 `content.last_frame_url`，取不到时记一条观察，视频照常完成。

`fetch` 保存所有候选，保留可选的末帧角色信息；下载不会把 HTML 错误页面当成 MP4。适配层检查文件标识，完整媒体时长和可解码性由后续本地媒体探测检查。媒体 URL 可能过期；已有远端任务可重新查询取得当前结果，若公司查询也不再返回资源，则需要公司提供恢复方式。

## 错误记录

HTTP 传输失败、图像和统一视频业务错误会附带 `details.diagnostic`。它分别保存错误类别、提交结果、请求 ID、响应声明的来源层级、脱敏错误正文、Retry-After 与处理建议。HTTP 200 中的 error 或 New API code/message 业务拒绝也会识别。

404 归类为 resource_not_found；只有响应明确给出 model_not_found 等错误码时才归类为模型不可用。upstream_error 只表示网关报告来自上游，具体根因仍需网关日志确认。POST 超时、5xx 或异常响应保留提交结果不明状态；已有任务 ID 的视频继续原任务。原有运行错误码保持兼容，细分判断读取 diagnostic。

诊断只保存选定的错误字段和响应头，清理凭据、认证值、带访问参数的 URL 与长媒体内容。历史未保存的正文或请求 ID 无法补回。

## 验证范围与依据

协议测试使用本地 mock 传输和固定响应，覆盖请求字段、多图顺序、首尾帧、异步状态、恢复地址约束、无自动 POST 重试、跨域认证隔离、失败下载续做等。真实服务连通性在目标环境另行验证；CPA 与 UniAPI 样例路由的付费实测结果记在各路由的 `capabilities.evidence`，未列出的参数组合未单独实测。

协议实现参考下列原厂公开文档，仅作为**已命名协议的请求/响应结构依据**。公司路由是否兼容、支持哪些模式和取值，需要公司资料或实际接通结果确认。

- [OpenAI Images 编辑接口](https://developers.openai.com/api/reference/resources/images/methods/edit)
- [Google Gemini Veo 视频生成 REST 示例](https://ai.google.dev/gemini-api/docs/veo)
- [火山方舟创建视频生成任务](https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh)
- [火山方舟查询视频生成任务](https://www.volcengine.com/docs/ark/get-video-generation-task-api)
