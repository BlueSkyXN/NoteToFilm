// 示例时间表，格式与 `ntf timing PROJECT --apply --js animation/<页面>/film-timing.js` 导出的一致：
// 镜头窗口取自正式分镜，逐词时间取自所采用配音的词边界（秒，从片头算起）。实际项目用命令导出，不手改。
export const TL = {"dur": 12.0, "scenes": [
  {"id": "s01", "start": 0.0, "dur": 3.0, "voice": 0.3, "words": [["通知", 0.35], ["已", 0.72], ["到", 0.84], ["包裹", 1.25], ["还在", 1.68], ["推车", 2.0], ["上", 2.32]]},
  {"id": "s02", "start": 3.0, "dur": 3.0, "voice": 3.25, "words": [["店员", 3.3], ["把", 3.7], ["它", 3.82], ["放上", 3.98], ["货架", 4.35], ["记下", 4.95], ["位置", 5.3]]},
  {"id": "s03", "start": 6.0, "dur": 3.0, "voice": 6.25, "words": [["上架", 6.3], ["以后", 6.68], ["再", 7.05], ["发", 7.2], ["通知", 7.38]]},
  {"id": "s04", "start": 9.0, "dur": 3.0, "voice": 9.25, "words": [["顾客", 9.3], ["一", 9.72], ["到", 9.82], ["就能", 10.0], ["取走", 10.35]]}
]};
export const DUR = TL.dur;
export const SC = Object.fromEntries(TL.scenes.map(s => [s.id, s]));
/** 某镜第 n 次说到 word 的绝对时刻（秒）。词边界缺失的镜头用 SC[id].voice 或 SC[id].start 加秒数。 */
export function W(id, word, n = 1) {
  const hits = (SC[id]?.words || []).filter(w => w[0] === word);
  if (hits.length < n) throw new Error(`${id} 里没有第 ${n} 个“${word}”`);
  return hits[n - 1][1];
}
