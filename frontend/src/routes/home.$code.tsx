import { useQuery } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  useNavigate,
  useParams,
} from "@tanstack/react-router"
import { ArrowRight, Headphones, Sparkles } from "lucide-react"
import { ClassesService } from "@/client"
import { DevicePreflight } from "@/components/Practice/DevicePreflight"
import HeroArt from "@/components/Practice/HeroArt"
import { PublishedClassSummaries } from "@/components/Practice/PublishedClassSummaries"
import { StudentClassroomInbox } from "@/components/Practice/StudentClassroomInbox"
import { StudentFollowups } from "@/components/Practice/StudentFollowups"
import StudentShell from "@/components/Practice/StudentShell"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { APP_NAME } from "@/config"
import { useClassroomActivity } from "@/hooks/useClassroomActivity"
import { useClassroomRevision } from "@/hooks/useClassroomRevision"
import { useStudentGuard } from "@/hooks/useStudentGuard"
import { displayName, loadStudent } from "@/lib/classroom-student"
import { useI18n } from "@/lib/i18n"
import { buildAttemptByItem } from "@/lib/practice-derive"
import { TERMS } from "@/lib/terms"

export const Route = createFileRoute("/home/$code")({
  component: HomePage,
  head: () => ({ meta: [{ title: `今日任务 / Today’s Tasks - ${APP_NAME}` }] }),
})

function HomePage() {
  const { t } = useI18n()
  const { code } = useParams({ from: "/home/$code" })
  useClassroomActivity(code, "entered")
  const navigate = useNavigate({ from: "/home/$code" })
  const student = loadStudent(code)
  useClassroomRevision(code, student?.id)

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
  const attempts = buildAttemptByItem(plan?.attempts ?? [])
  const done =
    plan?.items.filter(
      (item) =>
        item.type !== "instruction" && attempts.get(item.id)?.status === "done",
    ).length ?? 0
  const totalItems =
    plan?.items.filter((item) => item.type !== "instruction").length ?? 0
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

  return (
    <StudentShell active="home" wide>
      <div className="flex flex-col gap-7">
        <section className="learning-hero relative isolate overflow-hidden rounded-3xl p-5 sm:p-7 lg:p-8">
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
              <span className="h-px w-6 bg-tan-gold" />
              {t({ zh: "今日任务", en: "Today’s Tasks" })}
            </p>
            <h1 className="mt-3 break-words text-xl font-semibold leading-snug tracking-tight sm:text-3xl lg:text-4xl">
              {t({
                zh: `Hi，${displayName(student)}。`,
                en: `Hi, ${displayName(student)}.`,
              })}
              <br />
              <span className="text-tan-gold">
                {t({
                  zh: "今天，从这里开始。",
                  en: "Start here today.",
                })}
              </span>
            </h1>
            <p className="mt-4 text-sm leading-6 text-mint">
              {plan?.assigned_unit_title
                ? t({
                    zh: `${plan.exam ? "考试" : "今日练习"} · ${plan.assigned_unit_title}`,
                    en: `${plan.exam ? "Exam" : "Today's Practice"} · ${plan.assigned_unit_title}`,
                  })
                : t({
                    zh: "从一次小小的练习，开始你的表达。",
                    en: "Start your speaking journey with one small practice.",
                  })}
            </p>
            <div className="mt-4 space-y-3 text-sm text-mint">
              <p>{planSummary}</p>
              {totalItems > 0 ? (
                <div className="flex items-center gap-3">
                  <div
                    role="progressbar"
                    aria-label={t({
                      zh: "今日练习完成进度",
                      en: "Today's practice progress",
                    })}
                    aria-valuemin={0}
                    aria-valuemax={totalItems}
                    aria-valuenow={done}
                    className="h-2 flex-1 overflow-hidden rounded-full bg-white/15"
                  >
                    <div
                      className="h-full rounded-full bg-tan-soft transition-all"
                      style={{ width: `${(done / totalItems) * 100}%` }}
                    />
                  </div>
                  <span className="shrink-0 text-xs">
                    {t({
                      zh: `${done} / ${totalItems} 已完成`,
                      en: `${done} / ${totalItems} done`,
                    })}
                  </span>
                </div>
              ) : (
                <p role="status">
                  {t({
                    zh: "老师还没有安排练习内容，可以先检查设备。",
                    en: "Your teacher hasn't assigned practice yet. You can check your devices first.",
                  })}
                </p>
              )}
            </div>
            <div className="mt-5 flex flex-wrap items-center gap-4">
              <Button
                size="lg"
                className="group bg-tan-soft text-brand-pine shadow-none hover:bg-tan-pale"
                disabled={totalItems === 0}
                onClick={() =>
                  void navigate({
                    to: plan?.exam ? "/exam/$code" : "/p/$code",
                    params: { code },
                  })
                }
              >
                {totalItems === 0
                  ? t({ zh: "等待课堂安排", en: "Awaiting today's assignment" })
                  : plan?.exam
                    ? t({
                        zh: plan.exam.ended
                          ? "查看考试反馈"
                          : plan.exam.started
                            ? "继续考试"
                            : "进入考试",
                        en: plan.exam.ended
                          ? "View exam feedback"
                          : plan.exam.started
                            ? "Continue exam"
                            : "Open exam",
                      })
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
              {plan?.homework_title && (
                <Button
                  size="lg"
                  variant="outline"
                  className="min-h-11 border-white/30 bg-transparent text-paper-hero hover:bg-white/10"
                  onClick={() =>
                    void navigate({
                      to: "/p/$code",
                      params: { code },
                      search: { homework: true },
                    })
                  }
                >
                  {t({
                    zh: `课后作业 · ${plan.homework_title}`,
                    en: `Homework · ${plan.homework_title}`,
                  })}
                </Button>
              )}
              <span className="text-xs text-mint">
                {t({
                  zh: "轻松开口，不怕说错",
                  en: "Speak freely — mistakes are welcome",
                })}
              </span>
            </div>
          </div>
        </section>
        <StudentFollowups code={code} />
        <StudentClassroomInbox code={code} />
        <PublishedClassSummaries code={code} />
        <DevicePreflight code={code} />

        <div className="flex flex-wrap gap-3">
          {(totalItems === 0 ||
            (done >= totalItems && (!plan?.exam || plan.exam.ended))) && (
            <Button variant="ghost" className="min-h-11" asChild>
              <Link to="/explore/$code" params={{ code }}>
                <Sparkles />
                {t(TERMS.selfPractice)}
              </Link>
            </Button>
          )}
        </div>
      </div>
    </StudentShell>
  )
}
