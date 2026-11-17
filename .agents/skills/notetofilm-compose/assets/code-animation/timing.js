// timing.js — 本镜唯一的时间来源，页面只从这里取时间。
// 按真实配音和合成窗口填写：DUR 取本镜窗口（ntf timing 或合成时间表），BEATS 写段落卡里的关键变化时点（秒）。
// 旁白改动后先更新这里，再重新导出。
export const DUR = 7;

export const BEATS = {
  title: 0.2,      // 讲解对象出现
  baseline: 0.6,   // 共同基准建立
  first: 1.4,      // A 状态
  second: 2.6,     // B 状态，位置与尺度和 A 相同
  gap: 3.8,        // 差异被标出
  hold: 4.6,       // 有意停留，供阅读；之后画面保持
};
