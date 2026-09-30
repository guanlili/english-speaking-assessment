import type { TrailData } from "@/client"
import TrailChart from "@/components/Practice/TrailChart"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useI18n } from "@/lib/i18n"
import { TERMS } from "@/lib/terms"

function TrailView({
  trail,
  period = 30,
}: {
  trail: TrailData
  period?: number
}) {
  const { t } = useI18n()
  const allSessions = trail.sessions
  const cutoff = new Date(Date.now() - period * 86400000)
    .toISOString()
    .slice(0, 10)
  const sessions = allSessions.filter((x) => x.date >= cutoff)
  const hasTrend = sessions.length >= 2 // PRD US-09：少于 2 次不画趋势，只列表

  const speakingPoints = sessions.map((s) => ({
    label: s.date,
    value: s.speaking_avg ?? null,
  }))
  return (
    <div className="flex flex-col gap-6">
      {hasTrend ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t(TERMS.score)}</CardTitle>
            <CardDescription>
              {t({
                zh: "每日情景问答的参考分均值，不是考试成绩。",
                en: "Daily average of Scenario Q&A reference scores — not exam results.",
              })}
            </CardDescription>
          </CardHeader>
          <CardContent className="text-primary">
            <TrailChart title="" points={speakingPoints} min={0} max={100} />
          </CardContent>
        </Card>
      ) : null}

      {!hasTrend && (
        <Card>
          <CardContent className="py-6 text-center text-muted-foreground">
            {t({
              zh: "练习满 2 次后这里会出现口语参考分的变化曲线。",
              en: "After 2 practice rounds, your reference score trend will appear here.",
            })}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t({ zh: "每次练习", en: "Practice sessions" })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: "跟读完整度单独列出，不混进参考分（PRD 口径）。",
              en: "Read-along completeness is listed separately, not mixed into reference scores.",
            })}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {sessions.length === 0 ? (
            <p className="py-6 text-center text-muted-foreground">
              {t({
                zh: "还没有练习记录。",
                en: "No practice records yet.",
              })}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t({ zh: "日期", en: "Date" })}</TableHead>
                  <TableHead>{t(TERMS.score)}</TableHead>
                  <TableHead>
                    {t({
                      zh: "跟读完整度",
                      en: "Read-along completeness",
                    })}
                  </TableHead>
                  <TableHead>{t({ zh: "作答数", en: "Attempts" })}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sessions.map((s) => (
                  <TableRow key={s.date}>
                    <TableCell>{s.date}</TableCell>
                    <TableCell>{s.speaking_avg ?? "–"}</TableCell>
                    <TableCell>{s.repeat_completeness_avg ?? "–"}</TableCell>
                    <TableCell>{s.attempt_count ?? 0}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export default TrailView
