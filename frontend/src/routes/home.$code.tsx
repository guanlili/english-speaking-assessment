import { useQuery } from "@tanstack/react-query"
import { createFileRoute, useNavigate, useParams } from "@tanstack/react-router"
import {
  ArrowRight,
  CheckCircle2,
  Flame,
  Headphones,
  Sparkles,
  Star,
} from "lucide-react"
import { useEffect, useState } from "react"
import { ClassesService } from "@/client"
import StudentShell from "@/components/Practice/StudentShell"
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
  readWeekGoal,
  writeWeekGoal,
} from "@/lib/classroom-student"

export const Route = createFileRoute("/home/$code")({
  component: HomePage,
  head: () => ({ meta: [{ title: `学习首页 - ${APP_NAME}` }] }),
})

const QUOTES = [
  { en: "Progress, not perfection.", zh: "比完美更重要的，是又迈出了一小步。" },
  { en: "Every voice counts.", zh: "每一种声音，都值得被听见。" },
  { en: "Small steps, big dreams.", zh: "每一小步，都通向更大的世界。" },
  { en: "Say it your way.", zh: "用你自己的方式，说出你的想法。" },
  { en: "Practice makes progress.", zh: "练习的终点不是完美，是进步。" },
  { en: "Brave before perfect.", zh: "先勇敢，再完美。" },
  { en: "Speak from the heart.", zh: "从心里说出来的话，最有力量。" },
]

function HomePage() {
  const { code } = useParams({ from: "/home/$code" })
  const navigate = useNavigate({ from: "/home/$code" })
  const student = loadStudent(code)

  useEffect(() => {
    if (student === null) {
      void navigate({ to: "/j/$code", params: { code } })
    }
  }, [student, code, navigate])

  const [goalPicker, setGoalPicker] = useState(false)

  const todayQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: ["classroom", code, "today", student?.id],
    queryFn: () =>
      ClassesService.readTodayPlan({
        code: code.toUpperCase(),
        studentId: student?.id as string,
      }),
    enabled: student !== null,
  })

  // 身份失效（清库/课堂重建后 404）：清除本地身份，引导重新进入
  useEffect(() => {
    if (todayQuery.isError && isStudentNotFound(todayQuery.error)) {
      clearStudent(code)
      void navigate({ to: "/j/$code", params: { code } })
    }
  }, [todayQuery.isError, todayQuery.error, code, navigate])

  const trailQuery = useQuery({
    queryKey: ["classroom", code, "trail", student?.id],
    queryFn: () =>
      ClassesService.readStudentTrail({
        code: code.toUpperCase(),
        studentId: student?.id as string,
      }),
    enabled: student !== null,
  })

  if (student === null) return null

  const plan = todayQuery.data
  const g = plan?.gamification
  const done = plan
    ? plan.attempts.filter((a) => a.status === "done" || a.status === "failed")
        .length
    : 0
  const totalItems = plan?.items.length ?? 5

  // 周目标：trail 近 7 天有练习的天数
  const weekGoal = readWeekGoal()
  const practicedDates = new Set(
    (trailQuery.data?.sessions ?? [])
      .map((s) => s.date)
      .filter((d) => {
        const days = (Date.now() - new Date(d).getTime()) / 86400000
        return days <= 7
      }),
  )
  const weekDone = practicedDates.size
  const ring = Math.min(weekDone / weekGoal, 1)

  const quote = QUOTES[new Date().getDay() % QUOTES.length]

  return (
    <StudentShell active="home">
      <div className="flex flex-col gap-5">
        {/* Hero */}
        <section className="relative overflow-hidden rounded-3xl bg-secondary p-7">
          <div
            className="absolute -top-28 -right-20 size-60 rounded-full border"
            aria-hidden
          />
          <div className="relative z-10 max-w-[70%]">
            <p className="text-[10px] font-bold tracking-[0.2em] text-primary">
              A LITTLE PRACTICE. A BIG DIFFERENCE.
            </p>
            <h1 className="mt-3 text-2xl leading-snug font-bold tracking-tight md:text-3xl">
              Hi，{displayName(student)}
              <span className="text-primary">。</span>
              <br />
              今天也给自己一点开口的勇气吧。
            </h1>
            {plan?.assigned_unit_title && (
              <p className="mt-2 text-xs font-medium text-primary">
                📌 今日课堂：{plan.assigned_unit_title}（老师指派）
              </p>
            )}
            <div className="mt-5 flex items-center gap-3">
              <Button
                onClick={() =>
                  void navigate({ to: "/p/$code", params: { code } })
                }
              >
                {done >= totalItems
                  ? "查看今日成果"
                  : done > 0
                    ? "继续今天的练习"
                    : "开始今天的练习"}
                <ArrowRight />
              </Button>
              <span className="hidden text-[11px] text-muted-foreground md:inline">
                轻松开口，不怕说错
              </span>
            </div>
          </div>
        </section>

        {/* 今日计划 */}
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <div className="flex items-center gap-3">
              <span className="flex size-10 items-center justify-center rounded-xl bg-secondary text-primary">
                <Headphones className="size-5" />
              </span>
              <div>
                <CardTitle className="text-base">今天的开口计划</CardTitle>
                <CardDescription>
                  {plan?.assigned_unit_title ?? "个人关卡"} · 3 句复述 + 2
                  道问答
                </CardDescription>
              </div>
            </div>
            <span className="rounded-md bg-background px-2 py-1 text-[11px] text-muted-foreground">
              约 10 分钟
            </span>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-3">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-background">
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{ width: `${(done / totalItems) * 100}%` }}
                />
              </div>
              <span className="text-[11px] text-muted-foreground">
                {done} / {totalItems} 已完成
              </span>
            </div>
            <div className="flex items-center gap-3 border-t pt-3.5">
              <span className="flex size-8 items-center justify-center rounded-full bg-background text-xs text-muted-foreground">
                01
              </span>
              <div className="flex-1">
                <p className="text-sm font-semibold">先听一听，再说一说</p>
                <p className="text-xs text-muted-foreground">
                  听后复述 · 让熟悉的表达自然说出口
                </p>
              </div>
              <span className="text-xs text-muted-foreground">3 个短句</span>
            </div>
            <div className="flex items-center gap-3 border-t pt-3.5">
              <span className="flex size-8 items-center justify-center rounded-full bg-background text-xs text-muted-foreground">
                02
              </span>
              <div className="flex-1">
                <p className="text-sm font-semibold">轮到你，分享一点想法</p>
                <p className="text-xs text-muted-foreground">
                  情景问答 · 没有标准答案，你的想法很重要
                </p>
              </div>
              <span className="text-xs text-muted-foreground">2 个问题</span>
            </div>
            <p className="flex items-center gap-1.5 border-t pt-3 text-xs text-muted-foreground">
              <CheckCircle2 className="size-3.5" />
              难度会跟着你的状态调整，每一步都刚刚好。
            </p>
          </CardContent>
        </Card>

        {/* 周目标 + 档位生长 + 金句 */}
        <div className="grid gap-5 md:grid-cols-3">
          <Card>
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <CardTitle className="text-sm">这周，稳稳前进</CardTitle>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs"
                onClick={() => setGoalPicker(!goalPicker)}
              >
                调整目标
              </Button>
            </CardHeader>
            {goalPicker && (
              <CardContent className="pb-0">
                <div className="grid grid-cols-3 gap-2">
                  {[3, 5, 7].map((n) => (
                    <button
                      key={n}
                      type="button"
                      onClick={() => {
                        writeWeekGoal(n)
                        setGoalPicker(false)
                      }}
                      className={
                        weekGoal === n
                          ? "rounded-xl border border-primary bg-secondary py-3 text-center"
                          : "rounded-xl border border-border py-3 text-center hover:bg-background"
                      }
                    >
                      <strong className="block text-xl">{n}</strong>
                      <small className="text-[10px] text-muted-foreground">
                        {{ 3: "慢慢来", 5: "稳稳进步", 7: "每天一点" }[n]}
                      </small>
                    </button>
                  ))}
                </div>
              </CardContent>
            )}
            <CardContent className="flex flex-col items-center">
              <div className="relative grid size-32 place-items-center">
                <svg
                  viewBox="0 0 150 150"
                  className="absolute inset-0 size-full -rotate-90"
                  role="img"
                  aria-label={`本周已练习 ${weekDone} 天`}
                >
                  <circle
                    cx="75"
                    cy="75"
                    r="62"
                    fill="none"
                    stroke="var(--muted)"
                    strokeWidth="10"
                  />
                  <circle
                    cx="75"
                    cy="75"
                    r="62"
                    fill="none"
                    stroke="var(--primary)"
                    strokeWidth="10"
                    strokeLinecap="round"
                    strokeDasharray={`${ring * 389.6} 389.6`}
                  />
                </svg>
                <p className="relative text-center">
                  <span className="text-3xl font-bold">{weekDone}</span>
                  <span className="text-base text-muted-foreground">
                    {" "}
                    / {weekGoal} 天
                  </span>
                  <span className="block text-[10px] text-muted-foreground">
                    本周开口目标
                  </span>
                </p>
              </div>
              <p className="mt-3 text-center text-xs text-muted-foreground">
                {weekDone >= weekGoal
                  ? "本周目标已达成，保持自己的节奏"
                  : `再练 ${weekGoal - weekDone} 天，就完成本周小目标`}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">你的表达，正在生长</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="mt-2 text-4xl font-bold">
                {g
                  ? (trailQuery.data?.sessions?.[
                      trailQuery.data.sessions.length - 1
                    ]?.vocab_cefr ?? "–")
                  : "–"}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                词汇参考档位 · 只和自己比
              </p>
              <div className="mt-4 flex gap-1">
                {["A2", "B1", "B2"].map((b) => (
                  <span
                    key={b}
                    className={
                      b === (g ? "B1" : "A2")
                        ? "h-1.5 flex-1 rounded bg-primary"
                        : "h-1.5 flex-1 rounded bg-border"
                    }
                  />
                ))}
              </div>
              <div className="mt-1.5 flex justify-between text-[9px] text-muted-foreground">
                <span>A2 轻松开口</span>
                <span>B1 自在表达</span>
                <span>B2 拓展观点</span>
              </div>
              {g && (
                <p className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
                  <Flame className="size-3.5 text-orange-400" />
                  连胜 {g.streak_days} 天 · {g.xp} XP
                </p>
              )}
            </CardContent>
          </Card>

          <Card className="border-accent bg-accent">
            <CardHeader>
              <CardDescription className="flex items-center gap-1.5 !text-accent-foreground">
                <Sparkles className="size-3.5" /> 给今天的你
              </CardDescription>
            </CardHeader>
            <CardContent>
              <blockquote className="font-serif text-xl leading-relaxed">
                “{quote.en}”
              </blockquote>
              <p className="mt-2 text-xs text-accent-foreground/80">
                {quote.zh}
              </p>
            </CardContent>
          </Card>
        </div>

        {/* 快捷入口 */}
        <div className="flex flex-wrap gap-3">
          <Button
            variant="secondary"
            onClick={() =>
              void navigate({ to: "/explore/$code", params: { code } })
            }
          >
            <Sparkles />
            主题探索
          </Button>
          <Button
            variant="secondary"
            onClick={() => void navigate({ to: "/me/$code", params: { code } })}
          >
            <Star />
            我的成长
          </Button>
        </div>
      </div>
    </StudentShell>
  )
}
