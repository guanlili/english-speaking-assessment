import { Link } from "@tanstack/react-router"
import { ArrowRight, RotateCcw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"
import { EXPLAIN_QUIZ_PUBLISH, TERMS } from "@/lib/terms"
import { SubmitQuizButton } from "./SubmitQuizButton"

/**
 * 走完全部题后的收尾区：测验=交卷提醒/公布说明；练习=完成统计+再练一轮。
 * AI 学情入口（测验=整场洞察；练习=本轮洞察）也在这里。
 */
export default function FinishBanner({
  code,
  isQuiz,
  quizFinished,
  quizStatus,
  sessionId,
  onQuizSubmitted,
  allDone,
  hasAnswer,
  answeredCount,
  correctFirst,
  onOpenInsight,
  canNewRound,
  newRoundPending,
  onNewRound,
}: {
  code: string
  isQuiz: boolean
  quizFinished: boolean
  quizStatus: string | undefined
  sessionId: string | null
  onQuizSubmitted: () => void
  allDone: boolean
  hasAnswer: boolean
  answeredCount: number
  correctFirst: number
  onOpenInsight: () => void
  canNewRound: boolean
  newRoundPending: boolean
  onNewRound: () => void
}) {
  const { t } = useI18n()
  return (
    <>
      {isQuiz && quizFinished && (
        <Button variant="outline" onClick={onOpenInsight}>
          {t(TERMS.aiSessionInsight)}
        </Button>
      )}
      {isQuiz && allDone && (
        <div className="rounded-2xl border border-primary/20 bg-secondary/40 p-4">
          <p className="text-sm font-semibold">
            {quizStatus === "in_progress"
              ? t({
                  zh: "全部题目已提交。确认无误就交卷；到时间也会自动交卷。",
                  en: "All items submitted. Submit to finish — auto-submit at time-up either way.",
                })
              : t(EXPLAIN_QUIZ_PUBLISH)}
          </p>
          {quizStatus === "in_progress" && (
            <div className="mt-3">
              <SubmitQuizButton
                sessionId={sessionId}
                disabled={!sessionId}
                onDone={onQuizSubmitted}
              />
            </div>
          )}
          {quizStatus !== "in_progress" && (
            <div className="mt-3">
              <Button asChild size="sm" variant="outline">
                <Link to="/vocab/$code" params={{ code }}>
                  {t({ zh: "回词汇首页", en: "Back to Vocabulary home" })}
                  <ArrowRight />
                </Link>
              </Button>
            </div>
          )}
        </div>
      )}
      {!isQuiz && allDone && hasAnswer && (
        <Button variant="outline" className="w-fit" onClick={onOpenInsight}>
          {t(TERMS.aiSessionInsight)}
        </Button>
      )}
      {!isQuiz && allDone && hasAnswer && (
        <div className="rounded-2xl border border-primary/20 bg-secondary/40 p-4">
          <p className="text-sm font-semibold">
            {t({
              zh: `这一轮完成了：${answeredCount} 词，首答正确 ${correctFirst} 个。`,
              en: `Round complete: ${answeredCount} words, ${correctFirst} correct on first try.`,
            })}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {t({
              zh: "这一轮已单独记录，不改变任务成绩（任务成绩始终看第一轮）。想再练可以开新的一轮。",
              en: "This round is recorded separately — task scores always come from the first round. Start a new round to practice again.",
            })}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button asChild size="sm" variant="outline">
              <Link to="/vocab/$code" params={{ code }}>
                {t({ zh: "回词汇首页", en: "Back to Vocabulary home" })}
                <ArrowRight />
              </Link>
            </Button>
            {canNewRound && (
              <Button size="sm" disabled={newRoundPending} onClick={onNewRound}>
                <RotateCcw />
                {t({ zh: "再练一轮", en: "New round" })}
              </Button>
            )}
          </div>
        </div>
      )}
    </>
  )
}
