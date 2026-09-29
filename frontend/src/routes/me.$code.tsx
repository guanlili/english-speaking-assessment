import { useQuery } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  useNavigate,
  useParams,
} from "@tanstack/react-router"
import { BookOpen, Flame, Mic, Sparkles, Star, Trophy } from "lucide-react"
import { useEffect, useState } from "react"
import { ClassesService } from "@/client"
import InfoHint from "@/components/Common/InfoHint"
import StudentShell from "@/components/Practice/StudentShell"
import TrailView from "@/components/Practice/TrailView"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { APP_NAME } from "@/config"
import {
  clearStudent,
  displayName,
  isStudentNotFound,
  loadStudent,
} from "@/lib/classroom-student"
import { EXPLAIN } from "@/lib/terms"
import { safeLocalStorageGet } from "@/utils"

export const Route = createFileRoute("/me/$code")({
  component: MyTrailPage,
  head: () => ({
    meta: [{ title: `我的成长 - ${APP_NAME}` }],
  }),
})

function MyTrailPage() {
  const { code } = useParams({ from: "/me/$code" })
  const navigate = useNavigate({ from: "/me/$code" })
  const student = loadStudent(code)

  useEffect(() => {
    if (student === null) {
      void navigate({ to: "/j/$code", params: { code } })
    }
  }, [student, code, navigate])

  const [growthTab, setGrowthTab] = useState<"trail" | "saved">("trail")
  const [period, setPeriod] = useState(30)
  const todayQuery = useQuery({
    queryKey: ["classroom", code, "today", student?.id],
    queryFn: () =>
      ClassesService.readTodayPlan({
        code: code.toUpperCase(),
      }),
    enabled: student !== null,
  })

  const trailQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: ["classroom", code, "trail", student?.id],
    queryFn: () =>
      ClassesService.readStudentTrail({
        code: code.toUpperCase(),
      }),
    enabled: student !== null,
  })

  // 身份失效（清库/课堂重建后 404）：清除本地身份，引导重新进入
  useEffect(() => {
    if (trailQuery.isError && isStudentNotFound(trailQuery.error)) {
      clearStudent(code)
      void navigate({ to: "/j/$code", params: { code } })
    }
  }, [trailQuery.isError, trailQuery.error, code, navigate])

  if (student === null) return null

  const savedExpressions = safeLocalStorageGet<string[]>(
    "esa:saved-expressions",
    [],
  )

  return (
    <StudentShell active="me">
      <div className="flex flex-col gap-6">
        {trailQuery.data && (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Card>
              <CardContent className="py-4">
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Mic className="size-3.5" /> 累计开口
                  <InfoHint label="练习录音的累计时长（分钟）。" />
                </p>
                <p className="mt-1 text-2xl font-bold">
                  {trailQuery.data.total_minutes ?? 0}
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    分钟
                  </span>
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="py-4">
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Trophy className="size-3.5" /> 完成练习
                  <InfoHint label="已结算出分的练习轮数。" />
                </p>
                <p className="mt-1 text-2xl font-bold">
                  {trailQuery.data.sessions?.length ?? 0}
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    次
                  </span>
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="py-4">
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Flame className="size-3.5" /> 坚持练习
                  <InfoHint label={EXPLAIN.streak} />
                </p>
                <p className="mt-1 text-2xl font-bold">
                  {todayQuery.data?.gamification?.streak_days ?? 0}
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    天
                  </span>
                </p>
              </CardContent>
            </Card>
          </div>
        )}

        {trailQuery.data && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-1.5 text-base">
                <BookOpen className="size-4 text-primary" /> 词汇，也在慢慢生长
              </CardTitle>
              <CardDescription>
                累计命中表达次数 · 来源：词表分析
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2.5">
              <div className="flex items-end gap-3">
                <span className="text-4xl font-bold tabular-nums">
                  {Object.values(trailQuery.data.vocab_counts ?? {}).reduce(
                    (sum, count) => sum + count,
                    0,
                  )}
                </span>
                <span className="pb-1 text-xs text-muted-foreground">
                  次命中
                </span>
              </div>
              <p className="pt-1 text-xs text-muted-foreground">
                用过的表达越多，越容易在真实交流中自然说出来。
              </p>
            </CardContent>
          </Card>
        )}

        {todayQuery.data?.gamification && (
          <div className="flex flex-wrap items-center gap-4 rounded-lg border px-4 py-3">
            <span className="flex items-center gap-1 text-sm font-semibold">
              <Sparkles className="size-4 text-primary" />
              {todayQuery.data.gamification.xp} XP
              <InfoHint label={EXPLAIN.xp} />
            </span>
            <span className="flex items-center gap-1 text-sm text-muted-foreground">
              <Flame className="size-4 text-orange-500" />
              连胜 {todayQuery.data.gamification.streak_days} 天
              <InfoHint label={EXPLAIN.streak} />
            </span>
            <div className="ml-auto flex flex-wrap gap-2">
              {(todayQuery.data.gamification.badges ?? []).map((b) => (
                <Badge key={b.key} variant="secondary" title={b.description}>
                  <Star className="size-3" /> {b.label}
                </Badge>
              ))}
            </div>
          </div>
        )}

        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold tracking-tight">我的成长</h1>
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              {displayName(student)} · 课堂 {code.toUpperCase()}
            </p>
          </div>
          <Button variant="outline" size="sm" asChild>
            <Link to="/p/$code" params={{ code }}>
              回练习页
            </Link>
          </Button>
        </div>

        {trailQuery.isPending ? (
          <p className="py-10 text-center text-muted-foreground">正在加载…</p>
        ) : trailQuery.isError || !trailQuery.data ? (
          <p className="py-10 text-center text-muted-foreground">
            加载失败，请刷新重试。
          </p>
        ) : (
          <>
            <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
              <div className="flex gap-1 rounded-xl bg-secondary/60 p-1">
                {(
                  [
                    ["trail", "进步轨迹"],
                    ["saved", "表达收藏"],
                  ] as const
                ).map(([v, label]) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => setGrowthTab(v)}
                    className={
                      growthTab === v
                        ? "rounded-lg bg-card px-3 py-1.5 text-xs font-semibold shadow-sm"
                        : "rounded-lg px-3 py-1.5 text-xs text-muted-foreground"
                    }
                  >
                    {label}
                  </button>
                ))}
              </div>
              {growthTab === "trail" && (
                <div className="flex gap-1 rounded-xl bg-secondary/60 p-1">
                  {[7, 30].map((n) => (
                    <button
                      key={n}
                      type="button"
                      onClick={() => setPeriod(n)}
                      className={
                        period === n
                          ? "rounded-lg bg-card px-3 py-1.5 text-xs font-semibold shadow-sm"
                          : "rounded-lg px-3 py-1.5 text-xs text-muted-foreground"
                      }
                    >
                      近 {n} 天
                    </button>
                  ))}
                </div>
              )}
            </div>
            {growthTab === "trail" && (
              <TrailView trail={trailQuery.data} period={period} />
            )}
          </>
        )}

        {growthTab === "saved" && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">留住好表达</CardTitle>
              <CardDescription>
                练习中收藏的升级表达，下次试着用出来。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {savedExpressions.map((e) => (
                <p
                  key={e}
                  className="rounded-lg bg-background px-3 py-2 font-serif text-base"
                >
                  {e}
                </p>
              ))}
            </CardContent>
          </Card>
        )}

        <p className="pb-6 text-center text-xs text-muted-foreground">
          参考数据，不是考试成绩或官方等级。
        </p>
      </div>
    </StudentShell>
  )
}
