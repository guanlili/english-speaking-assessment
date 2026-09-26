import { useMutation, useQuery } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  useNavigate,
  useParams,
} from "@tanstack/react-router"
import confetti from "canvas-confetti"
import {
  ArrowRight,
  Flame,
  Play,
  Repeat,
  Shuffle,
  Sparkles,
  Star,
  Trophy,
} from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import type { PlanAttempt, PlanItem } from "@/client"
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Separator } from "@/components/ui/separator"
import { APP_NAME } from "@/config"

const API_BASE = import.meta.env.VITE_API_URL ?? ""

import { displayName, loadStudent } from "@/lib/classroom-student"

export const Route = createFileRoute("/p/$code/result")({
  component: RoundResultPage,
  head: () => ({
    meta: [{ title: `本轮结果 - ${APP_NAME}` }],
  }),
})

const ITEM_TYPE_LABELS: Record<string, string> = {
  repeat: "听后复述",
  question: "情景问答",
}

function RoundResultPage() {
  const { code } = useParams({ from: "/p/$code/result" })
  const navigate = useNavigate({ from: "/p/$code/result" })
  const student = loadStudent(code)

  const todayQuery = useQuery({
    queryKey: ["classroom", code, "today", student?.id],
    queryFn: () =>
      ClassesService.readTodayPlan({
        code: code.toUpperCase(),
        studentId: student?.id as string,
      }),
    enabled: student !== null,
  })

  const [replay, setReplay] = useState<{
    item: PlanItem
    attempt: PlanAttempt
  } | null>(null)

  const nextQuestionMutation = useMutation({
    mutationFn: () =>
      // 换题逻辑统一在练习页执行（?next=1），这里仅做跳转
      Promise.resolve(null),
    onSuccess: () => {
      void navigate({
        to: "/p/$code",
        params: { code },
        search: { next: true },
      })
    },
  })

  const plan = todayQuery.data
  const gamification = plan?.gamification ?? null
  const newBadges = useMemo(() => {
    if (!gamification?.badges) return []
    const today = new Date().toISOString().slice(0, 10)
    return gamification.badges.filter(
      (b) => (b.awarded_at ?? "").slice(0, 10) === today,
    )
  }, [gamification])

  // 3 星或新徽章 → 庆祝彩带（只放一次）
  useEffect(() => {
    if (
      gamification &&
      (gamification.session_stars === 3 || newBadges.length > 0)
    ) {
      confetti({ particleCount: 90, spread: 75, origin: { y: 0.6 } })
    }
  }, [gamification?.session_stars, newBadges.length, gamification])

  const { doneItems, weakest } = useMemo(() => {
    const empty: { item: PlanItem; attempt: PlanAttempt }[] = []
    if (!plan) return { doneItems: empty, weakest: null as string | null }
    const map = new Map<string, PlanAttempt>(
      plan.attempts.map((a) => [a.item_id, a]),
    )
    const scored = plan.items.flatMap((item) => {
      const attempt = map.get(item.id)
      if (attempt === undefined || attempt.status !== "done") return []
      return [{ item, attempt }]
    })
    let weakestId: string | null = null
    let minOverall = Number.POSITIVE_INFINITY
    for (const row of scored) {
      const overall = row.attempt.overall
      if (overall !== null && overall !== undefined && overall < minOverall) {
        minOverall = overall
        weakestId = row.item.id
      }
    }
    return { doneItems: scored, weakest: weakestId }
  }, [plan])

  if (student === null) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        <Button variant="outline" asChild>
          <Link to="/j/$code" params={{ code }}>
            先进入课堂
          </Link>
        </Button>
      </div>
    )
  }

  if (todayQuery.isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        正在加载结果…
      </div>
    )
  }
  if (todayQuery.isError || !plan) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        结果加载失败，请刷新重试。
      </div>
    )
  }

  return (
    <StudentShell active="practice">
      <div className="flex flex-col gap-6">
        <div>
          <h1 className="text-xl font-bold tracking-tight">
            今天的你，又向前了一步。
          </h1>
          <p className="text-sm text-muted-foreground">
            {displayName(student)} · 课堂 {plan.classroom_code} · 每题转写和总评
          </p>
        </div>

        {gamification && gamification.session_stars !== null && (
          <section className="flex flex-wrap items-center gap-5 rounded-3xl bg-secondary p-6">
            <span className="-rotate-8 grid size-20 shrink-0 place-items-center rounded-[26px] bg-primary text-yellow-300">
              <Trophy className="size-9" />
            </span>
            <div className="min-w-40 flex-1">
              <p className="text-[10px] font-bold tracking-[0.2em] text-primary">
                EVERY WORD COUNTS
              </p>
              <h2 className="mt-1.5 text-xl font-bold">
                比起完美，开口本身就很棒。
              </h2>
              <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
                <span className="flex items-center gap-1">
                  {[1, 2, 3].map((n) => (
                    <Star
                      key={n}
                      className={
                        n <= (gamification.session_stars ?? 0)
                          ? "size-5 fill-yellow-400 text-yellow-400"
                          : "size-5 text-muted-foreground/30"
                      }
                      style={{
                        animation: `star-pop 0.4s ease-out ${n * 0.25}s both`,
                      }}
                    />
                  ))}
                </span>
                <span className="flex items-center gap-1 font-semibold">
                  <Sparkles className="size-4 text-primary" />
                  XP {gamification.xp}
                </span>
                <span className="flex items-center gap-1 text-muted-foreground">
                  <Flame className="size-4 text-orange-500" />
                  连胜 {gamification.streak_days} 天
                </span>
              </div>
              {newBadges.length > 0 && (
                <p className="mt-2 text-sm">
                  <span className="font-semibold">本轮获得徽章：</span>
                  {newBadges.map((b) => b.label).join("、")}
                </p>
              )}
            </div>
          </section>
        )}

        {doneItems.length === 0 && (
          <Card>
            <CardContent className="py-6 text-muted-foreground">
              还没有完成的作答。回到练习页开始第一题。
            </CardContent>
          </Card>
        )}

        {doneItems.map(({ item, attempt }, index) => (
          <Card key={item.id}>
            <CardHeader>
              <CardDescription>
                {index + 1}. {ITEM_TYPE_LABELS[item.type] ?? item.type}
                {item.band ? ` · ${item.band}` : ""}
              </CardDescription>
              <CardTitle className="text-sm leading-relaxed font-medium">
                {item.text}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm leading-relaxed">
                <span className="text-muted-foreground">转写：</span>
                {attempt.transcript || "（无）"}
              </p>
              <Separator />
              <div className="flex items-center gap-4 text-sm">
                <span className="text-2xl font-bold tabular-nums">
                  总评 {attempt.overall ?? "–"}
                </span>
                {item.type !== "question" && (
                  <span className="text-muted-foreground">
                    完整度 {attempt.completeness ?? "–"} · 流利度{" "}
                    {attempt.fluency ?? "–"}
                  </span>
                )}
              </div>
              {attempt.advice && attempt.advice.length > 0 && (
                <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                  {attempt.advice.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              )}
              {attempt.attempt_id && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setReplay({ item, attempt })}
                >
                  <Play />
                  回听这一题
                </Button>
              )}
            </CardContent>
          </Card>
        ))}

        {/* 回看弹窗：转写 + 自己的录音 */}
        <Dialog
          open={replay !== null}
          onOpenChange={(o) => !o && setReplay(null)}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>
                {replay && (
                  <>
                    {ITEM_TYPE_LABELS[replay.item.type] ?? replay.item.type} ·
                    回看这次表达
                  </>
                )}
              </DialogTitle>
              <DialogDescription>{replay?.item.text}</DialogDescription>
            </DialogHeader>
            {replay && (
              <div className="space-y-3">
                <div>
                  <p className="mb-1 text-xs text-muted-foreground">
                    你说了什么（转写）
                  </p>
                  <p className="rounded-lg bg-background p-3 text-sm leading-relaxed">
                    {replay.attempt.transcript || "（无转写）"}
                  </p>
                </div>
                <div className="flex items-center gap-3 text-sm">
                  <span className="text-2xl font-bold tabular-nums">
                    {replay.attempt.overall ?? "–"}
                  </span>
                  <span className="text-muted-foreground">参考总评</span>
                </div>
                {replay.attempt.attempt_id && (
                  <audio
                    controls
                    preload="metadata"
                    src={`${API_BASE}/api/v1/attempts/${replay.attempt.attempt_id}/audio`}
                    className="w-full"
                  >
                    <track kind="captions" />
                  </audio>
                )}
                <p className="text-xs text-muted-foreground">
                  听一听自己刚才的声音，找出下一句想说得更好的地方。
                </p>
              </div>
            )}
            <DialogFooter>
              <Button variant="outline" onClick={() => setReplay(null)}>
                关闭
              </Button>
              <Button
                onClick={() => {
                  if (replay) {
                    void navigate({
                      to: "/p/$code",
                      params: { code },
                      search: { focus: replay.item.id },
                    })
                  }
                }}
              >
                <Repeat />
                再练这一题
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <div className="flex flex-wrap gap-3">
          {weakest && (
            <Button
              variant="outline"
              onClick={() =>
                void navigate({
                  to: "/p/$code",
                  params: { code },
                  search: { focus: weakest },
                })
              }
            >
              <Repeat />
              重练最弱的一题
            </Button>
          )}
          <Button
            onClick={() => nextQuestionMutation.mutate()}
            disabled={
              nextQuestionMutation.isPending ||
              plan.questions_exhausted === true
            }
          >
            <Shuffle />
            {plan.questions_exhausted === true
              ? "这个主题的题已练完"
              : "换同主题下一问"}
          </Button>
          <Button variant="ghost" asChild>
            <Link to="/p/$code" params={{ code }}>
              回练习页
              <ArrowRight />
            </Link>
          </Button>
        </div>

        <p className="pb-6 text-center text-xs text-muted-foreground">
          参考反馈，不是考试成绩。
        </p>
      </div>
    </StudentShell>
  )
}
