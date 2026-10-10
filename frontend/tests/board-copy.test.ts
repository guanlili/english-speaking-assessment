import assert from "node:assert/strict"
import test from "node:test"
import type { BoardStudent } from "../src/client/types.gen.ts"
import {
  boardReminderMessage,
  boardRosterCsv,
  boardStatusOf,
  boardStudentDisplayName,
  boardStudentFeedbackMessage,
  needsAttentionStudents,
} from "../src/lib/board-copy.ts"

/**
 * 教师课堂面板的文案/序列化纯函数层（批次 10-10 抽出）：
 * 双语解析由注入的 t 决定，这里固定取中文断言（en 分支行为同构）。
 * 构造最小 BoardStudent 形状，缺省字段走 `??` 兜底分支。
 */

const zh = (bi: { zh: string }) => bi.zh
const en = (bi: { en: string }) => bi.en

const student = (over: Partial<BoardStudent> = {}): BoardStudent => ({
  student_id: "s1",
  display_name: "小明",
  suffix: null,
  done_count: 0,
  total_count: 5,
  repeat_avg: null,
  question_avg: null,
  has_pending: false,
  inactive_days7: false,
  xp: 0,
  streak_days: 0,
  items: [],
  ...over,
})

test("状态判定优先级：未练 > 评分中 > 已提交 > 未提交", () => {
  assert.equal(
    boardStatusOf({ inactive_days7: true, has_pending: true, done_count: 5 }),
    "inactive",
  )
  assert.equal(
    boardStatusOf({ inactive_days7: false, has_pending: true, done_count: 5 }),
    "practicing",
  )
  assert.equal(
    boardStatusOf({ inactive_days7: false, has_pending: false, done_count: 1 }),
    "done",
  )
  assert.equal(
    boardStatusOf({ inactive_days7: false, has_pending: false, done_count: 0 }),
    "idle",
  )
})

test("值得关注名单：7 天未练或一题未交", () => {
  const roster = [
    student({ student_id: "a", done_count: 3 }),
    student({ student_id: "b", done_count: 0 }),
    student({ student_id: "c", inactive_days7: true, done_count: 5 }),
  ]
  assert.deepEqual(
    needsAttentionStudents(roster).map((s) => s.student_id),
    ["b", "c"],
  )
})

test("展示名：区分码以「·」拼接，无则原样", () => {
  assert.equal(
    boardStudentDisplayName({ display_name: "小明", suffix: "02" }),
    "小明·02",
  )
  assert.equal(
    boardStudentDisplayName({ display_name: "小明", suffix: null }),
    "小明",
  )
})

test("群发提醒文案：点名前 8 位，超出的截断；没有则称全班", () => {
  const classroom = { classroom_name: "三年二班", classroom_code: "ABC123" }
  const none = boardReminderMessage(classroom, [], zh)
  assert.match(none, /【三年二班】同学们，请完成今天的口语练习。/)
  assert.match(none, /课堂码：ABC123/)

  const many = boardReminderMessage(
    classroom,
    Array.from({ length: 10 }, (_, i) =>
      student({
        student_id: `s${i}`,
        display_name: `学生${i}`,
        done_count: 0,
      }),
    ),
    zh,
  )
  const named = [...many.matchAll(/学生\d/g)]
  assert.equal(named.length, 8, "最多点名 8 位")
  assert.ok(many.includes("学生7"))
  assert.ok(!many.includes("学生8"))
})

test("单生反馈文案：未提交与已完成两种口吻", () => {
  const idle = boardStudentFeedbackMessage(
    { display_name: "小明", suffix: "02", done_count: 0, total_count: 5 },
    zh,
  )
  assert.equal(idle, "小明·02 还没有提交本轮口语练习，可以提醒完成。")

  const done = boardStudentFeedbackMessage(
    { display_name: "小明", suffix: null, done_count: 3, total_count: 5 },
    en,
  )
  assert.equal(
    done,
    "小明 has completed 3/5 items; give per-item feedback from the results view.",
  )
})

test("名单 CSV：表头、行映射兜底、状态本地化与文件名日期", () => {
  const now = new Date("2026-10-10T00:00:00Z")
  const { rows, filename } = boardRosterCsv(
    [
      student({
        display_name: "小明",
        suffix: "02",
        done_count: 3,
        total_count: 5,
        repeat_avg: 88.5,
        question_avg: 76,
        xp: 120,
        streak_days: 4,
      }),
      student({ student_id: "s2", display_name: "小红" }),
    ],
    "ABC123",
    zh,
    now,
  )
  assert.equal(
    rows[0].join(","),
    "姓名,区分码,完成题数,跟读均分,情景问答均分,XP,连胜天数,状态",
  )
  assert.deepEqual(rows[1], [
    "小明",
    "02",
    "3/5",
    88.5,
    76,
    "120",
    "4",
    "已提交",
  ])
  // 缺省字段走兜底：区分码空串、均分 "-"、XP/连胜归零
  assert.deepEqual(rows[2], ["小红", "", "0/5", "-", "-", "0", "0", "未提交"])
  assert.equal(filename, "课堂ABC123-练习名单-2026-10-10.csv")

  const enName = boardRosterCsv([], "ABC123", en, now).filename
  assert.equal(enName, "classroom-ABC123-practice-roster-2026-10-10.csv")
})
