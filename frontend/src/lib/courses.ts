/**
 * 课程板块注册表（单一事实源）。
 *
 * 平台定位是综合英语学习中心，不是"口语产品 + 词汇功能"。口语、单词是
 * 并列的课程板块（Course），未来阅读课等新板块只需在此登记，导航、文案与
 * 未开通提示统一从这里取词，避免三端各写一套叫法。
 *
 * 授权口径不变：`key` 与后端 `tenant_module.module_key` 一一对应，
 * 是否展示仍由 `useModules().hasModule(key)` 决定，服务端闸门是最终裁决。
 */
import type { BiString } from "./bi.ts"

/** 当前已实现的课程板块，与后端 module_key 对齐。 */
export type CourseKey = "speaking" | "vocabulary"

export interface CourseMeta {
  key: CourseKey
  /** 导航与页面标题用的课程名（对外统一叫"课"，不叫"模块"）。 */
  name: BiString
  /** 一句话定位，用于课程卡/空态/未开通提示。 */
  tagline: BiString
  /** 排序权重，小的在前。 */
  order: number
}

export const COURSES: Record<CourseKey, CourseMeta> = {
  speaking: {
    key: "speaking",
    name: { zh: "口语课", en: "Speaking" },
    tagline: {
      zh: "朗读、复述与情景问答，练的是开口表达。",
      en: "Read aloud, repeat and answer: training how you speak.",
    },
    order: 1,
  },
  vocabulary: {
    key: "vocabulary",
    name: { zh: "单词课", en: "Vocabulary" },
    tagline: {
      zh: "认词、拼写与复习，练的是词汇积累。",
      en: "Recognise, spell and review: building your word bank.",
    },
    order: 2,
  },
}

/** 按展示顺序排列的课程清单。 */
export const COURSE_LIST: CourseMeta[] = Object.values(COURSES).sort(
  (a, b) => a.order - b.order,
)

export function courseMeta(key: CourseKey): CourseMeta {
  return COURSES[key]
}

export function courseName(key: CourseKey): BiString {
  return COURSES[key].name
}

/** 未开通/到期提示用的课程名（不含"模块"二字）。 */
export function courseLabelZh(key: CourseKey): string {
  return COURSES[key].name.zh
}
