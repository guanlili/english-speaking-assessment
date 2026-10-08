import type { VocabularyTodayItem } from "@/client"
import { useI18n } from "@/lib/i18n"
import { type AnswerState, QUIZ_SUBMITTED_DOT } from "./answer-state"

/** 进度点：点选跳题；对=主色、错=灰、当前=实心。测验已提交显示统一占位态。 */
export default function ProgressDots({
  items,
  answers,
  quizLocalSubmitted,
  isQuiz,
  current,
  onSelect,
}: {
  items: VocabularyTodayItem[]
  answers: Record<number, AnswerState>
  quizLocalSubmitted: Record<number, true>
  isQuiz: boolean
  current: number
  onSelect: (index: number) => void
}) {
  const { t } = useI18n()
  return (
    <ul
      className="flex flex-wrap gap-1.5"
      aria-label={t({ zh: "作答进度", en: "Answer progress" })}
    >
      {items.map((it, index) => {
        const state =
          answers[it.item_index] ??
          (isQuiz && (it.answered || quizLocalSubmitted[it.item_index])
            ? QUIZ_SUBMITTED_DOT
            : undefined)
        return (
          <li key={it.item_index}>
            <button
              type="button"
              aria-label={t({
                zh: `第 ${index + 1} 题${state ? (isQuiz ? "（已提交）" : state.isCorrect ? "（对）" : "（错）") : "（未答）"}`,
                en: `Item ${index + 1}${state ? (isQuiz ? " (submitted)" : state.isCorrect ? " (correct)" : " (missed)") : " (not answered)"}`,
              })}
              aria-current={index === current ? "true" : undefined}
              onClick={() => onSelect(index)}
              className={`size-11 rounded-xl border text-sm font-semibold transition-colors ${
                index === current
                  ? "border-primary bg-primary text-primary-foreground"
                  : state
                    ? state.isCorrect && !isQuiz
                      ? "border-primary/30 bg-secondary text-primary"
                      : "border-border bg-secondary/60 text-muted-foreground"
                    : "border-border text-muted-foreground hover:border-primary/40"
              }`}
            >
              {index + 1}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
