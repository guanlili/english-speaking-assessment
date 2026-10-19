import { useQuery } from "@tanstack/react-query"
import { TrendingUp } from "lucide-react"

import { ClassesService } from "@/client"
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

/** 教师端班级趋势：全班已完成练习按日的均分与活跃度（最近 14 天）。 */
function ClassTrendCard({ code }: { code: string }) {
  const { t } = useI18n()
  const trendQuery = useQuery({
    queryKey: ["teacher", "trend", code],
    queryFn: () =>
      ClassesService.readClassTrend({ code: code.toUpperCase(), days: 14 }),
  })

  const days = trendQuery.data ?? []
  const speakingPoints = days.map((d) => ({
    label: d.date,
    value: d.question_avg ?? null,
  }))
  const hasData = speakingPoints.some((p) => p.value !== null)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5 text-base">
          <TrendingUp className="size-4 text-primary" />
          {t({ zh: "班级趋势", en: "Class trend" })}
        </CardTitle>
        <CardDescription>
          {t({
            zh: "最近 14 天全班已完成练习的问答均分与活跃度；考试未终结的轮次不计入。",
            en: "Daily class averages over the last 14 days — exams still in progress are excluded.",
          })}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {trendQuery.isPending ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {t({ zh: "正在加载…", en: "Loading…" })}
          </p>
        ) : !hasData ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {t({
              zh: "还没有已完成的练习数据。",
              en: "No completed practice data yet.",
            })}
          </p>
        ) : (
          <>
            <TrailChart title="" points={speakingPoints} min={0} max={100} />
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t({ zh: "日期", en: "Date" })}</TableHead>
                  <TableHead className="text-right">
                    {t({ zh: "活跃学生", en: "Active" })}
                  </TableHead>
                  <TableHead className="text-right">
                    {t({ zh: "问答均分", en: "Q&A avg" })}
                  </TableHead>
                  <TableHead className="text-right">
                    {t({ zh: "跟读完整度", en: "Repeat avg" })}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {days.map((d) => (
                  <TableRow key={d.date}>
                    <TableCell>{d.date}</TableCell>
                    <TableCell className="text-right">
                      {d.active_students}
                    </TableCell>
                    <TableCell className="text-right">
                      {d.question_avg ?? "–"}
                    </TableCell>
                    <TableCell className="text-right">
                      {d.repeat_completeness_avg ?? "–"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        )}
      </CardContent>
    </Card>
  )
}

export default ClassTrendCard
