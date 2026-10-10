import type { BiString } from "./bi.ts"
import { EXAM_KIND_LABELS } from "./terms.ts"

/**
 * 练习页题面文案（从 p.$code.index.tsx 抽出的纯函数层，批次 10-10）：
 * 题型角标（itemPromptLabel）与作答提示（itemHint）只依赖题目特征，
 * 不依赖页面状态——抽出后可单测，练习页只管编排。
 */

export interface PracticeItemCopyInput {
  type: string
  examKind: string | null
  sentenceIndex?: number | null
  sentenceTotal?: number | null
}

export interface PracticeItemCopy {
  isPassage: boolean
  isInstruction: boolean
  isSentenceItem: boolean
  /** 题型角标文案（含句序后缀），已按当前语言解析 */
  promptLabel: string
  /** 作答提示文案 */
  hint: string
}

export function practiceItemCopy(
  input: PracticeItemCopyInput,
  t: (bi: BiString) => string,
): PracticeItemCopy {
  const isPassage = input.type === "passage"
  const isInstruction = input.type === "instruction"
  const isQuestion = input.type === "question"
  const isSentenceItem = isPassage && input.sentenceIndex != null
  const sentenceProgress =
    isSentenceItem && input.sentenceTotal
      ? t({
          zh: `第 ${input.sentenceIndex}/${input.sentenceTotal} 句`,
          en: `Sentence ${input.sentenceIndex}/${input.sentenceTotal}`,
        })
      : null

  const promptLabel = input.examKind
    ? t(
        EXAM_KIND_LABELS[input.examKind] ?? {
          zh: input.examKind,
          en: input.examKind,
        },
      )
    : isInstruction
      ? t({
          zh: "INSTRUCTIONS · 读一读再继续",
          en: "INSTRUCTIONS · Read before continuing",
        })
      : isQuestion
        ? t({
            zh: "YOUR TURN · 分享你的想法",
            en: "YOUR TURN · Share your thoughts",
          })
        : isSentenceItem
          ? `${t({
              zh: "READ ALOUD · 逐句朗读",
              en: "READ ALOUD · Sentence by sentence",
            })} · ${sentenceProgress}`
          : isPassage
            ? t({
                zh: "READ ALOUD · 大声朗读全文",
                en: "READ ALOUD · Read the full text aloud",
              })
            : t({
                zh: "LISTEN & REPEAT · 听一听，再试着说",
                en: "LISTEN & REPEAT · Listen, then try to say it",
              })

  const hint = isInstruction
    ? t({
        zh: "读完这段说明，点「继续」进入下一题。这一页不用录音。",
        en: "Read this, then tap Continue for the next item. No recording on this page.",
      })
    : isQuestion
      ? t({
          zh: "试着说出你的观点，再用一个理由或小例子支持它。",
          en: "State your opinion, then back it up with a reason or a quick example.",
        })
      : isSentenceItem
        ? t({
            zh: "把这一句读清楚。停顿和语调自然比逐词准确更重要。",
            en: "Read this sentence clearly. Natural pauses and intonation matter more than word-by-word accuracy.",
          })
        : isPassage
          ? t({
              zh: "先扫一眼生词，然后完整朗读。停顿和语调自然比逐词准确更重要。",
              en: "Skim the new words first, then read it through. Natural pauses and intonation matter more than word-by-word accuracy.",
            })
          : t({
              zh: "先听完整句子，再跟着节奏说。比起说得快，说得自然更重要。",
              en: "Listen to the full sentence first, then follow its rhythm. Sounding natural beats speaking fast.",
            })

  return { isPassage, isInstruction, isSentenceItem, promptLabel, hint }
}
