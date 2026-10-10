import type { VocabularyQuizState } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useI18n } from "@/lib/i18n"
import { EXPLAIN_QUIZ_RULES, TERMS } from "@/lib/terms"
import { formatDateTime } from "@/lib/time"

/** 测验规则页：未明确开始不下发题面；这里给出规则与「开始测验」入口。 */
export default function QuizRulesCard({
  quiz,
  assignmentTitle,
  startPending,
  onStart,
}: {
  quiz: VocabularyQuizState
  assignmentTitle: string
  startPending: boolean
  onStart: () => void
}) {
  const { t, lang } = useI18n()
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {t(TERMS.vocabQuiz)} · {assignmentTitle}
        </CardTitle>
        <CardDescription>{t(EXPLAIN_QUIZ_RULES)}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-2xl bg-secondary/50 p-4">
            <dt className="text-xs text-muted-foreground">
              {t(TERMS.quizDuration)}
            </dt>
            <dd className="mt-1 text-lg font-semibold">
              {quiz.duration_minutes} {t({ zh: "分钟", en: "min" })}
            </dd>
          </div>
          <div className="rounded-2xl bg-secondary/50 p-4">
            <dt className="text-xs text-muted-foreground">
              {t(TERMS.passLine)}
            </dt>
            <dd className="mt-1 text-lg font-semibold">
              {quiz.pass_line}
              {t({ zh: " 分", en: " pts" })}
            </dd>
          </div>
          <div className="rounded-2xl bg-secondary/50 p-4">
            <dt className="text-xs text-muted-foreground">
              {t({ zh: "开放 / 截止", en: "Opens / Due" })}
            </dt>
            <dd className="mt-1 text-sm font-medium leading-5">
              {quiz.opens_at
                ? formatDateTime(quiz.opens_at, lang)
                : t({ zh: "已开放", en: "Open now" })}
              <br />
              {quiz.due_at
                ? formatDateTime(quiz.due_at, lang)
                : t({ zh: "无截止", en: "No due" })}
            </dd>
          </div>
          <div className="rounded-2xl bg-secondary/50 p-4">
            <dt className="text-xs text-muted-foreground">
              {t({ zh: "参与次数", en: "Attempts" })}
            </dt>
            <dd className="mt-1 text-lg font-semibold">
              {quiz.attempts_used} / {quiz.attempts_allowed}
              {quiz.retake_granted && (
                <span className="ml-2 text-sm text-muted-foreground">
                  {t({ zh: "老师已授权补考", en: "retake granted" })}
                </span>
              )}
            </dd>
          </div>
        </dl>
        <Button
          size="lg"
          className="h-12 w-full sm:w-auto"
          disabled={startPending}
          onClick={onStart}
        >
          {startPending
            ? t({ zh: "正在开始…", en: "Starting…" })
            : t(TERMS.startQuiz)}
        </Button>
        <p className="text-xs text-muted-foreground">
          {t({
            zh: "点击开始后计时开始：有效结束时间取个人时长与任务截止中较早者。",
            en: "The timer starts on tap: your deadline is the earlier of your time limit and the task due time.",
          })}
        </p>
      </CardContent>
    </Card>
  )
}
