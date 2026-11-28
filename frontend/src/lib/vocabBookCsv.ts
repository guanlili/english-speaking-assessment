/**
 * 词书导入/导出：一份标准模板、一份导出，两边列完全一致（可导出改完再导入）。
 *
 * 列口径与后端 `_parse_vocab_csv` 一致：headword/meaning_zh 必填，其余可选；
 * accepted_spellings 用 `|` 分隔，morphology 为 JSON 数组字符串。
 * 转义与公式注入防护统一走 `@/lib/csv` 的 `downloadCsv`。
 */
import { VocabularyService, type VocabularyWordPublic } from "@/client"
import { downloadCsv } from "@/lib/csv"

export const VOCAB_CSV_HEADER = [
  "headword",
  "part_of_speech",
  "meaning_zh",
  "meaning_en",
  "accepted_spellings",
  "example_en",
  "morphology",
] as const

/** 模板示例行：两词足够看清格式，不给老师增加删行负担。 */
const TEMPLATE_ROWS: (string | null)[][] = [
  [
    "panda",
    "n.",
    "熊猫",
    "a large black-and-white bear",
    "",
    "The panda eats bamboo.",
    "",
  ],
  [
    "protect",
    "v.",
    "保护",
    "to keep someone or something safe",
    "protects|protecting|protected",
    "We should protect wild animals.",
    '[{"text":"pro","gloss":"向前","kind":"prefix"},{"text":"tect","gloss":"覆盖","kind":"root"}]',
  ],
]

export function downloadVocabBookTemplate(): void {
  downloadCsv([[...VOCAB_CSV_HEADER], ...TEMPLATE_ROWS], "词书导入模板.csv")
}

/** 词条 → 导出行；导出文件可直接回填再导入，不丢词性/例句/词法拆解。 */
export function vocabWordsToCsvRows(
  words: VocabularyWordPublic[],
): (string | null)[][] {
  return words.map((word) => [
    word.headword,
    word.part_of_speech ?? "",
    word.meaning_zh,
    word.meaning_en ?? "",
    (word.accepted_spellings ?? []).join("|"),
    word.example_en ?? "",
    word.morphology && word.morphology.length > 0
      ? JSON.stringify(word.morphology)
      : "",
  ])
}

function safeFilePart(title: string | undefined): string {
  const cleaned = (title ?? "").replace(/[\\/:*?"<>|\r\n]+/g, "-").trim()
  return cleaned || "词书"
}

/** 导出整本词书为 CSV；返回导出词条数，调用方据此给 toast。 */
export async function exportVocabBookCsv(
  bookId: string,
  title?: string,
): Promise<number> {
  const book = await VocabularyService.readBook({ book_id: bookId })
  const words = book.words ?? []
  downloadCsv(
    [[...VOCAB_CSV_HEADER], ...vocabWordsToCsvRows(words)],
    `${safeFilePart(title ?? book.title)}.csv`,
  )
  return words.length
}
