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
- `motion.js`：只由时间决定的辅助函数。缓动与 `snap`、`glide` 曲线，闭式弹簧 `spring`、`springTo`，`tween`、`stagger`，固定种子的 `rng`、`noise1`、`noise2`，OKLab 混色 `mix`，2D 相机 `camera`，2.5D 的 `camera3d` 与 `drawBoxes`；讲解图形有 `drawPath`（路径绘出）、`reveal`（遮罩显露）、`wrapText`（中文按标点规则换行）、`typeOn`、`countUp`（固定小数与单位的数字变化），让 CSS 动画停在指定时刻的 `scrubAnimations`，以及节拍换算 `beats` 与转场对拍的 `revealOn`。

怎么动得好看——运动质感、转场语法、镜头、动态排版、配色、质感层、签名时刻和 AI 默认味——读 [代码动画手法库](motion-craft.md)；现成的写法（遮罩逐字、前后沿拉伸、形状变形链、穿越转场、遮罩擦除、粒子组字、计数器、无缝循环、WebGL 后期、伪 3D 体块等）读 [代码动画写法](code-recipes.md)。

## 按时间绘制

`window.render(t)` 给定秒数，画出该时刻的完整画面。静帧检查、拖动预览和逐帧导出由此得到同一画面。

- 位置、透明度和形变由 `t` 计算，不依赖实时时钟、`requestAnimationFrame` 或上一帧的累积结果。
- 随机效果使用固定种子；粒子或物理模拟用固定步长预先算好。
- 字体、图片等资源在 `window.READY = true` 之前加载完成；需要跨机器一致时，把字体文件放进页面目录。
- DOM 页面里的 CSS 动画在 `render(t)` 开头调用 `scrubAnimations(t)`，让它们停在对应时刻。
- 画幅和帧率由命令传入（`?w=&h=&fps=`），版面按画幅等比计算。
- 字和繁忙的画面（体块、粒子、阵列）同屏时，先给字划一块禁入区，让主体避开；故意被遮挡的字，被挡部分不超过一个字。

## 时间来自项目

先取得配音和 `ntf timing` 结果，再把 `timing.js` 里的关键变化放到对应秒数；旁白改动后同步更新。段落卡写的开始状态、主要变化和完成状态，就是动画要依次画出的内容。

参与动画的标签和图解文字在页面源码里维护；不随动画变化的标题和旁白字幕继续用合成清单的 `text_overlays` 和字幕。同一段文字只在一处维护。数字和准确文字注明材料中的事实编号。

## 预览、渲染与接入

1. 静帧预览：`ntf web-render PROJECT --page animation/s02 --scene s02 --preview-time 1 --preview-time 3.5 --text-check`。输出各时刻的 PNG，并在另一页面按不同顺序重画同样的时刻做比对；`deterministic` 为 false 时，按 `nondeterministic` 给出的时刻查找跨帧状态、随机数、实时时钟或晚到的资源。`--text-check` 记录 Canvas 与 DOM/SVG 文字的位置，报告出界（CUT，展示级大字出血记为 BLEED）、两段文字重叠（OVERLAP）和字过小（TINY），并输出标好框的图；WebGL 纹理和图片里的字看不到，要自己看。
2. 渲染：去掉 `--preview-time`，按项目画幅和帧率逐帧截图并编码为无声视频，登记后采用到 `web.<scene>`（`--select` 可改）。时长默认读页面的 `window.DUR`，也可用 `--duration` 指定。页面目录内的文件和渲染参数不变时复用已有素材，`--force` 另生成新版本。
   质感参数：`--dpr 2` 超采样后缩回项目画幅，细线和小字更干净，渲染约慢 3 倍；`--subframes 4` 每帧平均 4 个子帧得到运动模糊（`--shutter` 调快门比例，默认 0.5），渲染时间乘以子帧数；`--grain 4–8` 在编码时叠加随时间变化的颗粒，不在页面里逐帧画噪点；颗粒会让文件大幅变大，使用前看 [motion-craft.md](motion-craft.md) 第 9 节。
3. 合成清单按 `{"selection": "web.s02"}` 引用。
4. 用 `ntf sheet` 检查关键变化的时点，以及文字是否裁切或重叠。
