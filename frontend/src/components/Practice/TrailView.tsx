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

function TrailView({
  trail,
  period = 30,
}: {
  trail: TrailData
  period?: number
}) {
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
            <CardTitle className="text-base">参考分</CardTitle>
            <CardDescription>
              每日情景问答的参考分均值，不是考试成绩。
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
            练习满 2 次后这里会出现口语参考分的变化曲线。
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">每次练习</CardTitle>
          <CardDescription>
            跟读完整度单独列出，不混进参考分（PRD 口径）。
          </CardDescription>
        </CardHeader>
        <CardContent>
          {sessions.length === 0 ? (
            <p className="py-6 text-center text-muted-foreground">
              还没有练习记录。
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>日期</TableHead>
                  <TableHead>参考分</TableHead>
                  <TableHead>跟读完整度</TableHead>
                  <TableHead>作答数</TableHead>
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
