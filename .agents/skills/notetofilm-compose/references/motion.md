# 参数化图层动效

`ntf motion` 将图层、关键帧、遮罩和路径展开渲染为无声视频素材，并登记到项目。它使用现有 Pillow 与 FFmpeg；声音、字幕与完整成片继续由 compose 处理。

## 调用与采用

```bash
ntf motion PROJECT --manifest MOTION.json --plan-only
ntf motion PROJECT --manifest MOTION.json --scene s01 --preview-only --preview-time 1.5
ntf motion PROJECT --manifest MOTION.json
```

`--scene` 可重复，使用固定 ID。预览输出最长边不超过 960 的 JPEG；`--plan-only` 不生成媒体或改变采用关系。正式输出默认采用到 `motion.<scene_id>`，可用 `--select-prefix` 指定另一前缀。合成清单引用例如 `{"selection":"motion.s01"}`。

相同有效输入、源文件、字体和渲染代码会复用已有素材；`--force` 生成新版本并保留旧文件。修改已登记源文件后应重新导入；不能用原素材 ID 冒充新内容。

## 清单示例

下面是图层字段示例，文字与关系须替换为实际材料。字体路径使用项目内字体或现有本机字体，不随通用技能分发。

```json
{
  "schema_version": 1,
  "output": {"width":1280,"height":720,"fps":24},
  "font_file": "assets/fonts/your-font.ttf",
  "scenes": [{
    "id":"s01", "duration_seconds":4, "background":"#f3f3f3",
    "layers":[
      {"type":"draw","objects":[
        {"type":"text","text":"比较实际约束","xy":[80,70],"size":48},
        {"type":"arrow","points":[[120,400],[1050,400]],"width":6,
         "reveal_start":0.5,"reveal_end":2.5}
      ]},
      {"type":"draw","start":0.5,"end":4,"fade_in":0.2,
       "objects":[{"type":"rect","box":[120,300,200,360],"fill":"#9d3939"}],
       "keyframes":[{"t":0.5,"offset":[0,0]},
                    {"t":2.5,"offset":[700,0],"ease":"ease_out"}]}
    ]
  }]
}
```

旧实验清单的顶层 `width/height/fps` 与镜内 `duration` 仍可读取；新清单采用 `output` 和 `duration_seconds`。图层时间和关键帧的 `t` 均从本镜起点计算。

## 图层与坐标

| 内容 | 参数与含义 |
|---|---|
| 图片、视频 | `type: image/video`，用项目内 `path`、`asset_id` 或 `selection` 引用实际媒体 |
| 目标区域 | `rect: [x,y,width,height]`，坐标属于输出画布 |
| 源图裁切 | `crop: [left,top,right,bottom]`，坐标属于实际源媒体；先探测实际宽高 |
| 可动画属性 | 关键帧支持 `rect`、`crop`、`offset: [x,y]` 和 `opacity: 0..1`；同一属性的时间严格递增 |
| 插值 | `linear`、`smooth` / `ease_in_out`、`ease_out`；一段插值使用结束关键帧的 ease |
| 进出场 | `start/end` 控制可见窗口，`fade_in/fade_out` 控制淡入淡出秒数 |
| 裁切视点 | `zoom_start` 为初始倍率，`zoom` 为镜内增量，`focus/centering` 使用 0..1 的位置比例 |
| 遮罩展开 | `reveal` 包含 start/end、画布坐标 box、right/left/down/up 方向及 ease |
| 视频时间 | `trim_start` 与数值 `speed`，采用区间须覆盖图层窗口；这里不自动循环或冻结尾帧 |
| 绘图对象 | `rect`、`gradient`、`line`、`arrow`、`text`；线/箭头用 reveal_start/reveal_end 控制路径展开 |

`motion` 的视频层会去掉声音，适合先制作视觉素材。需要保留原声及其变速时，用合成清单中的视频视觉项和 `audio_policy`。

## 净画面与配字分开

```bash
ntf motion PROJECT --manifest MOTION.json --stage picture --select-prefix motion
ntf motion PROJECT --manifest MOTION.json --stage annotate --select-prefix motion
```

picture 输出图片和视频图层，采用到 `motion.<id>.picture`。annotate 使用该已采用净画面，再加入 draw 图层，采用到 `motion.<id>`；两步使用相同的前缀与镜头 ID。改字或图解后只跑 annotate，净画面继续复用。只有图解的镜头可直接使用默认 all。

动效参数服务导演给出的信息顺序或事件变化。渲染后检查实际 JPEG 和关键动作连续播放，尤其是遮罩方向、裁切边界、文字可读性及技术关系。
