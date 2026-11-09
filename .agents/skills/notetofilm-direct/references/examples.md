# 正式分镜示例

以下两镜展示准确图解与文生场景的字段写法，内容仅用于说明格式。制作路线和画风在导演备稿中选择，执行参数使用现有字段。

```json
{
  "schema_version": 1,
  "scenes": [{
    "id": "s01",
    "narration": "<填写第一镜旁白>",
    "screen_text": "<填写第一镜屏幕文字>",
    "visual_prompt": "<填写第一镜画面要求>",
    "visual_type": "still",
    "audio_policy": "edge_tts"
  }, {
    "id":"s02",
    "narration":"<填写第二镜旁白>",
    "screen_text":"<填写第二镜屏幕文字>",
    "visual_prompt":"<填写第二镜画面要求>",
    "visual_type":"video",
    "video_mode":"text_to_video",
    "video_prompt":"<填写第二镜动作和视觉要求>",
    "audio_policy":"edge_tts"
  }]
}
```

保存草稿后执行 `ntf storyboard PROJECT --file FILE`。自动工作流继续 `ntf plan PROJECT`；独立候选路线按已选素材编写合成清单。实际路由、参数与素材引用按项目配置填写，示例不证明通道已联通。

用户说“第三镜”时先按当前顺序找到其固定 ID；插镜后不重命名其他镜头。改成“并行制作”时，除了旁白，原流程箭头的关系可能也要调整。
