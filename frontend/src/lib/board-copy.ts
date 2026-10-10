import type { BoardStudent } from "../client/types.gen.ts"
import type { BiString } from "./bi.ts"

/**
 * 教师课堂面板的文案与序列化纯函数层（从 t.$code.index.tsx 抽出，批次 10-10）：
 * 学生状态判定、名单筛选标签、CSV 行构造、提醒/反馈文案生成都只依赖入参
 * 和注入的 t——抽出后可单测，页面只管编排与交互。
 */

export type BoardStudentStatus = "inactive" | "practicing" | "done" | "idle"

/** 名单筛选下拉与 CSV 状态列共用的标签（键序即下拉展示序，勿重排）。 */
export const BOARD_STATUS_LABELS: Record<string, BiString> = {
  all: { zh: "全部状态", en: "All statuses" },
  done: { zh: "已提交", en: "Submitted" },
  practicing: { zh: "评分中", en: "Scoring" },
  idle: { zh: "未提交", en: "Not submitted" },
  inactive: { zh: "7 天未练", en: "Inactive 7 days" },
}

/** 学生状态判定：7 天未练 > 评分中 > 已提交 > 未提交。 */
export function boardStatusOf(student: {
  inactive_days7?: boolean
  has_pending: boolean
  done_count: number
}): BoardStudentStatus {
  return student.inactive_days7
    ? "inactive"
    : student.has_pending
      ? "practicing"
      : (student.done_count ?? 0) > 0
        ? "done"
        : "idle"
}

/** 名单展示名：有区分码时以「·」拼接（与复制反馈文案共用）。 */
export function boardStudentDisplayName(student: {
  display_name: string
  suffix?: string | null
}): string {
  return student.suffix
    ? `${student.display_name}·${student.suffix}`
    : student.display_name
}

/** 「值得关注」名单：7 天未练或本轮一题未交。 */
export function needsAttentionStudents(
  students: BoardStudent[],
): BoardStudent[] {
  return students.filter(
    (student) => student.inactive_days7 || student.done_count === 0,
  )
}

/** 群发提醒文案：点名前 8 位未完成学生，没有则称全班。 */
export function boardReminderMessage(
  classroom: { classroom_name: string; classroom_code: string },
  students: BoardStudent[],
  t: (bi: BiString) => string,
): string {
  const names = needsAttentionStudents(students)
    .map((student) => student.display_name)
    .slice(0, 8)
    .join("、")
  return t({
    zh: `【${classroom.classroom_name}】${names || "同学们"}，请完成今天的口语练习。提交后老师会查看反馈。课堂码：${classroom.classroom_code}`,
    en: `[${classroom.classroom_name}] ${names || "everyone"}, please complete today's speaking practice. Your teacher will review your feedback after you submit. Classroom code: ${classroom.classroom_code}`,
  })
}

/** 单个学生的复制反馈文案：按是否已提交分两种口吻。 */
export function boardStudentFeedbackMessage(
  student: Pick<
    BoardStudent,
    "display_name" | "suffix" | "done_count" | "total_count"
  >,
  t: (bi: BiString) => string,
): string {
  const name = boardStudentDisplayName(student)
  return student.done_count === 0
    ? t({
        zh: `${name} 还没有提交本轮口语练习，可以提醒完成。`,
        en: `${name} hasn't submitted this round of speaking practice yet — a reminder could help.`,
      })
    : t({
        zh: `${name} 已完成 ${student.done_count}/${student.total_count} 题，可结合结果页逐题反馈。`,
        en: `${name} has completed ${student.done_count}/${student.total_count} items; give per-item feedback from the results view.`,
      })
}

export interface BoardRosterCsv {
  rows: (string | number)[][]
  filename: string
}

/** 今日名单 CSV：表头 + 每生一行（含状态本地化），文件名带导出日期。 */
export function boardRosterCsv(
  students: BoardStudent[],
  classroomCode: string,
  t: (bi: BiString) => string,
  now: Date = new Date(),
): BoardRosterCsv {
  const header = [
    t({ zh: "姓名", en: "Name" }),
    t({ zh: "区分码", en: "Suffix" }),
    t({ zh: "完成题数", en: "Items Done" }),
    t({ zh: "跟读均分", en: "Repeat Avg" }),
    t({ zh: "情景问答均分", en: "Scenario Q&A Avg" }),
    "XP",
    t({ zh: "连胜天数", en: "Streak Days" }),
    t({ zh: "状态", en: "Status" }),
  ]
  const rows = students.map((st) => [
    st.display_name,
    st.suffix ?? "",
    `${st.done_count ?? 0}/${st.total_count ?? 0}`,
    st.repeat_avg ?? "-",
    st.question_avg ?? "-",
    String(st.xp ?? 0),
    String(st.streak_days ?? 0),
    t(BOARD_STATUS_LABELS[boardStatusOf(st)] ?? { zh: "", en: "" }),
  ])
  const date = now.toISOString().slice(0, 10)
  const filename = t({
    zh: `课堂${classroomCode}-练习名单-${date}.csv`,
    en: `classroom-${classroomCode}-practice-roster-${date}.csv`,
  })
  return { rows: [header, ...rows], filename }
}
