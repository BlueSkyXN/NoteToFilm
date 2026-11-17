# 第三方参考与许可

本项目在开发中参考了以下项目。下表列出的位置包含从这些项目复用或改编的代码和文本，**这些复用的代码和文本遵循原作者的许可协议**；其余内容由本项目编写，以 GPL-3.0-or-later 发布（见 `LICENSE`）。

## garden-skills

- 来源：<https://github.com/ConardLi/garden-skills>，提交 `9578a34edf3c359da23d8a632b72790834961d11`，`skills/motion-showreel`
- 协议：MIT License（原作者许可文本见本节末尾）

| 本仓库位置 | 复用或改编的内容 |
|---|---|
| `.agents/skills/notetofilm-compose/assets/code-animation/motion.js` | 时间驱动辅助函数（缓动、弹簧、噪声、混色、相机、2.5D 体块）；文件末尾的讲解图形函数为本项目编写 |
| `.agents/skills/notetofilm-compose/references/code-recipes.md` | references/recipes.md 的写法与代码，替换为本项目的命令与时间来源 |
| `.agents/skills/notetofilm-compose/references/motion-craft.md` | references/craft.md，以及 references/review.md 的审片项与常见问题 |
| `.agents/skills/notetofilm-direct/references/styles/` 中的七个风格文件 | 风格库对应文件的主体；「在 NoteToFilm 中制作」与声音一节为本项目改写 |
| `runtime/notetofilm_local/data/text_hook.js` | scripts/lib/text-hook.mjs 的页面内文字位置记录 |
| `runtime/notetofilm_local/web_render.py` | `render(t)` 页面约定、浏览器启动参数、确定性比对、子帧平均、超采样与颗粒的做法（以 Python 与 FFmpeg 重写） |

## 只参考思路，未复用代码和文本

| 项目 | 协议 | 参考的思路 |
|---|---|---|
| garden-skills 的 web-video-presentation、web-design-engineer 等技能 | MIT | 口播与画面分工、信息逐步揭示、设计工作方法 |
| video-agent-kit（Z.ai） | MIT | 按时间抽帧的联系表与局部复看、冻结/黑场/静音检测、中文分词断行、配音回听 |

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
