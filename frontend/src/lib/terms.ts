/**
 * 全站术语单一事实源（2026-09 术语统一）。
 *
 * 面向用户的新文案一律从这里取词，避免同一概念再次出现多种叫法。
 * 人读版本（含取舍原因）见仓库 CLAUDE.md「术语表」章节。
 */
export const TERMS = {
  /** Unit：课堂指派与学生自主练习的基本单位 */
  unit: "单元",
  /** Unit.topic：单元的主题（如「宠物」） */
  topic: "主题",
  /** Passage：朗读/复述用的英文材料 */
  passage: "篇目",
  /** 三种题型（全端统一名称） */
  typeReading: "文章朗读",
  typeRepeat: "听句复述",
  typeQa: "情景问答",
  /** 学生端每日练习入口（与导航一致） */
  todayPractice: "今日练习",
  /** 老师未发布统一内容时，学生按单元顺序自行练习 */
  selfPractice: "自主练习",
  /** 老师把单元下发给全班的动作（教师端按钮用「发布」） */
  publish: "发布",
  /** 系统给学生的分数口径：不是考试成绩 */
  score: "参考分",
  /** 学生成长页（导航与页面标题一致） */
  growthPage: "我的成长",
  /** 教师端查看学生历史曲线的页面 */
  trailPage: "进步轨迹",
} as const

/** 激励规则解释（触点小字 / Tooltip / 帮助页共用，防止口径漂移）。 */
export const EXPLAIN = {
  stars:
    "星级按本轮各题参考分均值评定：≥85 得 3 星，≥70 得 2 星，完成即得 1 星。只和自己比，不和同学排名。",
  xp: "每完成一题得 10 XP，每颗星加 5 XP，连续练习 3 天及以上每天再奖 10 XP。",
  streak: "在练习日内连续完成练习的累计天数，中断后重新开始。",
  badges:
    "完成特定练习目标时获得（如首次开口、坚持 3 天等），只在「我的成长」展示。",
  score: "参考分由 AI 语音评测生成，用于指出改进方向，不是考试成绩或官方等级。",
} as const

/** 题型 → 展示名（学生端/教师端/结果页/发布历史共用，防文案分叉）。 */
export const ITEM_TYPE_LABELS: Record<string, string> = {
  passage: TERMS.typeReading,
  repeat: TERMS.typeRepeat,
  question: TERMS.typeQa,
}
