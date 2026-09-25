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

// 词汇档映射为数值画线（A2=1 / B1=2 / B2=3）
const BAND_VALUES: Record<string, number> = { A2: 1, B1: 2, B2: 3 }
const BAND_LABELS = ["", "A2", "B1", "B2"]

function TrailView({ trail }: { trail: TrailData }) {
  const sessions = trail.sessions
  const hasTrend = sessions.length >= 2 // PRD US-09：少于 2 次不画趋势，只列表

  const speakingPoints = sessions.map((s) => ({
    label: s.date,
    value: s.speaking_avg ?? null,
  }))
  const vocabPoints = sessions.map((s) => ({
    label: s.date,
    value: s.vocab_cefr ? (BAND_VALUES[s.vocab_cefr] ?? null) : null,
  }))

  return (
    <div className="flex flex-col gap-6">
      {hasTrend ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">口语参考分</CardTitle>
            <CardDescription>
              每日情景问答的总评均值。参考分，不是考试成绩。
            </CardDescription>
          </CardHeader>
          <CardContent className="text-primary">
            <TrailChart title="" points={speakingPoints} min={0} max={100} />
          </CardContent>
        </Card>
      ) : null}

      {hasTrend ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">词汇参考档</CardTitle>
            <CardDescription>
              按词表命中给出的 CEFR 参考（A2/B1/B2）。参考等级，不是官方证书。
            </CardDescription>
          </CardHeader>
          <CardContent className="text-primary">
            <TrailChart
              title=""
              points={vocabPoints}
              min={1}
              max={3}
              formatValue={(v) => BAND_LABELS[v] ?? String(v)}
            />
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="py-6 text-center text-muted-foreground">
            练习满 2 次后这里会出现口语分和词汇档的变化曲线。
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">每次练习</CardTitle>
          <CardDescription>
            跟读完整度单独列出，不混进口语参考分（PRD 口径）。
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
                  <TableHead>口语参考分</TableHead>
                  <TableHead>跟读完整度</TableHead>
                  <TableHead>词汇参考档</TableHead>
                  <TableHead>作答数</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sessions.map((s) => (
                  <TableRow key={s.date}>
                    <TableCell>{s.date}</TableCell>
                    <TableCell>{s.speaking_avg ?? "–"}</TableCell>
                    <TableCell>{s.repeat_completeness_avg ?? "–"}</TableCell>
                    <TableCell>{s.vocab_cefr ?? "–"}</TableCell>
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
