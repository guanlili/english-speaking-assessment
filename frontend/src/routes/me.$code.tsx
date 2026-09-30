import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link, useParams } from "@tanstack/react-router"
import { BookOpen, Flame, Mic, Sparkles, Star, Trophy } from "lucide-react"
import { useState } from "react"
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
import { useStudentGuard } from "@/hooks/useStudentGuard"
import { displayName, loadStudent } from "@/lib/classroom-student"
import { readSavedExpressions } from "@/lib/favorites"
import { useI18n } from "@/lib/i18n"
import { EXPLAIN, TERMS } from "@/lib/terms"

export const Route = createFileRoute("/me/$code")({
  component: MyTrailPage,
  head: () => ({
    meta: [{ title: `我的成长 / My Growth - ${APP_NAME}` }],
  }),
})

function MyTrailPage() {
  const { t } = useI18n()
  const { code } = useParams({ from: "/me/$code" })
  const student = loadStudent(code)

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

  useStudentGuard(code, student, trailQuery)

  if (student === null) return null

  // 只读当前登录学生的收藏；旧的无归属收藏不再展示给任何登录者
  const savedExpressions = readSavedExpressions(student)

  return (
    <StudentShell active="me">
      <div className="flex flex-col gap-6">
        {trailQuery.data && (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Card>
              <CardContent className="py-4">
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Mic className="size-3.5" />{" "}
                  {t({ zh: "累计开口", en: "Total speaking" })}
                  <InfoHint
                    label={t({
                      zh: "练习录音的累计时长（分钟）。",
                      en: "Total length of your practice recordings (minutes).",
                    })}
                  />
                </p>
                <p className="mt-1 text-2xl font-bold">
                  {trailQuery.data.total_minutes ?? 0}
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    {t({ zh: "分钟", en: "min" })}
                  </span>
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="py-4">
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Trophy className="size-3.5" />{" "}
                  {t({ zh: "完成练习", en: "Completed rounds" })}
                  <InfoHint
                    label={t({
                      zh: "已结算出分的练习轮数。",
                      en: "Practice rounds that have received scores.",
                    })}
                  />
                </p>
                <p className="mt-1 text-2xl font-bold">
                  {trailQuery.data.sessions?.length ?? 0}
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    {t({ zh: "次", en: "rounds" })}
                  </span>
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="py-4">
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Flame className="size-3.5" />{" "}
                  {t({ zh: "坚持练习", en: "Keep going" })}
                  <InfoHint label={t(EXPLAIN.streak)} />
                </p>
                <p className="mt-1 text-2xl font-bold">
                  {todayQuery.data?.gamification?.streak_days ?? 0}
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    {t({ zh: "天", en: "days" })}
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
                <BookOpen className="size-4 text-primary" />{" "}
                {t({
                  zh: "词汇，也在慢慢生长",
                  en: "Your vocabulary is growing too",
                })}
              </CardTitle>
              <CardDescription>
                {t({
                  zh: "累计命中表达次数 · 来源：词表分析",
                  en: "Total expression hits · source: wordlist analysis",
                })}
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
                  {t({ zh: "次命中", en: "hits" })}
                </span>
              </div>
              <p className="pt-1 text-xs text-muted-foreground">
                {t({
                  zh: "用过的表达越多，越容易在真实交流中自然说出来。",
                  en: "The more expressions you've used, the more naturally they come out in real conversations.",
                })}
              </p>
            </CardContent>
          </Card>
        )}

        {todayQuery.data?.gamification && (
          <div className="flex flex-wrap items-center gap-4 rounded-lg border px-4 py-3">
            <span className="flex items-center gap-1 text-sm font-semibold">
              <Sparkles className="size-4 text-primary" />
              {todayQuery.data.gamification.xp} XP
              <InfoHint label={t(EXPLAIN.xp)} />
            </span>
            <span className="flex items-center gap-1 text-sm text-muted-foreground">
              <Flame className="size-4 text-orange-500" />
              {t({
                zh: `连胜 ${todayQuery.data.gamification.streak_days} 天`,
                en: `Streak ${todayQuery.data.gamification.streak_days} days`,
              })}
              <InfoHint label={t(EXPLAIN.streak)} />
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
            <h1 className="text-xl font-bold tracking-tight">
              {t(TERMS.growthPage)}
            </h1>
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              {displayName(student)} ·{" "}
              {t({
                zh: `课堂 ${code.toUpperCase()}`,
                en: `Classroom ${code.toUpperCase()}`,
              })}
            </p>
          </div>
          <Button variant="outline" size="sm" asChild>
            <Link to="/p/$code" params={{ code }}>
              {t({ zh: "回练习页", en: "Back to practice" })}
            </Link>
          </Button>
        </div>

        {trailQuery.isPending ? (
          <p className="py-10 text-center text-muted-foreground">
            {t({ zh: "正在加载…", en: "Loading…" })}
          </p>
        ) : trailQuery.isError || !trailQuery.data ? (
          <p className="py-10 text-center text-muted-foreground">
            {t({
              zh: "加载失败，请刷新重试。",
              en: "Failed to load — please refresh and retry.",
            })}
          </p>
        ) : (
          <>
            <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
              <div className="flex gap-1 rounded-xl bg-secondary/60 p-1">
                {(
                  [
                    ["trail", t(TERMS.trailPage)],
                    ["saved", t({ zh: "表达收藏", en: "Saved expressions" })],
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
                      {t({ zh: `近 ${n} 天`, en: `Last ${n} days` })}
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
              <CardTitle className="text-base">
                {t({ zh: "留住好表达", en: "Keep the great expressions" })}
              </CardTitle>
              <CardDescription>
                {t({
                  zh: "练习中收藏的升级表达，下次试着用出来。",
                  en: "Upgraded expressions you saved during practice — try using them next time.",
                })}
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
          {t({
            zh: "参考数据，不是考试成绩或官方等级。",
            en: "Reference data, not exam results or official levels.",
          })}
        </p>
      </div>
    </StudentShell>
  )
}
