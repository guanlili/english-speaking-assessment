import { Link } from "@tanstack/react-router"
import { ArrowRight, CheckCircle2, Circle, XCircle } from "lucide-react"
import type { VocabularyStudentPlan } from "@/client"
import InfoHint from "@/components/Common/InfoHint"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useI18n } from "@/lib/i18n"
import { EXPLAIN_FIRST_TRY_ACCURACY, EXPLAIN_ROUND_TIMES } from "@/lib/terms"
import { formatDateTime } from "@/lib/time"

export /** 本轮报告：口径分开——正确率分母=已答，完成进度分母=总题数 */
function RoundReport({
  plan,
  accuracy,
  kindLabel,
  code,
}: {
  plan: VocabularyStudentPlan
  accuracy: number | null
  kindLabel: string
  code: string
}) {
  const { t, lang } = useI18n()
  const answered = plan.answered_count ?? 0
  const total = plan.total_count ?? 0
  const items = plan.items ?? []
  const wrongItems = items.filter(
    (it) => it.answered && it.is_correct === false,
  )
  const correctedWrong = items.filter(
    (it) => it.from_wrong && it.is_correct === true,
  )
  const fmtTime = (value?: string | null) =>
    value ? formatDateTime(value, lang) : "–"

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {t({ zh: "本轮报告", en: "Round Report" })}
          <Badge variant="outline" className="ml-2 text-muted-foreground">
            {kindLabel}
          </Badge>
        </CardTitle>
        <CardDescription>
          {t({
            zh: `已答 ${answered} / ${total} 题（完成进度按本轮总题数计）`,
            en: `${answered} / ${total} answered (progress counts this round's total items)`,
          })}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-2 sm:grid-cols-3">
          <div className="rounded-2xl bg-secondary/50 p-4">
            <p className="text-xs text-muted-foreground">
              {t({ zh: "首答正确数", en: "Correct on first try" })}
            </p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">
              {plan.correct_first_count ?? 0}
            </p>
          </div>
          <div className="rounded-2xl bg-secondary/50 p-4">
            <p className="text-xs text-muted-foreground">
              {t({ zh: "首答正确率", en: "First-try accuracy" })}
              <InfoHint label={t(EXPLAIN_FIRST_TRY_ACCURACY)} />
            </p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">
              {accuracy === null
                ? t({ zh: "未作答", en: "Not answered" })
                : `${accuracy}%`}
            </p>
          </div>
          <div className="rounded-2xl bg-secondary/50 p-4">
            <p className="text-xs text-muted-foreground">
              {t({ zh: "本轮起止", en: "Round times" })}
              <InfoHint label={t(EXPLAIN_ROUND_TIMES)} />
            </p>
            <p className="mt-1 text-sm font-medium leading-5">
              {fmtTime(plan.started_at)}
              <br />
              ↓<br />
              {fmtTime(plan.submitted_at)}
            </p>
          </div>
        </div>

        {correctedWrong.length > 0 && (
          <div className="rounded-2xl border border-primary/20 bg-primary/5 p-4">
            <p className="text-sm font-semibold">
              {t({
                zh: `本轮纠正了 ${correctedWrong.length} 个历史错词。`,
                en: `You corrected ${correctedWrong.length} previously missed word(s) this round.`,
              })}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {t({
                zh: "它们仍会留在错词本里，多练几轮再放心。",
                en: "They stay in your Wrong Words book — a few more rounds to be sure.",
              })}
            </p>
          </div>
        )}

        {wrongItems.length > 0 && (
          <div>
            <p className="mb-2 text-sm font-medium">
              {t({
                zh: `本轮拼错的词（${wrongItems.length}）`,
                en: `Missed this round (${wrongItems.length})`,
              })}
            </p>
            <ul className="grid gap-1.5 sm:grid-cols-2">
              {wrongItems.map((it) => (
                <li
                  key={it.item_index}
                  className="min-w-0 flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-xl border px-3 py-2"
                >
                  <span className="max-w-full break-all text-sm font-semibold">
                    {it.headword}
                  </span>
                  <span className="min-w-0 flex-1 basis-24 truncate text-xs text-muted-foreground">
                    {it.meaning_zh}
                  </span>
                  {it.first_answer && (
                    <span className="max-w-full truncate font-mono text-xs text-muted-foreground line-through">
                      {it.first_answer}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div>
          <p className="mb-2 text-sm font-medium">
            {t({ zh: "正确拼写对答案", en: "Correct spellings" })}
          </p>
          <ul className="grid gap-1.5 sm:grid-cols-2">
            {items.map((it) => (
              <li
                key={it.item_index}
                className="flex items-center gap-2 rounded-xl border px-3 py-2"
              >
                {it.answered ? (
                  it.is_correct ? (
                    <CheckCircle2 className="size-4 shrink-0 text-primary" />
                  ) : (
                    <XCircle className="size-4 shrink-0 text-muted-foreground" />
                  )
                ) : (
                  <Circle className="size-4 shrink-0 text-border" />
                )}
                <span className="min-w-0 flex-1 truncate text-sm">
                  {it.answered && it.headword ? (
                    <span className="font-semibold">{it.headword}</span>
                  ) : (
                    <span className="text-muted-foreground">?</span>
                  )}
                  <span className="ml-2 text-muted-foreground">
                    {it.meaning_zh}
                  </span>
                </span>
              </li>
            ))}
          </ul>
          {answered < total && (
            <p className="mt-2 text-xs text-muted-foreground">
              {t({
                zh: `还有 ${total - answered} 题未作答，不显示拼写。`,
                en: `${total - answered} item(s) unanswered — spellings stay hidden.`,
              })}
            </p>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          <Button asChild size="sm" variant="outline">
            <Link to="/vocab/$code/records" params={{ code }}>
              {t({ zh: "查看练习记录", en: "View Practice Records" })}
              <ArrowRight />
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
