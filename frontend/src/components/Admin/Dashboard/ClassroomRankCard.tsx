import type { DashboardClassroomRow } from "@/client"
import InfoHint from "@/components/Common/InfoHint"
import { Badge } from "@/components/ui/badge"
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
import { EXPLAIN } from "@/lib/terms"
import { formatDateTime } from "@/lib/time"

/** 课堂排行：区间作答数降序；沉默课堂横幅提示推动。 */
function ClassroomRankCard({
  classrooms,
  silent,
  pending,
}: {
  classrooms: DashboardClassroomRow[] | undefined
  silent: DashboardClassroomRow[] | undefined
  pending: boolean
}) {
  const { t, lang } = useI18n()

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5 text-base">
          {t({ zh: "课堂使用排行", en: "Classroom usage" })}
          <InfoHint label={t(EXPLAIN.dashboard_active)} />
        </CardTitle>
        <CardDescription>
          {t({
            zh: "按区间内提交作答数降序；最近活跃为历史最近一次提交。",
            en: "Sorted by attempts in range; last active is the latest attempt ever.",
          })}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {silent && silent.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-amber-500/30 bg-amber-500/5 p-3 text-sm">
            <InfoHint label={t(EXPLAIN.dashboard_silent)} side="right" />
            <span className="font-medium">
              {t({ zh: "沉默课堂", en: "Silent classrooms" })}
            </span>
            {silent.slice(0, 6).map((c) => (
              <Badge key={c.classroom_id} variant="outline" className="gap-1">
                {c.name}
                <span className="text-muted-foreground">
                  {c.silent_days}
                  {t({ zh: "天", en: "d" })}
                </span>
              </Badge>
            ))}
            {silent.length > 6 ? (
              <span className="text-muted-foreground">
                {t({
                  zh: `等 ${silent.length} 个`,
                  en: `${silent.length} total`,
                })}
              </span>
            ) : null}
          </div>
        ) : null}
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t({ zh: "课堂", en: "Classroom" })}</TableHead>
                <TableHead className="hidden md:table-cell">
                  {t({ zh: "教师", en: "Teacher" })}
                </TableHead>
                <TableHead className="text-right">
                  {t({ zh: "学生", en: "Students" })}
                </TableHead>
                <TableHead className="text-right">
                  {t({ zh: "区间作答", en: "In range" })}
                </TableHead>
                <TableHead className="text-right">
                  {t({ zh: "平均分", en: "Avg" })}
                </TableHead>
                <TableHead className="hidden lg:table-cell text-right">
                  {t({ zh: "累计作答", en: "All time" })}
                </TableHead>
                <TableHead className="hidden lg:table-cell">
                  {t({ zh: "最近活跃", en: "Last active" })}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pending ? (
                <TableRow>
                  <TableCell
                    colSpan={7}
                    className="py-6 text-center text-muted-foreground"
                  >
                    {t({ zh: "正在加载…", en: "Loading…" })}
                  </TableCell>
                </TableRow>
              ) : !classrooms || classrooms.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={7}
                    className="py-6 text-center text-muted-foreground"
                  >
                    {t({ zh: "还没有课堂。", en: "No classrooms yet." })}
                  </TableCell>
                </TableRow>
              ) : (
                classrooms.map((c) => (
                  <TableRow key={c.classroom_id}>
                    <TableCell className="font-medium">
                      {c.name}
                      <span className="ml-1 text-xs text-muted-foreground">
                        {c.code}
                      </span>
                    </TableCell>
                    <TableCell className="hidden md:table-cell text-muted-foreground">
                      {c.owner_name ?? "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {c.students}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {c.attempts}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {c.avg_score ?? "—"}
                    </TableCell>
                    <TableCell className="hidden lg:table-cell text-right tabular-nums text-muted-foreground">
                      {c.attempts_all}
                    </TableCell>
                    <TableCell className="hidden lg:table-cell text-muted-foreground">
                      {c.last_active ? formatDateTime(c.last_active, lang) : "—"}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

export default ClassroomRankCard
