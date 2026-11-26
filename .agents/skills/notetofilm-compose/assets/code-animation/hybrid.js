// hybrid.js — 视频片段加代码动画的成片页面示例：人物和物件的动作来自视频片段，准确的字、标注和图解由代码画，
// 镜头之间借运动转场。替换镜头表、片段和文字，保留四个做法：
//   1. 时间只从 film-timing.js 取（`ntf timing --apply --js` 导出），字落在说到它的那个词上；
//   2. 片段用 clips.js 按需取帧，叠加的字用 overlay() 按同一取景贴在素材里的东西上；
//   3. 按 frame.time 选镜头（shotAt），开 --subframes 时硬切不混帧；
//   4. 转场跨过剪点（transitions.js），快速移动的模糊交给 --subframes。
// 示例情境是虚构的：通知早于上架，顾客到店找不到包裹；改成上架后再通知。
import { DUR, SC, W } from './film-timing.js';
import { seg, glide, drawPath, loadFonts } from './motion.js';
import { ctx, DW, DH, base, text, faded, font } from './kit.js';
import { clipLibrary, overlay, shotAt } from './clips.js';
import { across, whipPan, pushThrough, wipeBy } from './transitions.js';

const C = { paper: '#EDEBE6', ink: '#1E2328', muted: '#7C8288', accent: '#D9822B' };

// 片段：名称 → `ntf frames` 返回的帧数和帧率；帧在 media/<名称>/。
const clips = clipLibrary({
  cart: { frames: 96, fps: 24 },
  shelf: { frames: 96, fps: 24 },
  pickup: { frames: 96, fps: 24 },
});

// 素材里要贴字的东西，在原尺寸帧（1280×720）上量出的像素位置；只对机位固定的片段直接成立。
const SPOT = { parcel: [640, 440], slot: [820, 300] };

// s01 推车上的包裹：镜头缓推，标签贴在包裹上
async function s01(t, d = [0, 0]) {
  const lt = t - SC.s01.start;
  const v = await clips.play('cart', lt, { from: 0.2, zoom: 1 + 0.08 * seg(lt, 0, 3), dx: d[0], dy: d[1] });
  overlay(v, () => {
    const k = glide(seg(t, W('s01', '包裹') - 0.05, W('s01', '包裹') + 0.3));
    faded(k, () => { ctx.strokeStyle = C.accent; ctx.lineWidth = 4; ctx.strokeRect(SPOT.parcel[0] - 90, SPOT.parcel[1] - 70, 180, 140); });
    text('还没上架', SPOT.parcel[0], SPOT.parcel[1] - 86, 26, { color: C.ink, weight: 600, align: 'center', alpha: k });
  });
}

// s02 店员把包裹放上货架：格位编号贴在格位上
async function s02(t, d = [0, 0]) {
  const lt = t - SC.s02.start;
  const v = await clips.play('shelf', lt, { from: 0.4, dx: d[0], dy: d[1] });
  overlay(v, () => {
    const k = glide(seg(t, W('s02', '位置') - 0.1, W('s02', '位置') + 0.3));
    text('B-12', SPOT.slot[0], SPOT.slot[1] - 18, 34, { color: C.accent, weight: 700, align: 'center', alpha: k });
  });
}

// s03 图解：到站 → 上架 → 通知，通知那一步落在“通知”这个词上
function s03(t, d = [0, 0]) {
  ctx.save(); ctx.translate(d[0], d[1]);
  ctx.fillStyle = C.paper; ctx.fillRect(0, 0, DW, DH);
  const steps = [['到站', '到站'], ['上架', '上架'], ['通知', '通知']], y = DH / 2, x0 = 260, gap = (DW - 520) / 2;
  steps.forEach(([label, word], i) => {
    const at = i === 0 ? SC.s03.start + 0.2 : W('s03', word), k = glide(seg(t, at - 0.05, at + 0.35)), x = x0 + i * gap;
    if (i > 0) drawPath(ctx, [[x - gap + 70, y], [x - 70, y]], glide(seg(t, at - 0.35, at)), { width: 4, color: C.muted, arrow: 12 });
    faded(k, () => { ctx.fillStyle = i === 2 ? C.accent : C.ink; ctx.beginPath(); ctx.arc(x, y, 56, 0, Math.PI * 2); ctx.fill(); });
    text(label, x, y + 12, 30, { color: C.paper, weight: 700, align: 'center', alpha: k });
  });
  ctx.restore();
}

// s04 顾客取走包裹
async function s04(t, d = [0, 0]) {
  await clips.play('pickup', t - SC.s04.start, { from: 0.2, zoom: 1.04, dx: d[0], dy: d[1] });
}

// 遮挡物：一张取件通知单，大到能在掠过中央时盖住画面
function slip(x, y) {
  ctx.save(); ctx.translate(x, y); ctx.rotate(-0.38);
  ctx.fillStyle = '#F7F5F0'; ctx.fillRect(-520, -680, 1040, 1360);
  ctx.fillStyle = C.accent; ctx.fillRect(-520, -680, 1040, 40);
  text('取件通知', -460, -560, 96, { color: C.ink, weight: 700 });
  ctx.restore();
}

// 镜头表：[开始秒, 绘制函数]。转场写在跨过剪点的那一段里，上一镜和下一镜用同一个进度。
const SHOTS = [
  [0, s01],
  [SC.s02.start - 0.12, async t => whipPan(across(t, SC.s02.start, 0.24), dx => s01(t, [dx, 0]), dx => s02(t, [dx, 0]))],
  [SC.s02.start + 0.12, s02],
  [SC.s03.start - 0.17, async t => pushThrough(across(t, SC.s03.start, 0.34), (dx, dy) => s02(t, [dx, dy]), async (dx, dy) => s03(t, [dx, dy]))],
  [SC.s03.start + 0.17, s03],
  [SC.s04.start - 0.3, async t => wipeBy(across(t, SC.s04.start, 0.6), async () => s03(t), () => s04(t), slip)],
  [SC.s04.start + 0.3, s04],
];

export async function start() {
  await loadFonts([font(96, 700), font(34, 700), font(30, 700), font(26, 600)]);
  window.DUR = DUR;
  window.render = async (t, frame) => {
    base(C.ink);
    await shotAt(SHOTS, t, frame)(t);
    faded(seg(t, DUR - 0.5, DUR), () => { ctx.fillStyle = '#000'; ctx.fillRect(0, 0, DW, DH); });
  };
}
