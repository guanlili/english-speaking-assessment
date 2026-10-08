import { useQuery } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  useNavigate,
  useParams,
} from "@tanstack/react-router"
import {
  ArrowRight,
  BookA,
  CheckCircle2,
  Flame,
  Headphones,
  Sparkles,
  Star,
  Volume2,
} from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"
import { ClassesService } from "@/client"
import HeroArt from "@/components/Practice/HeroArt"
import StudentShell from "@/components/Practice/StudentShell"
import TopicArt from "@/components/Practice/TopicArt"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { APP_NAME } from "@/config"
import { useStudentGuard } from "@/hooks/useStudentGuard"
import {
  displayName,
  loadStudent,
  readWeekGoal,
  writeWeekGoal,
} from "@/lib/classroom-student"
import { type BiString, useI18n } from "@/lib/i18n"
import { TERMS } from "@/lib/terms"
import { speakEnglish } from "@/lib/tts"

export const Route = createFileRoute("/home/$code")({
  component: HomePage,
  head: () => ({ meta: [{ title: `学习首页 / Home - ${APP_NAME}` }] }),
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

/** 周历表头（周一→周日），双语 */
const WEEKDAYS: BiString[] = [
  { zh: "一", en: "M" },
  { zh: "二", en: "T" },
  { zh: "三", en: "W" },
  { zh: "四", en: "T" },
  { zh: "五", en: "F" },
  { zh: "六", en: "S" },
  { zh: "日", en: "S" },
]

function HomePage() {
  const { t, lang } = useI18n()
  const { code } = useParams({ from: "/home/$code" })
  const navigate = useNavigate({ from: "/home/$code" })
  const student = loadStudent(code)

  const [goalPicker, setGoalPicker] = useState(false)

  const todayQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: ["classroom", code, "today", student?.id],
    queryFn: () =>
      ClassesService.readTodayPlan({
        code: code.toUpperCase(),
      }),
    enabled: student !== null,
  })

  // 身份失效（清库/课堂重建后 404）：清除本地身份，引导重新进入
  useStudentGuard(code, student, todayQuery)

  // 组件卸载时停止语音合成
  useEffect(() => {
    return () => {
      window.speechSynthesis?.cancel()
    }
  }, [])

  const pathQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: ["classroom", code, "path", student?.id],
    queryFn: () =>
      ClassesService.readLearningPath({
        code: code.toUpperCase(),
      }),
    enabled: student !== null,
    staleTime: 60_000,
  })

  const trailQuery = useQuery({
    queryKey: ["classroom", code, "trail", student?.id],
    queryFn: () =>
      ClassesService.readStudentTrail({
        code: code.toUpperCase(),
      }),
    enabled: student !== null,
  })

  if (student === null) return null

  if (todayQuery.isPending) {
    return (
      <StudentShell active="home" wide>
        <div role="status" className="space-y-6">
          <span className="sr-only">
            {t({ zh: "正在加载今日学习计划…", en: "Loading today's plan…" })}
          </span>
          <Skeleton className="h-72 rounded-3xl" />
          <Skeleton className="h-64 rounded-3xl" />
          <div className="grid gap-4 sm:grid-cols-3">
            {[1, 2, 3].map((item) => (
              <Skeleton key={item} className="h-40 rounded-2xl" />
            ))}
          </div>
        </div>
      </StudentShell>
    )
  }

  if (todayQuery.isError) {
    return (
      <StudentShell active="home" wide>
        <Card className="items-center px-6 py-12 text-center">
          <Headphones className="size-10 text-primary" />
          <div role="alert" className="space-y-2">
            <h1 className="text-xl font-semibold">
              {t({
                zh: "学习计划暂时没有加载成功",
                en: "Today's plan failed to load",
              })}
            </h1>
            <p className="text-sm text-muted-foreground">
              {t({
                zh: "请检查网络连接，再试一次。你的练习记录不会丢失。",
                en: "Check your connection and try again. Your practice records are safe.",
              })}
            </p>
          </div>
          <Button
            onClick={() => void todayQuery.refetch()}
            disabled={todayQuery.isFetching}
          >
            {t({ zh: "重新加载", en: "Reload" })}
          </Button>
        </Card>
      </StudentShell>
    )
  }

  const plan = todayQuery.data
  const g = plan?.gamification
  const done = plan
    ? plan.attempts.filter((a) => a.status === "done" || a.status === "failed")
        .length
    : 0
  const totalItems = plan?.items.length ?? 0
  // 题量按本轮实际指派计算：老师勾选的题型不同，结构就不同
  const countType = (type: string) =>
    plan?.items.filter((item) => item.type === type).length ?? 0
  const readingCount = countType("passage")
  const repeatCount = countType("repeat")
  const qaCount = countType("question")
  const planSummary =
    [
      readingCount > 0 &&
        t({
          zh: `${readingCount} 篇朗读`,
          en: `${readingCount} read-aloud`,
        }),
      repeatCount > 0 &&
        t({
          zh: `${repeatCount} 句复述`,
          en: `${repeatCount} listen & repeat`,
        }),
      qaCount > 0 &&
        t({
          zh: `${qaCount} 道情景问答`,
          en: `${qaCount} scenario Q&A`,
        }),
    ]
      .filter(Boolean)
      .join(" + ") ||
    t({ zh: "内容待老师安排", en: "content awaiting your teacher" })

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
    <StudentShell active="home" wide>
      <div className="flex flex-col gap-7">
        <section className="learning-hero relative isolate overflow-hidden rounded-3xl p-6 sm:p-9 lg:p-10">
          <div
            className="pointer-events-none absolute -right-20 -top-28 size-96 rounded-full border border-white/10"
            aria-hidden="true"
          />
          <div
            className="pointer-events-none absolute -bottom-5 right-0 hidden h-[95%] w-[42%] lg:block"
            aria-hidden="true"
          >
            <HeroArt />
          </div>
          <div className="relative z-10 lg:max-w-[65%]">
            <p className="flex items-center gap-2 text-[10px] font-semibold tracking-[0.2em] text-mint">
              <span className="h-px w-6 bg-tan-gold" /> YOUR VOICE MATTERS
            </p>
            <h1 className="mt-5 break-words text-2xl font-semibold leading-snug tracking-tight sm:text-3xl lg:text-4xl">
              {t({
                zh: `Hi，${displayName(student)}。`,
                en: `Hi, ${displayName(student)}.`,
              })}
              <br />
              <span className="text-tan-gold">
                {t({
                  zh: "今天，也勇敢开口。",
                  en: "Be brave and speak up today.",
                })}
              </span>
            </h1>
            <p className="mt-4 text-sm leading-6 text-mint">
              {plan?.assigned_unit_title
                ? t({
                    zh: `今日练习 · ${plan.assigned_unit_title}`,
                    en: `Today's Practice · ${plan.assigned_unit_title}`,
                  })
                : t({
                    zh: "从一次小小的练习，开始你的表达。",
                    en: "Start your speaking journey with one small practice.",
                  })}
            </p>
            <div className="mt-7 flex flex-wrap items-center gap-4">
              <Button
                size="lg"
                className="group bg-tan-soft text-brand-pine shadow-none hover:bg-tan-pale"
                disabled={totalItems === 0}
                onClick={() =>
                  void navigate({ to: "/p/$code", params: { code } })
                }
              >
                {totalItems === 0
                  ? t({ zh: "等待课堂安排", en: "Awaiting today's assignment" })
                  : done >= totalItems
                    ? t({
                        zh: "查看今日成果",
                        en: "See today's results",
                      })
                    : done > 0
                      ? t({
                          zh: "继续今日练习",
                          en: "Continue today's practice",
                        })
                      : t({
                          zh: "开始今日练习",
                          en: "Start today's practice",
                        })}
                <ArrowRight className="transition-transform group-hover:translate-x-1" />
              </Button>
              <span className="text-xs text-mint">
                {t({
                  zh: "轻松开口，不怕说错",
                  en: "Speak freely — mistakes are welcome",
                })}
              </span>
            </div>
          </div>
        </section>

        {/* 今日计划 */}
        <Card>
          <CardHeader className="flex flex-wrap items-center justify-between gap-3 space-y-0">
            <div className="flex items-center gap-3">
              <span className="flex size-10 items-center justify-center rounded-xl bg-secondary text-primary">
                <Headphones className="size-5" />
              </span>
              <div>
                <CardTitle className="text-base">
                  {t({ zh: "今天的开口计划", en: "Today's speaking plan" })}
                </CardTitle>
                <CardDescription>
                  {plan?.assigned_unit_title
                    ? plan.assigned_unit_title
                    : t(TERMS.selfPractice)}{" "}
                  · {planSummary}
                </CardDescription>
              </div>
            </div>
            <span className="rounded-full border bg-background px-3 py-1.5 text-xs text-muted-foreground">
              {totalItems > 0
                ? t({
                    zh: "按自己的节奏完成",
                    en: "Go at your own pace",
                  })
                : t({ zh: "内容待安排", en: "Content to be assigned" })}
            </span>
          </CardHeader>
          <CardContent className="space-y-4">
            {totalItems === 0 && (
              <p
                role="status"
                className="rounded-xl bg-secondary/50 p-4 text-sm leading-6 text-muted-foreground"
              >
                {t({
                  zh: "老师还没有安排练习内容。你可以先检查麦克风，或到主题探索中自主练习。",
                  en: "Your teacher hasn't assigned practice yet. You can test your microphone or practice on your own in Explore Topics.",
                })}
              </p>
            )}
            <div className="flex items-center gap-3">
              <div
                role="progressbar"
                aria-label={t({
                  zh: "今日练习完成进度",
                  en: "Today's practice progress",
                })}
                aria-valuemin={0}
                aria-valuemax={totalItems || 1}
                aria-valuenow={Math.min(done, totalItems)}
                className="h-2 flex-1 overflow-hidden rounded-full bg-secondary"
              >
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{
                    width: `${Math.min((done / (totalItems || 1)) * 100, 100).toFixed(0)}%`,
                  }}
                />
              </div>
              <span className="text-[11px] text-muted-foreground">
                {t({
                  zh: `${done} / ${totalItems} 已完成`,
                  en: `${done} / ${totalItems} done`,
                })}
              </span>
            </div>
            {[
              readingCount > 0
                ? {
                    title: t({
                      zh: "先读一读，说一说",
                      en: "Read a little, speak a little",
                    }),
                    sub: t({
                      zh: "文章朗读 · 自然完整地读出来",
                      en: "Read Aloud · Read it through naturally",
                    }),
                    count: t({
                      zh: `${readingCount} 篇朗读`,
                      en: `${readingCount} passages`,
                    }),
                  }
                : null,
              repeatCount > 0
                ? {
                    title: t({
                      zh: "先听一听，再说一说",
                      en: "Listen first, then speak",
                    }),
                    sub: t({
                      zh: "听句复述 · 让熟悉的表达自然说出口",
                      en: "Listen & Repeat · Let familiar expressions come out naturally",
                    }),
                    count: t({
                      zh: `${repeatCount} 个短句`,
                      en: `${repeatCount} sentences`,
                    }),
                  }
                : null,
              qaCount > 0
                ? {
                    title: t({
                      zh: "轮到你，分享一点想法",
                      en: "Your turn — share an idea",
                    }),
                    sub: t({
                      zh: "情景问答 · 没有标准答案，你的想法很重要",
                      en: "Scenario Q&A · No single right answer; your ideas matter",
                    }),
                    count: t({
                      zh: `${qaCount} 个问题`,
                      en: `${qaCount} questions`,
                    }),
                  }
                : null,
            ]
              .filter((step) => step !== null)
              .map((step, index) => (
                <div
                  key={step.title}
                  className="flex items-center gap-3 border-t pt-3.5"
                >
                  <span className="flex size-8 items-center justify-center rounded-full bg-background text-xs text-muted-foreground">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div className="flex-1">
                    <p className="text-sm font-semibold">{step.title}</p>
                    <p className="text-xs text-muted-foreground">{step.sub}</p>
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {step.count}
                  </span>
                </div>
              ))}
            <p className="flex items-center gap-1.5 border-t pt-3 text-xs text-muted-foreground">
              <CheckCircle2 className="size-3.5" />
              {t({
                zh: "老师会根据课堂目标安排内容；按自己的节奏完成每一步。",
                en: "Your teacher assigns content based on class goals; complete each step at your own pace.",
              })}
            </p>
          </CardContent>
        </Card>

        {/* 从感兴趣的事，开始聊（主题推荐 3 卡） */}
        {(pathQuery.data?.units ?? []).length > 0 && (
          <div>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-bold tracking-tight">
                {t({
                  zh: "从感兴趣的事，开始聊",
                  en: "Start with what interests you",
                })}
              </h2>
              <Button
                variant="ghost"
                size="sm"
                className="text-xs text-primary"
                onClick={() =>
                  void navigate({ to: "/explore/$code", params: { code } })
                }
              >
                {t({ zh: "全部单元", en: "All units" })} <ArrowRight />
              </Button>
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              {(pathQuery.data?.units ?? []).slice(0, 3).map((unit) => (
                <button
                  key={unit.unit_id}
                  type="button"
                  onClick={() =>
                    void navigate({ to: "/explore/$code", params: { code } })
                  }
                  className="group overflow-hidden rounded-[1.375rem] border border-border/80 bg-card text-left transition-[transform,box-shadow,border-color] duration-200 hover:-translate-y-1 hover:border-primary/30 hover:shadow-lg"
                >
                  <div className="relative h-24">
                    <TopicArt topic={unit.topic} />
                    <span className="absolute top-2 left-2 rounded-md bg-card/85 px-2 py-0.5 text-[10px] font-semibold text-primary">
                      {(unit.rounds_done ?? 0) > 0
                        ? t({
                            zh: `已获 ${unit.best_stars ?? 0} 星`,
                            en: `Earned ${unit.best_stars ?? 0} stars`,
                          })
                        : t({ zh: "新单元", en: "New" })}
                    </span>
                  </div>
                  <div className="p-3">
                    <h3 className="text-sm font-semibold">{unit.title}</h3>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {unit.topic}
                    </p>
                    <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground">
                      <span>{t({ zh: "约 10 分钟", en: "About 10 min" })}</span>
                      <ArrowRight className="size-3.5" />
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* 周目标 + 表达积累 + 金句 */}
        <div className="grid gap-5 md:grid-cols-3">
          <Card>
            <CardHeader className="flex flex-wrap items-center justify-between gap-3 space-y-0">
              <CardTitle className="text-sm">
                {t({ zh: "这周，稳稳前进", en: "Steady forward this week" })}
              </CardTitle>
              <Dialog open={goalPicker} onOpenChange={setGoalPicker}>
                <DialogTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-xs text-primary"
                  >
                    {t({ zh: "调整目标", en: "Adjust goal" })}
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>
                      {t({
                        zh: "找到适合自己的练习节奏",
                        en: "Find your own practice rhythm",
                      })}
                    </DialogTitle>
                    <DialogDescription>
                      {t({
                        zh: "选择每周想练习的天数，随时可以调整。不用和别人比。",
                        en: "Choose how many days a week you'd like to practice — change it anytime. No need to compare with others.",
                      })}
                    </DialogDescription>
                  </DialogHeader>
                  <div className="grid grid-cols-3 gap-3">
                    {[3, 5, 7].map((n) => (
                      <button
                        key={n}
                        type="button"
                        aria-pressed={weekGoal === n}
                        onClick={() => {
                          writeWeekGoal(n)
                          setGoalPicker(false)
                          toast.success(
                            t({
                              zh: `每周目标已调整为 ${n} 天`,
                              en: `Weekly goal set to ${n} days`,
                            }),
                          )
                        }}
                        className={`rounded-2xl border px-2 py-5 text-center transition-colors ${weekGoal === n ? "border-primary bg-secondary text-primary" : "border-border hover:border-primary/50 hover:bg-secondary/40"}`}
                      >
                        <strong className="block text-3xl tabular-nums">
                          {n}
                          <span className="ml-1 text-xs font-normal">
                            {t({ zh: "天", en: "days" })}
                          </span>
                        </strong>
                        <span className="mt-2 block text-xs text-muted-foreground">
                          {
                            {
                              3: t({ zh: "慢慢来", en: "Easy does it" }),
                              5: t({ zh: "稳稳进步", en: "Steady progress" }),
                              7: t({ zh: "每天一点", en: "A little daily" }),
                            }[n]
                          }
                        </span>
                      </button>
                    ))}
                  </div>
                </DialogContent>
              </Dialog>
            </CardHeader>
            <CardContent className="flex flex-col items-center">
              <div className="relative grid size-32 place-items-center">
                <svg
                  viewBox="0 0 150 150"
                  className="absolute inset-0 size-full -rotate-90"
                  role="img"
                  aria-label={t({
                    zh: `本周已练习 ${weekDone} 天`,
                    en: `Practiced ${weekDone} days this week`,
                  })}
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
                    / {weekGoal} {t({ zh: "天", en: "days" })}
                  </span>
                  <span className="block text-[10px] text-muted-foreground">
                    {t({ zh: "本周开口目标", en: "This week's speaking goal" })}
                  </span>
                </p>
              </div>
              <div className="mt-3 grid grid-cols-7 gap-1 text-center">
                {WEEKDAYS.map((d, i) => {
                  const now = new Date()
                  const dow = (now.getDay() + 6) % 7
                  const day = new Date(now)
                  day.setDate(now.getDate() - dow + i)
                  // 本地日期（不能用 toISOString：会转成 UTC，东八区凌晨会差一天）
                  const key = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`
                  const isToday = i === dow
                  const practiced = practicedDates.has(key)
                  return (
                    <div key={key}>
                      <p className="mb-1.5 text-[9px] text-muted-foreground">
                        {t(d)}
                      </p>
                      <span
                        className={
                          practiced
                            ? "mx-auto grid size-6 place-items-center rounded-full bg-primary text-[10px] text-white"
                            : isToday
                              ? "mx-auto grid size-6 place-items-center rounded-full border-[1.5px] border-dashed border-primary bg-card text-[10px] text-primary"
                              : "mx-auto grid size-6 place-items-center rounded-full bg-background text-[10px] text-muted-foreground"
                        }
                      >
                        {practiced
                          ? "✓"
                          : isToday
                            ? t({ zh: "今", en: "•" })
                            : "·"}
                      </span>
                    </div>
                  )
                })}
              </div>
              <p className="mt-3 text-center text-xs text-muted-foreground">
                {weekDone >= weekGoal
                  ? t({
                      zh: "本周目标已达成，保持自己的节奏",
                      en: "Weekly goal reached — keep your own pace",
                    })
                  : t({
                      zh: `再练 ${weekGoal - weekDone} 天，就完成本周小目标`,
                      en: `${weekGoal - weekDone} more day(s) to reach this week's goal`,
                    })}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">
                {t({
                  zh: "你的表达，正在生长",
                  en: "Your expressions are growing",
                })}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="mt-2 text-4xl font-bold tabular-nums">
                {Object.values(trailQuery.data?.vocab_counts ?? {}).reduce(
                  (sum, count) => sum + count,
                  0,
                )}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {t({
                  zh: "累计用过的词汇表达",
                  en: "Expressions used in total",
                })}
              </p>
              {g && (
                <p className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
                  <Flame className="size-3.5 text-orange-400" />
                  {t({
                    zh: `连胜 ${g.streak_days} 天 · ${g.xp} XP`,
                    en: `Streak ${g.streak_days} days · ${g.xp} XP`,
                  })}
                </p>
              )}
            </CardContent>
          </Card>

          <Card className="border-accent bg-accent">
            <CardHeader>
              <CardDescription className="flex items-center gap-1.5 !text-accent-foreground">
                <Sparkles className="size-3.5" />{" "}
                {t({ zh: "给今天的你", en: "For you today" })}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <blockquote className="font-serif text-xl leading-relaxed">
                “{quote.en}”
              </blockquote>
              {lang === "zh" && (
                <p className="mt-2 text-xs text-accent-foreground/80">
                  {quote.zh}
                </p>
              )}
              <div className="mt-3 flex items-center justify-between text-[10px] text-accent-foreground/70">
                <span>ONE SENTENCE A DAY</span>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t({
                    zh: "朗读今日金句",
                    en: "Read today's quote aloud",
                  })}
                  onClick={() => {
                    speakEnglish(quote.en)
                  }}
                >
                  <Volume2 />
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* 快捷入口 */}
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" asChild>
            <Link to="/vocab/$code" params={{ code }}>
              <BookA />
              {t(TERMS.vocabLearning)}
            </Link>
          </Button>
          <Button
            variant="secondary"
            onClick={() =>
              void navigate({ to: "/explore/$code", params: { code } })
            }
          >
            <Sparkles />
            {t({ zh: "主题探索", en: "Explore Topics" })}
          </Button>
          <Button
            variant="secondary"
            onClick={() => void navigate({ to: "/me/$code", params: { code } })}
          >
            <Star />
            {t(TERMS.growthPage)}
          </Button>
        </div>
      </div>
    </StudentShell>
  )
}
