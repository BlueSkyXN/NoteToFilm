# 代码动画素材

`ntf motion` 用参数清单制作图层动效，适合图片、视频、简单图形和文字。画面需要更自由的形变、连续的对象运动、大段文字排版、数据图形或简单立体结构时，由 Agent 写一个按时间绘制的网页（Canvas、SVG、DOM，确有需要时 WebGL），用 `ntf web-render` 逐帧渲染成项目视频素材。

## 先判断用哪种方式

| 画面任务 | 合适的方式 |
|---|---|
| 关系、流程、数据、并行工作、汇表、动态排版，需要准确又连续的变化 | 代码动画收益最大 |
| 图片分层显露、遮罩、路径展开、裁切推近 | `ntf motion` 已能表达，清单更容易复用和修改 |
| 写实人物、手部动作、实拍质感 | 图片或视频生成，或已有素材 |

`ntf web-render` 需要运行环境装有 Playwright（web 可选依赖），并能找到 Chromium 或本机 Google Chrome。`ntf install-info` 的 `web_rendering` 显示是否可用；缺少时先说明用途并取得同意再安装。

## 从骨架开始

把骨架目录 `assets/code-animation/`（入口 [index.html](../assets/code-animation/index.html)）整个复制到项目内，例如 `animation/<scene_id>/`：

- `index.html`：示例页面，演示同位对照——固定基准与尺度，让差异成为唯一变化。替换内容、数值和样式，保留 `window.render`、`window.DUR` 和 `window.READY` 的写法。
- `timing.js`：本镜唯一的时间来源，写本镜时长和段落卡里的关键变化时点。
- `kit.js`：设计坐标与基本绘制。短边按 720 设计（16:9 是 1280×720，9:16 是 720×1280），每帧先调用 `base(底色)`，之后直接写设计像素；`DW`、`DH` 是当前画幅的设计宽高。`text`、`wipeText`（遮罩显露）、`riseText`（从基线弹上）、`box` 的透明度都与外层相乘，整组淡出用 `faded(a, () => …)` 包住；形变途中的乱码字符、拉远后当纹理用的小字放进 `decorative(() => …)`，文字检查不记录。
- `motion.js`：只由时间决定的辅助函数。缓动与 `snap`、`glide` 曲线，闭式弹簧 `spring`、`springTo`，`tween`、`stagger`，固定种子的 `rng`、`noise1`、`noise2`，OKLab 混色 `mix`，2D 相机 `camera`，2.5D 的 `camera3d` 与 `drawBoxes`；讲解图形有 `drawPath`（路径绘出）、`reveal`（遮罩显露）、`wrapText`（中文按标点规则换行）、`typeOn`、`countUp`（固定小数与单位的数字变化），让 CSS 动画停在指定时刻的 `scrubAnimations`，以及节拍换算 `beats` 与转场对拍的 `revealOn`。

怎么动得好看——运动质感、转场语法、镜头、动态排版、配色、质感层、签名时刻和 AI 默认味——读 [代码动画手法库](motion-craft.md)；现成的写法（遮罩逐字、前后沿拉伸、形状变形链、穿越转场、遮罩擦除、粒子组字、计数器、无缝循环、WebGL 后期、伪 3D 体块等）读 [代码动画写法](code-recipes.md)。

## 按时间绘制

`window.render(t)` 给定秒数，画出该时刻的完整画面。静帧检查、拖动预览和逐帧导出由此得到同一画面。

- 位置、透明度和形变由 `t` 计算，不依赖实时时钟、`requestAnimationFrame` 或上一帧的累积结果。
- 随机效果使用固定种子；粒子或物理模拟用固定步长预先算好。
- 入口在提供 `window.render` 前同步写入 `window.READY = false`，字体、图片和预处理（如把照片转成网点、生成纸纹）全部完成后再设为 `true`。`web-render` 读取当前页面的就绪状态。入口省略 READY 时，render 可用即可截图。需要跨机器一致时，把字体文件放进页面目录。
- DOM 页面里的 CSS 动画在 `render(t)` 开头调用 `scrubAnimations(t)`，让它们停在对应时刻。
- 画幅和帧率由命令传入（`?w=&h=&fps=`），版面按画幅等比计算。
- 字和繁忙的画面（体块、粒子、阵列）同屏时，先给字划一块禁入区，让主体避开；故意被遮挡的字，被挡部分不超过一个字。
- 画面里只放承载内容的字：对象名称、对比标签、结论。图号、版本、“示意”、修订号之类的元标签不画；底部留出字幕区。
- 绘制函数自己设置透明度时（`globalAlpha = alpha`），会覆盖外层的淡出。用 `kit.js` 的绘制函数，或自己写成 `globalAlpha *= alpha`。
- `destination-out`、`destination-in` 作用于画布上已经画好的全部内容：在主画布上挖洞，会把底下的背景一起挖穿。只想处理某一层时（印章的斑驳、文字窗口），先画到离屏画布，处理完再贴回。

## 时间来自项目

先取得配音和 `ntf timing` 结果，再把 `timing.js` 里的关键变化放到对应秒数；旁白改动后同步更新。整片一个页面、字要落在说到它的那个词上时，用 `ntf timing PROJECT --apply --js animation/<页面>/film-timing.js` 导出镜头窗口和逐词时间，页面里写 `W('s05', '通知')`，不手填秒数（示例见骨架的 `film-timing.js`）。段落卡写的开始状态、主要变化和完成状态，就是动画要依次画出的内容。

参与动画的标签和图解文字在页面源码里维护；不随动画变化的标题和旁白字幕继续用合成清单的 `text_overlays` 和字幕。同一段文字只在一处维护。数字和准确文字注明材料中的事实编号。

## 衔接相邻镜头

- 后一页的 t=0 应等于前一页的末帧：共用同一份绘制函数（把前一页的模块复制进本页目录导入），或把前一页末帧静帧放进本页目录作为起点，再让元素收起、移动或淡出。用 `ntf compare 前一页末帧.png 本页首帧.png --output DIR` 并排核对。
- 生成的视频片段要和代码图形同屏（叠字、压暗、遮挡、与图形接力）时，用 `ntf frames` 把采用的片段抽成帧序列放进页面目录，页面用骨架的 `clips.js` 取帧，做法见下一节。片段比本镜短时停在末帧，用缓慢推近接住。
- 页面里陈列已有成片时，每段按它从入画到退场的时长抽帧，免得循环或停帧。要遮去烧录字幕，可以用 `drawImage` 裁出字幕以上的部分，按原片背景色补齐下方，再用导出帧检查填色处有无色带。并排对照两种讲法时，可以保留体现差异的原文，去掉与本片旁白字幕重复的标题。
- 从视频切进图解时，用上一镜的尾帧（`return_last_frame` 或工具箱“取最后一帧”）作位置参考，让图解里的对象落在视频对象的位置上，再展开解释；用 `ntf compare clip.mp4@末帧秒数 preview.png --overlay --output DIR` 叠合核对。
- 一段连续动画跨两段旁白时，渲染成一个页面，在合成清单两镜里分别用 `duration_seconds` 和 `trim_start` 引用它的前后两段。

## 视频片段加代码动画

人物和物件的动作来自生成视频，准确的字、标注、图解和整屏转场由代码画，整片写成一个页面。骨架里的 [hybrid.html](../assets/code-animation/hybrid.html) 和 [hybrid.js](../assets/code-animation/hybrid.js) 是一个四镜示例：推车上的包裹、横甩到货架、往下穿进图解、取件单掠过后接顾客取件。

1. **时间**：配音后 `ntf timing PROJECT --apply --js animation/film/film-timing.js`。字和动作写在 `W('镜头', '词')` 上。
2. **片段**：生成并选好片段后，`ntf frames PROJECT --select s05.video --output animation/film/media/s05`，把返回的 `frames`、`fps` 填进 `clipLibrary`。帧按需加载、最近用过的留在缓存里，片段多也不会撑满内存；取不到的帧会让渲染停下，片段到齐再渲。
3. **镜头表**：`SHOTS` 是 `[开始秒, 绘制函数]`，`render(t, frame)` 里用 `shotAt(SHOTS, t, frame)` 选镜头。它按 `frame.time` 选，开 `--subframes` 时硬切处不混帧。
4. **叠字对齐素材**：`clips.play()` 返回这一帧的取景，`overlay(取景, () => …)` 里按素材像素画，字贴在素材里的东西上、随推拉一起动。坐标先在原尺寸帧上画网格量出来；只对机位固定的片段直接成立，镜头在动的片段量几个关键帧再插值，或换固定机位的片段。
5. **转场**：[transitions.js](../assets/code-animation/transitions.js) 的 `whipPan`（横甩，约 0.24 秒）、`pushThrough`（上下穿越，约 0.34 秒）、`wipeBy`（遮挡物掠过，约 0.6 秒）。转场写成跨过剪点的一段，上一镜和下一镜用同一个 `across(t, 剪点, 时长)` 进度；一支片子挑两三种。
6. **渲染**：`ntf web-render PROJECT --page animation/film/hybrid.html --scene film --subframes 4`，快速移动有真实的运动模糊。先 `--preview-time` 看转场中段和叠字。
7. **检查**：`ntf sheet FILM --start 剪点前 --end 剪点后 --fps 8` 逐帧看转场（不留空白帧、不混帧、遮挡物认得出），`ntf inspect FILM --scan` 看 `low_motion` 和 `pace`。

不花钱先试一遍模板：用 FFmpeg 做三段占位片段，导入并抽帧，再渲示例页面。

```bash
ffmpeg -f lavfi -i "color=c=0x8C8F92:s=1280x720:r=24:d=4" -vf "drawbox=x=550:y=370:w=180:h=140:color=0xD9822B:t=fill" -pix_fmt yuv420p cart.mp4
ffmpeg -f lavfi -i "color=c=0x6E7377:s=1280x720:r=24:d=4" -vf "drawgrid=w=160:h=120:t=4:c=0x3B3F43,drawbox=x='1150-min(t\,1.5)*240':y=250:w=140:h=100:color=0xD9822B:t=fill" -pix_fmt yuv420p shelf.mp4
ffmpeg -f lavfi -i "testsrc2=s=1280x720:r=24:d=4" -pix_fmt yuv420p pickup.mp4
for c in cart shelf pickup; do
  ntf import PROJECT $c.mp4 --kind video --select $c.video
  ntf frames PROJECT --select $c.video --output animation/demo/media/$c
done
# 把骨架目录复制到 PROJECT/animation/demo/ 后：
ntf web-render PROJECT --page animation/demo/hybrid.html --scene demo --subframes 4
```

## 几个方向一起做

方向样片可以放在同一个项目里：每个方向一个页面目录（例如 `animation/dirs/<方向>/`），渲染时 `--select web.<方向>`，每个方向一份合成清单，配乐或底声导入成不同的采用位。几个页面共用的绘制代码放在 `animation/dirs/lib/`，用相对路径导入：`web-render` 以项目根目录为站点根，页面目录外的项目文件也能加载。复用判断只看页面目录里的文件，改了共用代码后渲染要加 `--force`。

比较画风时，各方向共用一份动作编排（同一个时间表和对象状态），只换画法，差异才落在画风上；比较手法或结构时各自编排。做完用 `ntf compare A.mp4 B.mp4 C.mp4 --at 开场秒数 --at 记忆点秒数 --at 落版秒数 --output DIR` 排成对比表。

## 一镜到底的长片

讲解片常用一个世界坐标、一镜到底：任务标记沿一张线路图或流程图走，最后拉远成全景。片子变长时，新段落接在全景之后、结尾之前，用同一张图当舞台：点亮相关节点、连线、分叉，讲完退场。几条容易漏掉的细节：

- **按缩放后的大小定字号。** 文字检查按成片像素算，下限是画高的 2.5%（1080p 约 27px）。镜头拉远到 0.88 倍时，全图上的说明卡要用至少约 32 的设计字号；先算“设计字号 × 镜头缩放”，再写卡片。
- **框和内容一起出现。** 卡片框先弹出、内容等到下一句才出，会留下空框；让框随第一项内容出现。一镜开头旁白已经开始、第一个元素却要等几秒，先放和这句话相关的东西（主语、一条开始生长的线），不要留一页空纸。
- **高亮跟着当前这句话。** 上一句点亮的名称在下一句开始前熄灭；同一时刻画面上几处高亮应该指向同一件事。聚焦某几个节点时，其余节点、包括早先加了信号色底的标签一起变淡。
- **引线绕开文字。** 连线、反馈线从字的上方或侧面出发，不穿过站名和标签；文字检查不报线压字，要看静帧。新元素先找空区，挤在已有元素之间会和它们重叠。
- **整页要不透明。** 中途换成一整页讲别的内容时，用不透明纸面盖住，铺满期间不画底下的世界；半透明的页会透出底图，文字检查也会把底下的字算进重叠。全片用了镜头呼吸时，整页也给同样幅度的匀速推近，让镜头语言前后一致；信息变化仍然要靠页面里的对象。
- **推近后检查字幕区。** 在推近的关键帧看表格末行、标签缩放后的屏幕位置。进了字幕区，就下移镜头中心，或在推近期间隐藏这一层。`--text-check` 能在指定预览时刻提示页面上可识别的文字框重叠。原片自带的字、合成时叠加的字幕，以及图形是否遮字，要在最终成片对应的时刻看。
- **细线生长会被报成冻结。** 一条线慢慢长出来、小卡片轻微弹动，像素变化低于扫描阈值。扫描报冻结时，截两帧量像素差或看连续帧，再判断是空等还是慢变化。

大改之前，把页面、旁白、时间锚点和配乐脚本复制一份快照（例如 `snap-v7/`），旧版成片等用户确认后再清理，回退时能原样重出。

## 预览、渲染与接入

1. 静帧预览：`ntf web-render PROJECT --page animation/s02 --scene s02 --preview-time 1 --preview-time 3.5 --text-check`。预览时刻须在页面时长以内。输出各时刻的 PNG，并在另一页面按不同顺序重画同样的时刻做比对；`deterministic` 为 false 时，按 `nondeterministic` 给出的时刻查找跨帧状态、随机数、实时时钟或晚到的资源。`--text-check` 记录 Canvas 与 DOM/SVG 文字的位置，报告出界（CUT，展示级大字出血记为 BLEED）、两段文字重叠（OVERLAP）和字过小（TINY，下限为画高的 2.5%，720p 约 18px，次要标注也按此），并输出标好框的图；WebGL 纹理和图片里的字看不到，要自己看。
2. 渲染：去掉 `--preview-time`，逐帧调用 `render(t, frame)`（`frame.time` 是这一帧的名义时刻），按项目画幅和帧率截图并编码为无声视频，登记后采用到 `web.<scene>`（`--select` 可改）。时长默认读页面的 `window.DUR`，也可用 `--duration` 指定。页面目录内的文件和渲染参数不变时复用已有素材，`--force` 另生成新版本。
   质感参数：`--dpr 2` 超采样后缩回项目画幅，细线和小字更干净，渲染约慢 3 倍；`--subframes 4` 每帧平均 4 个子帧得到运动模糊（`--shutter` 调快门比例，默认 0.5），渲染时间乘以子帧数；`--grain 4–8` 在编码时叠加随时间变化的颗粒，不在页面里逐帧画噪点；颗粒会让文件大幅变大，使用前看 [motion-craft.md](motion-craft.md) 第 9 节。
3. 合成清单按 `{"selection": "web.s02"}` 引用。
4. 用 `ntf sheet` 检查关键变化的时点，以及文字是否裁切或重叠。

文字检查和 `ntf inspect --scan` 给的是线索，逐条判断，不以清零为目标：

- 有意的停留（落版、读字、静态证据）也会被报成冻结。在段落卡或 `timing.js` 里写下有意停留的区间，扫描时用 `--hold 开始-结束` 声明，落在其中的冻结标为 `intended`；其余冻结逐条判断，空等就改那几拍的对象动作或删短，不靠加推镜、漂移、光点消掉报告。
- 黑场条目的 `has_content` 为 true 时，是深色底上有字或图形，看原帧确认即可，不必为此提亮底色。
- 文字检查不报整段在画外的字；乱码字符和纹理小字用 `decorative()` 包住后不再刷屏。剩下的出界、重叠、过小逐条看，`counts` 先看各类有多少。
