// clips.js — 视频片段与镜头表。生成的视频片段用 `ntf frames` 抽成帧序列放进页面目录，这里按需取帧、
// 和图形同屏；叠加的字按同一取景贴在素材里的东西上；多镜头的页面按帧时刻选镜头。
import { clamp, lerp, loadImage } from './motion.js';
import { ctx, DW, DH, faded } from './kit.js';

/**
 * 片段库。clips：名称 → { frames, fps }（`ntf frames` 的返回值里有这两项），帧在 media/<名称>/000.jpg 起。
 * 帧按需加载，最近用过的 cacheSize 帧留在内存里；一次全部加载，片段多时浏览器内存会撑满。
 * 取不到的帧会让页面报错（web-render 按缺资源停下），片段到齐、抽完帧再渲。
 */
export function clipLibrary(clips, { dir = 'media', cacheSize = 90 } = {}) {
  const cache = new Map();
  async function frame(name, seconds) {
    const clip = clips[name];
    if (!clip) throw new Error(`片段库里没有 ${name}`);
    const i = clamp(Math.floor(seconds * clip.fps + 1e-6), 0, clip.frames - 1);
    const key = `${name}/${i}`;
    let image = cache.get(key);
    if (image) { cache.delete(key); cache.set(key, image); return image; }
    image = await loadImage(`${dir}/${name}/${String(i).padStart(3, '0')}.jpg`);
    cache.set(key, image);
    if (cache.size > cacheSize) cache.delete(cache.keys().next().value);
    return image;
  }
  /** 镜头内时间 lt → 素材时间：入点 from 加倍速 speed，或分段 keys [[镜头内秒, 素材秒], ...]（慢放画圈、原速画线）。 */
  const sourceTime = (lt, { from = 0, speed = 1, keys = null } = {}) => {
    if (!keys) return from + lt * speed;
    if (lt <= keys[0][0]) return keys[0][1];
    for (let i = 0; i < keys.length - 1; i++) {
      const [a, sa] = keys[i], [b, sb] = keys[i + 1];
      if (lt <= b) return lerp(sa, sb, (lt - a) / (b - a));
    }
    return keys[keys.length - 1][1];
  };
  /** 在镜头里播放一段：返回这次画面的取景，叠加层用 overlay(view, …) 对齐。 */
  async function play(name, lt, { from, speed, keys, ...look } = {}) {
    return drawFrame(await frame(name, sourceTime(lt, { from, speed, keys })), look);
  }
  return { frame, play, sourceTime };
}

/** 取景：zoom 推近倍数，cx、cy 是取景中心（0–1）。sx、sy、sw、sh 是素材上的取景框，k 是素材像素到设计像素的倍数。 */
export function view(iw, ih, { zoom = 1, cx = 0.5, cy = 0.5 } = {}) {
  const sw = iw / zoom, sh = ih / zoom;
  return { sx: clamp(cx * iw - sw / 2, 0, iw - sw), sy: clamp(cy * ih - sh / 2, 0, ih - sh), sw, sh, k: DW / sw };
}

/** 画一帧素材铺满画面（素材与画幅同比例）。dx、dy 是整幅位移，转场时用。返回取景，带上位移。 */
export function drawFrame(image, { zoom = 1, cx = 0.5, cy = 0.5, dx = 0, dy = 0, alpha = 1, filter = null } = {}) {
  const v = { ...view(image.naturalWidth, image.naturalHeight, { zoom, cx, cy }), dx, dy };
  faded(alpha, () => {
    if (filter) ctx.filter = filter;
    ctx.drawImage(image, v.sx, v.sy, v.sw, v.sh, dx, dy, DW, DH);
    ctx.filter = 'none';
  });
  return v;
}

/**
 * 在素材像素坐标里画叠加层：字、标注和描线贴在素材里的东西上，随推拉一起动。
 * 坐标先在原尺寸帧上量（画网格读数），只对机位固定的片段直接成立；镜头在动的片段量几个关键帧再插值。
 */
export function overlay(v, draw) {
  ctx.save();
  ctx.translate(v.dx || 0, v.dy || 0); ctx.scale(v.k, v.k); ctx.translate(-v.sx, -v.sy);
  try { draw(); } finally { ctx.restore(); }
}

/**
 * 镜头表：shots 是 [[开始秒, 绘制函数], …]，按开始时刻排列。返回当前镜头的绘制函数。
 * 按 frame.time（这一帧的名义时刻）选镜头：开 --subframes 时各子帧的 t 围绕它取样，
 * 直接按 t 选，硬切处会把前后两镜混成一帧叠影。镜头内的运动照常用 t。
 */
export function shotAt(shots, t, frame) {
  const tf = frame && Number.isFinite(frame.time) ? frame.time : t;
  let current = shots[0][1];
  for (const [start, draw] of shots) if (tf >= start - 1e-6) current = draw;
  return current;
}

export { DW, DH };
