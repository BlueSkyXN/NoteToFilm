// kit.js — 设计坐标和基本绘制。短边按 720 设计：16:9 画幅是 1280×720，9:16 是 720×1280。
// 每帧先调用 base()，之后直接写设计像素，不用逐个乘缩放系数；DW、DH 是当前画幅的设计宽高。
// 这里的绘制函数都把透明度与外层相乘：外面整组淡出时，里面的字和形状一起变淡。
import { clamp, snap, renderInfo, setupCanvas } from './motion.js';

export const { W, H } = renderInfo();
export const ctx = setupCanvas(document.getElementById('c'), W, H);
export const U = Math.min(W, H) / 720, DW = W / U, DH = H / U;
const DPR = window.devicePixelRatio || 1;

// 字体族。需要跨机器一致时，把字体文件放进页面目录，在 index.html 用 @font-face 声明，再改这里。
export const FONTS = {
  sans: '"PingFang SC", "Noto Sans CJK SC", "Source Han Sans SC", sans-serif',
  mono: '"SF Mono", "JetBrains Mono", Menlo, monospace',
};
export const font = (size, weight = 500, family = 'sans') => `${weight} ${size}px ${FONTS[family] ?? family}`;

/** 每帧开头调用：回到设计坐标、不透明、正常混合；给了底色就铺满画面。 */
export function base(background) {
  ctx.setTransform(DPR * U, 0, 0, DPR * U, 0, 0);
  ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over'; ctx.filter = 'none';
  if (background) { ctx.fillStyle = background; ctx.fillRect(0, 0, DW, DH); }
}

/** 在外层透明度上再乘 a 执行 draw。整组淡出时用它包住整组。 */
export function faded(a, draw) {
  if (!(a > 0)) return;
  ctx.save(); ctx.globalAlpha *= clamp(a); draw(); ctx.restore();
}

export function measure(s, size, weight = 500, family = 'sans') {
  ctx.save(); ctx.font = font(size, weight, family); const w = ctx.measureText(s).width; ctx.restore(); return w;
}

export function text(s, x, y, size, { weight = 500, color = '#1E2328', align = 'left', baseline = 'alphabetic', family = 'sans', alpha = 1 } = {}) {
  faded(alpha, () => {
    ctx.font = font(size, weight, family); ctx.fillStyle = color; ctx.textAlign = align; ctx.textBaseline = baseline;
    ctx.fillText(s, x, y);
  });
}

/** 遮罩从左向右显露一行字，k 从 0 到 1。 */
export function wipeText(s, x, y, size, k, o = {}) {
  k = clamp(k); if (k <= 0) return;
  const w = measure(s, size, o.weight, o.family) + size * 0.2, x0 = o.align === 'center' ? x - w / 2 : o.align === 'right' ? x - w : x - size * 0.1;
  ctx.save(); ctx.beginPath(); ctx.rect(x0, y - size * 1.15, w * snap(k), size * 1.5); ctx.clip(); text(s, x, y, size, o); ctx.restore();
}

/** 字从基线下面弹上来。k 可以带弹簧过冲；窗口高度按常见中文字体留了余量，换字体后先渲一帧看有没有被裁。 */
export function riseText(s, x, y, size, k, o = {}) {
  if (k <= 0) return;
  ctx.save(); ctx.beginPath(); ctx.rect(-DW, y - size * 1.05, DW * 3, size * 1.32); ctx.clip();
  text(s, x, y + (1 - k) * size * 1.2, size, o); ctx.restore();
}

export function roundRect(x, y, w, h, r) {
  r = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath(); ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

export function box(x, y, w, h, r, { fill = null, stroke = null, width = 1, alpha = 1 } = {}) {
  faded(alpha, () => {
    roundRect(x, y, w, h, r);
    if (fill) { ctx.fillStyle = fill; ctx.fill(); }
    if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = width; ctx.stroke(); }
  });
}
