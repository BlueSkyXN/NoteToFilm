# 入门：从安装到一支能看的片子

这份说明给第一次用 NoteToFilm 的人和 Agent：先不花钱做出一支完整的短片，再加入视频生成，最后用工具看出片子哪里慢、哪里乱。命令细节见[命令说明](../shared/commands.md)，制作方法在各 Skill 里。

## 1. 安装并检查

按[仓库 README](../README.md) 从源码运行，或用安装器把 CLI 和七个 Skill 装进客户端。检查依赖：

```bash
ntf install-info --require-audio --require-render
```

还需要 FFmpeg、ffprobe；代码动画渲染另装 `web` 可选依赖（Playwright）和 Chromium 或 Chrome。

## 2. 先做一支不花钱的片子

配音用 Edge TTS（联网、免费），画面用代码动画，不调用付费的图像和视频接口。

1. 建项目，写正式分镜（每镜的旁白和画面任务），配音并按实测定片长：

   ```bash
   ntf init demo --title 示例
   ntf storyboard demo --file storyboard.json
   ntf run demo --kind audio
   ntf timing demo --apply
   ntf timing demo --js animation/film/film-timing.js
   ```

2. 把 compose Skill 的代码动画骨架（`assets/code-animation/`）复制到 `demo/animation/film/`。只有图形时从 `index.html` 改起；要和视频片段同屏时用 `hybrid.html`（第 3 节）。字和动作写在 `W('镜头', '词')`（单个词）或 `P('镜头', '短语')` 上，落在说到它的那一刻。
3. 渲染、合成、检查：

   ```bash
   ntf web-render demo --page animation/film --scene film --text-scan 0.25   # 先扫一遍出界、重叠和过小的字
   ntf web-render demo --page animation/film --scene film --subframes 4
   ntf plan demo && ntf run demo --kind compose
   ntf inspect FILM --scan --timeline TIMELINE
   ntf sheet FILM --output review/sheet --timeline TIMELINE
   ```

   合成清单的写法见 compose Skill；`FILM`、`TIMELINE` 是合成返回的成片和时间表。之后只改了某几秒，用 `--range 开始-结束` 只重渲那一段，拼回已采用的整片。

## 3. 加入视频生成（会产生费用）

人物和案例片里，人物的动作要由人去做：旁白说他在画、在递、在开口，画面里就是他在做。这类镜头用图生视频。

1. 配置图像、视频通道：`ntf config-init routes.json`，按[通道配置说明](company-protocols.md)填好后 `ntf routes --config routes.json` 检查。
2. 在设计备稿写视频预算：哪些镜头用视频、共多少秒、按通道单价估多少，确认在授权以内。
3. 生成关键帧和片段（image、video Skill），选片时检查动作是否看得见、人物有没有在片段后段变样。
4. 把采用的片段抽成帧，用 `hybrid.html` 的写法把片段、叠字和整屏转场放进一个页面：

   ```bash
   ntf frames demo --select s05.video --output animation/film/media/s05
   ntf web-render demo --page animation/film/hybrid.html --scene film --subframes 4
   ```

   不花钱也能先演练一遍：compose Skill 的 `code-animation.md`“视频片段加代码动画”一节有用 FFmpeg 占位片段跑通模板的命令。

## 4. 看出片子哪里不对

Agent 不能连续看片，靠这几样代替：

- `ntf inspect FILM --scan`：`freeze` 是完全不动，`low_motion` 是几乎不动（字和标签在变、人和镜头没动也算），`pace` 给中位镜长和剪点。对照 direct Skill 片型配方里的“节奏起点”。
- `ntf sheet FILM --cuts --fps 8 --timeline TIMELINE`：逐帧看每个剪点和转场，找空白帧、混帧、接错的物件。
- 声音：说话时配乐要比人声低 15 dB 以上，音效只给画面里发出声音的东西；量法见 compose Skill 的 `sound-mix.md`“检查”。听感要人用耳机确认。

改的时候先判断问题在哪一层（direct Skill 的常见做法有诊断表），只改那一层；旁白、时间轴不动时，前后两版可以直接并排比较。

## 5. 交给 Agent 时说清楚

让 Agent 从 workflow Skill 开始，并告诉它：

- 片子给谁看、用在哪里，看完要记住什么；
- 材料在哪里（整篇，不只截取的一段）；
- 时长、画幅，人物能否点名、用什么形象；
- 通道和费用上限：每支片子最多花多少，超出先问。

Agent 开工前会用几行话告诉你计划：给谁看、主角、怎么讲、画面样子、片长和预计花费。说完它接着做，觉得不对随时打断。你没说清给谁看、用在哪，或者花费会超出你给的额度时，它会先停下来问。成片是一支完整首版，有开头交代和结尾落点，不交没头没尾的中段。
