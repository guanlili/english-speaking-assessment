import type { DashboardPerformance } from "@/client"
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

/** 阈值口径：>5min 黄、>25min 红（QUEUED_STALE_TIMEOUT_S 重投语义）。 */
const QUEUE_WARN_S = 5 * 60
const QUEUE_CRIT_S = 25 * 60

function queueTone(ageS: number | null | undefined): string {
  if (ageS == null) return ""
  if (ageS >= QUEUE_CRIT_S) return "bg-red-500/10 text-red-600"
  if (ageS >= QUEUE_WARN_S) return "bg-amber-500/10 text-amber-600"
  return ""
}

function fmtSeconds(
  t: (bi: { zh: string; en: string }) => string,
  s: number | null | undefined,
): string {
  if (s == null) return "—"
  if (s < 60) return t({ zh: `${Math.round(s)} 秒`, en: `${Math.round(s)}s` })
  return t({
    zh: `${Math.floor(s / 60)} 分 ${Math.round(s % 60)} 秒`,
    en: `${Math.floor(s / 60)}m${Math.round(s % 60)}s`,
  })
}

function fmtBytes(
  _t: (bi: { zh: string; en: string }) => string,
  bytes: number,
): string {
  const gb = bytes / 1024 ** 3
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  return `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`
}

/** 性能与稳定区：实时（30s 轮询）+ 日快照历史。 */
function PerformanceCard({
  data,
  pending,
}: {
  data: DashboardPerformance | undefined
  pending: boolean
}) {
  const { t } = useI18n()
  if (pending || !data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t({ zh: "性能与稳定", en: "Performance & health" })}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="py-6 text-center text-sm text-muted-foreground">
            {t({ zh: "正在加载…", en: "Loading…" })}
          </p>
        </CardContent>
      </Card>
    )
  }

  const rt = data.realtime as {
    scoring?: {
      by_status?: Record<string, number>
      oldest_queued_age_s?: number | null
      workers_configured?: number
      executor_running?: boolean
    }
    db_pool?: {
      pool_size?: number
      checked_in?: number
      checked_out?: number
      overflow?: number
    }
    providers?: Record<
      string,
      {
        calls?: number
        failures?: number
        failure_rate?: number
        avg_seconds?: number
      }
    >
    audio_storage?: { total_bytes?: number; file_count?: number }
    process?: { started_at?: string }
  }
  const scoring = rt.scoring
  const pool = rt.db_pool
  const poolTotal = (pool?.pool_size ?? 0) + (pool?.overflow ?? 0)
  const poolOut = pool?.checked_out ?? 0
  const providers: Array<{ key: string; label: string }> = [
    { key: "asr", label: t({ zh: "语音识别", en: "ASR" }) },
    { key: "llm", label: t({ zh: "语言模型", en: "LLM" }) },
    { key: "tts", label: t({ zh: "语音合成", en: "TTS" }) },
  ]
  const history = [...data.history].reverse().slice(0, 14)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5 text-base">
          {t({ zh: "性能与稳定", en: "Performance & health" })}
          <InfoHint
            label={t({
              zh: "实时数字为进程启动以来的累计（重启归零）；历史为每日快照。",
              en: "Realtime figures accumulate since process start (reset on restart); history is a daily snapshot.",
            })}
          />
        </CardTitle>
        <CardDescription>
          {t({
            zh: "评分队列、引擎失败率、连接池水位与音频存储；异常升高先看这里。",
            en: "Scoring queue, engine failure rates, DB pool level, and audio storage; check here first when something feels off.",
          })}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* 评分队列 */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">
            {t({ zh: "评分队列", en: "Scoring queue" })}
          </span>
          {scoring?.executor_running === false ? (
            <Badge variant="destructive">
              {t({ zh: "worker 未运行", en: "worker down" })}
            </Badge>
          ) : null}
          {Object.entries(scoring?.by_status ?? {}).map(([status, n]) => (
            <Badge key={status} variant="outline" className="tabular-nums">
              {status} {n}
            </Badge>
          ))}
          <span
            className={
              "rounded-md px-2 py-0.5 text-sm tabular-nums " +
              queueTone(scoring?.oldest_queued_age_s)
            }
          >
            {t({ zh: "最老排队", en: "oldest queued" })}:{" "}
            {fmtSeconds(t, scoring?.oldest_queued_age_s)}
          </span>
          <span className="text-xs text-muted-foreground">
            {t({ zh: "worker", en: "workers" })}{" "}
            {scoring?.workers_configured ?? "—"}
          </span>
        </div>

        {/* 引擎失败率 */}
        <div className="grid gap-2 sm:grid-cols-3">
          {providers.map((p) => {
            const stat = rt.providers?.[p.key]
            const rate = stat?.failure_rate ?? 0
            return (
              <div key={p.key} className="rounded-xl border p-3">
                <p className="text-xs text-muted-foreground">{p.label}</p>
                <p className="mt-1 text-sm">
                  {t({ zh: "调用", en: "calls" })}{" "}
                  <span className="font-semibold tabular-nums">
                    {stat?.calls ?? 0}
                  </span>
                  {rate > 0 ? (
                    <span className="ml-2 text-red-600 tabular-nums">
                      {t({ zh: "失败率", en: "fail" })}{" "}
                      {(rate * 100).toFixed(1)}%
                    </span>
                  ) : (
                    <span className="ml-2 text-muted-foreground">
                      {t({ zh: "无失败", en: "no failures" })}
                    </span>
                  )}
                </p>
                <p className="text-xs text-muted-foreground tabular-nums">
                  {t({ zh: "均延迟", en: "avg" })}{" "}
                  {fmtSeconds(t, stat?.avg_seconds ?? 0)}
                </p>
              </div>
            )
          })}
        </div>

        {/* 连接池 + 存储 + 今日异常 */}
        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-xl border p-3">
            <p className="text-xs text-muted-foreground">
              {t({ zh: "数据库连接池", en: "DB pool" })}
            </p>
            <p className="mt-1 text-sm tabular-nums">
              {poolOut} / {poolTotal}
            </p>
            <div className="mt-2 h-2.5 overflow-hidden rounded-full bg-muted">
              <div
                className={
                  "h-full rounded-full " +
                  (poolTotal > 0 && poolOut / poolTotal >= 0.8
                    ? "bg-red-500"
                    : "bg-primary")
                }
                style={{
                  width: `${poolTotal > 0 ? Math.min(100, (poolOut / poolTotal) * 100) : 0}%`,
                }}
              />
            </div>
          </div>
          <div className="rounded-xl border p-3">
            <p className="text-xs text-muted-foreground">
              {t({ zh: "音频存储", en: "Audio storage" })}
            </p>
            <p className="mt-1 text-sm tabular-nums">
              {fmtBytes(t, rt.audio_storage?.total_bytes ?? 0)}
            </p>
            <p className="text-xs text-muted-foreground tabular-nums">
              {t({ zh: "文件", en: "files" })}{" "}
              {rt.audio_storage?.file_count ?? 0}
            </p>
          </div>
          <div className="rounded-xl border p-3">
            <p className="text-xs text-muted-foreground">
              {t({ zh: "今日异常上报", en: "Issues today" })}
            </p>
            <p className="mt-1 text-sm tabular-nums">
              {data.runtime_issues_today}
            </p>
            <p className="text-xs text-muted-foreground">
              {t({
                zh: "设备/音频/上传异常练习轮",
                en: "rounds reporting device/audio/upload issues",
              })}
            </p>
          </div>
        </div>

        {/* 日快照历史 */}
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t({ zh: "日期", en: "Date" })}</TableHead>
                <TableHead className="text-right">
                  {t({ zh: "作答", en: "Attempts" })}
                </TableHead>
                <TableHead className="text-right">
                  {t({ zh: "失败", en: "Failed" })}
                </TableHead>
                <TableHead className="text-right">
                  {t({ zh: "活跃学生", en: "Active" })}
                </TableHead>
                <TableHead className="hidden md:table-cell text-right">
                  {t({ zh: "排队峰值", en: "Queue peak" })}
                </TableHead>
                <TableHead className="hidden md:table-cell text-right">
                  {t({ zh: "池峰值", en: "Pool peak" })}
                </TableHead>
                <TableHead className="hidden lg:table-cell text-right">
                  {t({ zh: "引擎失败", en: "Engine failures" })}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {history.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={7}
                    className="py-6 text-center text-muted-foreground"
                  >
                    {t({
                      zh: "还没有日快照（部署后次日起累积）。",
                      en: "No daily snapshots yet (they accumulate from the day after deploy).",
                    })}
                  </TableCell>
                </TableRow>
              ) : (
                history.map((h) => (
                  <TableRow key={h.date}>
                    <TableCell className="tabular-nums">{h.date}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {h.attempts}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {h.attempts_failed || "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {h.active_students}
                    </TableCell>
                    <TableCell className="hidden md:table-cell text-right tabular-nums">
                      {h.queue_max_age_s != null
                        ? fmtSeconds(t, h.queue_max_age_s)
                        : "—"}
                    </TableCell>
                    <TableCell className="hidden md:table-cell text-right tabular-nums">
                      {h.pool_max_checked_out ?? "—"}
                    </TableCell>
                    <TableCell className="hidden lg:table-cell text-right tabular-nums">
                      {h.provider_failures
                        ? Object.values(h.provider_failures).reduce(
                            (a, b) => a + b,
                            0,
                          ) || "—"
                        : "—"}
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

export default PerformanceCard
