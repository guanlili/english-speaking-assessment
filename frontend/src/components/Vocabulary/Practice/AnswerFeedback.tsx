import { ArrowRight, CheckCircle2, RotateCcw, XCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"
import { EXPLAIN_QUIZ_PUBLISH, TERMS } from "@/lib/terms"
import type { AnswerState } from "./answer-state"

/** 测验已提交态：只确认接收（不提前泄露答案），提供下一题/刷新。 */
export function QuizSubmittedCard({
  hasNext,
  onNext,
  onRefresh,
}: {
  hasNext: boolean
  onNext: () => void
  onRefresh: () => void
}) {
  const { t } = useI18n()
  return (
    <div
      role="status"
      className="flex items-start gap-3 rounded-2xl border border-primary/30 bg-primary/5 p-4"
    >
      <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-primary" />
      <div className="min-w-0 space-y-1">
        <p className="font-semibold">
          {t({ zh: "答案已提交", en: "Answer submitted" })}
        </p>
        <p className="text-sm text-muted-foreground">
          {t(EXPLAIN_QUIZ_PUBLISH)}
        </p>
      </div>
      <div className="ml-auto flex shrink-0 gap-2 self-center">
        {hasNext ? (
          <Button variant="outline" onClick={onNext}>
            {t({ zh: "下一题", en: "Next item" })}
          </Button>
        ) : (
          <Button variant="outline" onClick={onRefresh}>
            {t({ zh: "刷新状态", en: "Refresh status" })}
          </Button>
        )}
      </div>
    </div>
  )
}

/** 练习即时反馈：对/错 + 正确拼写 + 重试 / 词讲解 / 下一个词。 */
export function PracticeFeedbackCard({
  answer,
  meaningZh,
  typedInput,
  onRetry,
  canExplain,
  onExplain,
  nextLabel,
  onNext,
}: {
  answer: AnswerState
  meaningZh: string
  typedInput: string
  onRetry: () => void
  canExplain: boolean
  onExplain: () => void
  nextLabel: string
  onNext: () => void
}) {
  const { t } = useI18n()
  return (
    <div className="space-y-4">
      <div
        role="status"
        className={`flex items-start gap-3 rounded-2xl border p-4 ${
          answer.isCorrect
            ? "border-primary/30 bg-primary/5"
            : "border-border bg-secondary/50"
        }`}
      >
        {answer.isCorrect ? (
          <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-primary" />
        ) : (
          <XCircle className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
        )}
        <div className="min-w-0 space-y-1">
          <p className="font-semibold">
            {answer.isCorrect
              ? t({ zh: "拼对了！", en: "Correct!" })
              : t({
                  zh: "差一点点，再看看正确拼写。",
                  en: "So close — check the correct spelling.",
                })}
          </p>
          <p className="text-sm">
            <span className="font-semibold">{answer.correctSpelling}</span>
            <span className="ml-2 text-muted-foreground">{meaningZh}</span>
          </p>
          {!answer.isCorrect && typedInput !== "" && (
            <p className="text-sm text-muted-foreground">
              {t({ zh: "你拼的是：", en: "You typed: " })}
              <span className="font-mono">{typedInput}</span>
            </p>
          )}
          {answer.attemptNo > 1 && (
            <p className="text-xs text-muted-foreground">
              {t({
                zh: `第 ${answer.attemptNo} 次尝试（成绩按第一次计算）`,
                en: `Try #${answer.attemptNo} (score counts the first try)`,
              })}
            </p>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {!answer.isCorrect && (
          <Button variant="outline" onClick={onRetry}>
            <RotateCcw />
            {t({ zh: "再试一次", en: "Try again" })}
          </Button>
        )}
        {canExplain && (
          <Button variant="ghost" onClick={onExplain}>
            {t(TERMS.aiWordExplanation)}
          </Button>
        )}
        <Button onClick={onNext}>
          {nextLabel}
          <ArrowRight />
        </Button>
      </div>
    </div>
  )
}
