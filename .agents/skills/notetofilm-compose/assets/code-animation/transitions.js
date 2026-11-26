// transitions.js — 借运动的整屏转场。一次转场跨过剪点，两层相邻一起移动，不留空白帧；
// 快速移动的模糊交给 `ntf web-render --subframes 4`，不要把整幅图错开叠影。
// drawA、drawB 是 async (dx, dy) => {...}，在给定位移处画出上一镜、下一镜的整幅画面。
import { seg, whip, ease, lerp } from './motion.js';
import { DW, DH } from './kit.js';

/** 以剪点 cut 为中心、总长 dur 秒的转场进度：之前 0，之后 1。上一镜和下一镜都用同一个进度。 */
export const across = (t, cut, dur) => seg(t, cut - dur / 2, cut + dur / 2);

/** 横甩（约 0.2–0.3 秒）：上一镜向左甩出，下一镜紧跟着从右边进来；dir = -1 反过来。 */
export async function whipPan(k, drawA, drawB, { dir = 1 } = {}) {
  const off = whip(k) * DW * dir;
  if (k < 1) await drawA(-off, 0);
  if (k > 0) await drawB(DW * dir - off, 0);
}

/** 上下穿越（约 0.3–0.4 秒）：dir = 1 往下穿（上一镜上移，下一镜从下面贴着升上来），dir = -1 往上穿出。 */
export async function pushThrough(k, drawA, drawB, { dir = 1 } = {}) {
  const off = ease.inOutCubic(k) * DH * dir;
  if (k < 1) await drawA(0, -off);
  if (k > 0) await drawB(0, DH * dir - off);
}

/**
 * 遮挡物掠过（约 0.5–0.7 秒）：一件看得出是什么的东西（一张单子、一扇门、走过的人）从镜头前掠过，
 * 进度过半、它盖住画面中央的那一刻换镜。drawCover(x, y, k) 画遮挡物，要大到能盖住中央。
 */
export async function wipeBy(k, drawA, drawB, drawCover, { from = [DW + 760, -520], to = [-760, DH + 520] } = {}) {
  if (k < 0.5) await drawA(0, 0); else await drawB(0, 0);
  if (k > 0 && k < 1) {
    const e = ease.inOutSine(k);
    drawCover(lerp(from[0], to[0], e), lerp(from[1], to[1], e), k);
  }
}
