# 第三方参考与许可

NoteToFilm 自有内容以 GPL-3.0-or-later 发布，见 [LICENSE](LICENSE)。随项目分发的第三方代码、文本及其改编保留原作者许可，下表列出对应文件。仅用于设计对照的来源列在“只参考思路”一节。

## garden-skills

- 来源：<https://github.com/ConardLi/garden-skills>，提交 `9578a34edf3c359da23d8a632b72790834961d11`，`skills/motion-showreel`；表中标注“2b9a893”的条目来自提交 `2b9a89340b70f632d31c0f1c69fce94a7912423e`
- 协议：MIT License（原作者许可文本见本节末尾）

| 本仓库位置 | 复用或改编的内容 |
|---|---|
| `.agents/skills/notetofilm-compose/assets/code-animation/motion.js` | 时间驱动辅助函数（缓动、弹簧、噪声、混色、相机、2.5D 体块）；文件末尾的讲解图形函数为本项目编写 |
| `.agents/skills/notetofilm-compose/references/code-recipes.md` | references/recipes.md 的写法与代码，替换为本项目的命令与时间来源 |
| `.agents/skills/notetofilm-compose/references/motion-craft.md` | references/craft.md，以及 references/review.md 的审片项与常见问题 |
| `.agents/skills/notetofilm-direct/references/styles/` 中的 blueprint、copperplate-engraving、data-motion、editorial-collage、isometric-infographic、swiss-editorial、whiteboard-explainer 七个风格文件 | 风格库对应文件的主体；「在 NoteToFilm 中制作」与声音一节为本项目改写 |
| `.agents/skills/notetofilm-direct/references/styles/INDEX.md`、`.agents/skills/notetofilm-direct/assets/style-recipe.template.md` | references/styles/INDEX.md 的用法、三个方向与混搭规则，SKILL.md 第 3 步“已定风格先出三帧”，以及 styles/_template.md 的栏目结构 |
| `.agents/skills/notetofilm-direct/assets/design-brief.template.md` 的设计摘要 | references/brief-template.md 中 Reel Read 的字段结构（对标、候选结构、辨识信号、开头、记忆点、声音、禁止项） |
| `.agents/skills/notetofilm-direct/references/sound-design.md` | references/sound.md 的声音方向、戏剧曲线菜单与声音默认味，改写为讲解片的四层声音 |
| `.agents/skills/notetofilm-compose/references/sound-mix.md` 的时间规则 | references/sound.md 的时间规则（转场声最响处对准切点、声音先行与延续）；音效命令与预混脚本为本项目编写 |
| `.agents/skills/notetofilm-compose/references/delivery.md` 的审片记录与独立审片 | references/review.md 的审片记录格式与独立审片做法 |
| `.agents/skills/notetofilm-direct/references/formats.md` 的“数据爆点”“片头、落版与金句” | references/formats.md 中 D、E、G 三类用途的结构与坑 |
| `runtime/notetofilm_local/data/text_hook.js` | scripts/lib/text-hook.mjs 的页面内文字位置记录 |
| `runtime/notetofilm_local/web_render.py` | `render(t)` 页面约定、浏览器启动参数、确定性比对、子帧平均、超采样与颗粒的做法（以 Python 与 FFmpeg 重写） |
| `runtime/notetofilm_local/synth.py`（2b9a893） | scripts/lib/synth.mjs 的乐器配方、和弦与音阶表、session 接口（节奏、总线、侧链、共享混响）与 Freeverb 调音，以 Python 标准库与 FFmpeg 重写 |
| `runtime/notetofilm_local/inspection.py` 的倍频程平衡、重拍前凹陷与有意停留（2b9a893） | scripts/audio.mjs check 的倍频程能量、drop 呼吸量与提示阈值，scripts/inspect.mjs 的 HOLDS 判定（前后放宽 0.35 秒），以 FFmpeg 测量重写 |
| `.agents/skills/notetofilm-direct/references/styles/` 中的 minimal-ui、terminal-ascii、one-line、particle-field 四个风格文件（2b9a893） | 风格库对应文件的主体；声音一节改写为 `ntf score`，补充「在 NoteToFilm 中制作」与本项目实验中的做法 |
| `.agents/skills/notetofilm-compose/references/sound-mix.md` 的“代码合成配乐”（2b9a893） | references/sound.md 第 1 档内置合成的接口说明、低频控制、侧链与混音建议、检查方法和声音默认味 |

## 只参考思路，未复用代码和文本

| 来源 | 上游协议 | 参考的思路及本项目的用法 |
|---|---|---|
| [OpenMotion · Motion.md 设计说明](https://github.com/nexu-io/openmotion/blob/19e492000238eaed6cc304156c5051e936369fc1/docs/motion-md.md) | Apache-2.0 | 把一段参考片看成一连串观看动作：观众先注意什么，什么时候发现变化，哪一声使结果落定。NoteToFilm 在[导演备稿](.agents/skills/notetofilm-direct/assets/design-brief.template.md)中用自己的材料重排这些时刻，再写入正式分镜。 |
| [HyperFrames · 可按时间定位的动画](https://github.com/heygen-com/hyperframes/blob/765883195eb0a40c1062715879270e55f9074a67/README.md#how-it-works) | Apache-2.0 | 把镜头定位到同一时刻，就能复查一个动作的前后状态。NoteToFilm 的[因果草图](.agents/skills/notetofilm-direct/references/shot-studies.md)用项目自己的 Pillow 脚本逐帧绘制。实际制片沿用镜号、素材和合成时间表。 |
| [garden-skills](https://github.com/ConardLi/garden-skills/tree/9578a34edf3c359da23d8a632b72790834961d11/skills) 的 web-video-presentation、web-design-engineer 等技能 | MIT | 口播与画面分工、信息逐步揭示、设计工作方法 |
| Z.ai 的 ZCode 官方插件 `video-agent-kit` 0.4.3，见随包 README 的 `video_watch_segment`、`qc_preview` | MIT | 按时间抽帧的联系表与局部复看、冻结/黑场/静音检测、中文分词断行、配音回听。NoteToFilm 用 `ntf sheet` 定位剪点，用 `ntf inspect --scan` 找到停留，再由剪辑者判断是否需要收短。 |

## garden-skills 许可文本

```text
MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
