# SpeakUp 开口说：原型设计系统与功能落地

参照 `prototypes/speakup/index.html`，把正式产品升级为原型的视觉风格与学生端体验。产品定位不变（课堂教学工具），皮肤与交互全面 SpeakUp 化。

## P1 全局换肤（SpeakUp 设计系统）
- `src/index.css` 主题变量映射原型 tokens：米白背景 `hsl(75 22% 97%)`、暖绿主色 `hsl(158 41% 29%)`、薄荷 `hsl(111 29% 92%)`、蜜桃点缀、大圆角（22px/12px）、柔和阴影；dark 模式保持可用
- Button primary 立体风格（底部 4px 深绿硬阴影 + hover 上浮，多邻国式）；录音钮脉冲、波形动画、页面进入动画 keyframes
- 品牌替换：`APP_NAME` → "SpeakUp 开口说"（config.ts / 页面标题 / README / CLAUDE.md）；登录页与侧边栏品牌字样

## P2 自由练习后端（探索模式）
- `PracticeSession.mode`（daily/explore，迁移一列，默认 daily）
- `POST /classes/{code}/explore {unit_id, student_id}`：创建/复用当日该单元的 explore session
- `GET /today` 支持 `session_id` 参数返回任意 session 的计划（练习页复用现有流程）；explore 轮同样积累 XP/星级/词汇/轨迹
- **教师面板 board 只统计 daily 轮**（自由练习不进课堂完成率）
- 测试：explore 创建/复用/计划/教师面板排除

## P3 学生端信息架构（新页面 + StudentShell）
- `StudentShell` 组件：学生端左侧导航（学习首页/今日练习/主题探索/我的成长/关卡地图）+ 课堂信息 + 底部鼓励语；home/explore/practice/result/me/map 六页接入
- `/home/:code` 学习首页：hero 欢迎卡 + 今日计划卡（进度条、3 复述+2 问答两行、开始按钮）+ 周目标环（trail 近 7 日打卡，目标 5 天，localStorage 可调）+ 档位生长条（A2/B1/B2 track）+ 每日金句卡
- `/explore/:code` 主题探索：单元卡片网格（插画 + 档位标签 + 时长）、Dialog 预览（篇目/复述句/分档问法）→「就聊这个」进自由练习
- `TopicArt` 组件：从原型搬 6 幅 SVG 主题插画（pets/school/weekend/food/future/friends），按 topic 映射

## P4 练习页交互升级（p.$code.index）
- 题头：步骤条（done/current）+ 类型标签（LISTEN & REPEAT / YOUR TURN）+ 中文提示（按题型固定文案）
- 听示范：语速选择（0.8×/1.0×，speechSynthesis rate；音频文件模式隐藏）；复述题「收起原文」练记忆开关
- 录音区：大圆录音钮（录音中红色脉冲）+ 波形动画 + 计时 + 原型的鼓励文案（"说完后点一下结束"）
- 表达支架卡：问答 → "I think… because…" 句式支架；复述 → "Listen. Pause. Speak."
- 反馈卡：分数格子化（score-cell）+ 开头鼓励语（复述/问答两套）+ 来源标注保留

## P5 结果页与成长页重构
- 结果页：奖杯 banner + 4 统计卡（总评/完整度/流利度/词汇档）+ rubric 四维条形 + 词表命中词 tags + 升级表达卡（**收藏**，localStorage）+ 每题回看 Dialog（转写+音频回放）
- `/me`：统计卡（累计开口分钟/完成次数/档位/坚持天数）+ 趋势与词汇生长条 + 练习时间线 + 徽章墙保留
- 表达收藏存 localStorage（`esa:saved-expressions`），不动后端

## P6 教师/管理端视觉统一
- 皮肤自动继承；教师面板：统计卡化（完成率/均分/值得关注）、档位分布改条形图、文案换原型基调（"参考数据辅助教学，不定义学生"）；管理端标签文案微调

## 执行顺序与验证
P1（皮肤）→ P2（后端探索）→ P3（新页面）→ P4（练习页）→ P5（结果/成长）→ P6（教师/管理）。
每阶段：后端测试全绿 → generate-client → 前端 lint/build → 浏览器实测；最终全量回归 + 提交 PR。原型的鼓励文案与插画资产直接搬运（自带版权：项目内原型文件）。