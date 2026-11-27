import type {
  VocabularyStudentResultRow,
  VocabularyWordStatRow,
} from "@/client"

/**
 * 教师结果页的派生纯函数（聚合口径 + 错词 CSV 行生成）。
 *
 * 与组件解耦：聚合与行生成可直接单测；CSV 转义仍统一走 `downloadCsv` /
 * `formatCsvCell`，这里只产出原始值，不在库里重复实现转义规则。
 */

/** 班级首答聚合结果。`accuracy = null` 表示全班零作答，界面显示 `–`。 */
export interface ClassFirstTrySummary {
  /** 全班已答题数之和（分母） */
  answered: number
  /** 全班首答正确题数之和（分子） */
  correct: number
  /** 首答正确率（0–100 取整）；零作答为 null */
  accuracy: number | null
}

/**
 * 班级首答正确率聚合：分子 = 各学生 `correct_first_count` 之和，
 * 分母 = 各学生 `answered_count` 之和；重试轮次不进入该口径。
 * 全班已答为 0 时正确率返回 null（界面显示 `–`，不折算成 0%）。
 */
export function summarizeClassFirstTry(
  students: Array<
    Pick<VocabularyStudentResultRow, "answered_count" | "correct_first_count">
  >,
): ClassFirstTrySummary {
  const answered = students.reduce(
    (sum, row) => sum + (row.answered_count ?? 0),
    0,
  )
  const correct = students.reduce(
    (sum, row) => sum + (row.correct_first_count ?? 0),
    0,
  )
  return {
    answered,
    correct,
    accuracy: answered > 0 ? Math.round((correct / answered) * 100) : null,
  }
}

/** 错词 CSV 行：字段值保持原始类型，表头由调用方按语言传入。 */
export interface WrongWordCsvRow {
  headword: string
  partOfSpeech: string
  meaningZh: string
  answeredOfRoster: string
  correctFirst: number
  errorCount: number
  errorRate: string
  misspellings: string
}

/** 错词 CSV 数据源：兼容结果载荷的逐词统计行（词性可能缺省）。 */
export type WrongWordCsvSource = Pick<
  VocabularyWordStatRow,
  | "headword"
  | "meaning_zh"
  | "answered_count"
  | "correct_first_count"
  | "error_count"
  | "misspellings"
> & {
  part_of_speech?: string | null
}

/** 常见误拼拼成名录：`answer×count`，多条用 `; ` 连接。 */
export function formatMisspellings(
  misspellings: VocabularyWordStatRow["misspellings"],
): string {
  return (misspellings ?? [])
    .map((miss) => `${miss.answer}×${miss.count}`)
    .join("; ")
}

/**
 * 从当前结果载荷的 `words` 生成错词 CSV 行；仅保留 `error_count > 0` 的词。
 * 错误率 = 错误次数 ÷ 已答人数；该词零作答时显示 `–`，不折算成 0%。
 */
export function buildWrongWordCsvRows(
  words: WrongWordCsvSource[],
  rosterSize: number,
): WrongWordCsvRow[] {
  return words
    .filter((word) => (word.error_count ?? 0) > 0)
    .map((word) => {
      const answered = word.answered_count ?? 0
      const errorCount = word.error_count ?? 0
      return {
        headword: word.headword,
        partOfSpeech: word.part_of_speech ?? "",
        meaningZh: word.meaning_zh,
        answeredOfRoster: `${answered}/${rosterSize}`,
        correctFirst: word.correct_first_count ?? 0,
        errorCount,
        errorRate:
          answered > 0 ? `${Math.round((errorCount / answered) * 100)}%` : "–",
        misspellings: formatMisspellings(word.misspellings),
      }
    })
}

/** 错词 CSV 表头（顺序与 `WrongWordCsvRow` 字段一一对应）。 */
export interface WrongWordCsvHeaders {
  headword: string
  partOfSpeech: string
  meaningZh: string
  answeredOfRoster: string
  correctFirst: string
  errorCount: string
  errorRate: string
  misspellings: string
}

/**
 * 组装可直接交给 `downloadCsv` 的二维表：表头 + 错词行。
 * 单元格转义由 `downloadCsv` 内的 `formatCsvCell` 统一处理。
 */
export function wrongWordCsvTable(
  words: WrongWordCsvSource[],
  rosterSize: number,
  headers: WrongWordCsvHeaders,
): Array<Array<string | number>> {
  const rows = buildWrongWordCsvRows(words, rosterSize).map((row) => [
    row.headword,
    row.partOfSpeech,
    row.meaningZh,
    row.answeredOfRoster,
    row.correctFirst,
    row.errorCount,
    row.errorRate,
    row.misspellings,
  ])
  return [
    [
      headers.headword,
      headers.partOfSpeech,
      headers.meaningZh,
      headers.answeredOfRoster,
      headers.correctFirst,
      headers.errorCount,
      headers.errorRate,
      headers.misspellings,
    ],
    ...rows,
  ]
}
