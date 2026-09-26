import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  useNavigate,
  useParams,
} from "@tanstack/react-router"
import { ArrowRight, Circle, Flame, Mic, Sparkles, Square } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import type { PlanAttempt, PlanItem } from "@/client"
import { ClassesService } from "@/client"
import FeedbackCard from "@/components/Practice/FeedbackCard"
import SpeakButton from "@/components/Practice/SpeakButton"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { APP_NAME } from "@/config"
import { useAttemptSubmit } from "@/hooks/useAttemptSubmit"
import { MAX_RECORD_SECONDS, useRecorder } from "@/hooks/useRecorder"
import { displayName, loadStudent } from "@/lib/classroom-student"

export const Route = createFileRoute("/p/$code/")({
  component: ClassroomPracticePage,
  validateSearch: (
    search: Record<string, unknown>,
  ): { focus?: string; next?: boolean } => {
    // 只序列化真值，避免 URL 出现 ?focus=undefined&next=false
    const result: { focus?: string; next?: boolean } = {}
    if (typeof search.focus === "string") result.focus = search.focus
    if (search.next === true) result.next = true
    return result
  },
  head: () => ({
    meta: [{ title: `今天的练习 - ${APP_NAME}` }],
  }),
})

const BAND_LABELS: Record<string, string> = {
  A2: "低档",
  B1: "中档",
  B2: "高档",
}

const ITEM_TYPE_LABELS: Record<string, string> = {
  repeat: "听后复述",
  question: "情景问答",
}

function formatSeconds(seconds: number): string {
  const whole = Math.floor(seconds)
  return `${String(Math.floor(whole / 60)).padStart(1, "0")}:${String(whole % 60).padStart(2, "0")}`
}

function isTerminal(status: string | undefined): boolean {
  return status === "done" || status === "failed"
}

function ClassroomPracticePage() {
  const { code } = useParams({ from: "/p/$code/" })
  const { focus: focusParam, next: nextFlag } = Route.useSearch()
  const navigate = useNavigate({ from: "/p/$code/" })
  const queryClient = useQueryClient()
  const student = loadStudent(code)
  // 手动定位的题（结果页「重练最弱一题」跳转过来）
  const [focusItemId, setFocusItemId] = useState<string | null>(
    focusParam ?? null,
  )
  // 提交后钉住当前题，直到用户点「下一题」
  const [pinnedItemId, setPinnedItemId] = useState<string | null>(null)

  const todayQuery = useQuery({
    queryKey: ["classroom", code, "today", student?.id],
    queryFn: () =>
      ClassesService.readTodayPlan({
        code: code.toUpperCase(),
        studentId: student?.id as string,
      }),
    enabled: student !== null,
    refetchInterval: (query) =>
      query.state.data?.attempts.some((a) => !isTerminal(a.status))
        ? 2000
        : false,
  })

  // 未留名 → 回加入页
  useEffect(() => {
    if (student === null) {
      void navigate({ to: "/j/$code", params: { code } })
    }
  }, [student, code, navigate])

  // 换一题：同主题同档未做过（US-06）
  const nextQuestionMutation = useMutation({
    mutationFn: () =>
      ClassesService.readNextQuestion({
        code: code.toUpperCase(),
        studentId: student?.id as string,
      }),
    onSuccess: (data) => {
      if (data.question) {
        setExtraQuestion(data.question as PlanItem)
        queryClient.invalidateQueries({
          queryKey: ["classroom", code, "today", student?.id],
        })
      } else {
        toast.info("这个主题的题已练完", {
          description: "可以重录上一题继续 polish",
        })
      }
    },
  })

  // 结果页「换同主题下一问」跳转过来（?next=1）时执行换题（闩锁保证只触发一次）
  const nextFlagConsumedRef = useRef(false)
  useEffect(() => {
    if (nextFlag && !nextFlagConsumedRef.current && student !== null) {
      nextFlagConsumedRef.current = true
      nextQuestionMutation.mutate()
    }
  })

  // 追加换来的题（本地状态；完成后随 attempts 展示）
  const [extraQuestion, setExtraQuestion] = useState<PlanItem | null>(null)

  const plan = todayQuery.data
  const items = useMemo(() => {
    if (!plan) return []
    const merged = [...plan.items]
    if (extraQuestion) {
      const exists = merged.some((i) => i.id === extraQuestion.id)
      if (!exists) merged.push(extraQuestion)
    }
    return merged
  }, [plan, extraQuestion])

  const attemptByItem = useMemo(() => {
    const map = new Map<string, PlanAttempt>()
    for (const a of plan?.attempts ?? []) {
      map.set(a.item_id, a)
    }
    return map
  }, [plan])

  const currentIndex = useMemo(() => {
    // 查看反馈期间钉在当前题（避免评分完成后的计划刷新把视图拽走）
    if (pinnedItemId) {
      const pinnedIndex = items.findIndex((i) => i.id === pinnedItemId)
      if (pinnedIndex >= 0) return pinnedIndex
    }
    if (focusItemId) {
      const focusIndex = items.findIndex((i) => i.id === focusItemId)
      if (focusIndex >= 0) return focusIndex
    }
    const firstUndone = items.findIndex(
      (item) => !isTerminal(attemptByItem.get(item.id)?.status),
    )
    if (firstUndone === -1) return items.length - 1
    return firstUndone
  }, [items, attemptByItem, focusItemId, pinnedItemId])

  const currentItem = items[currentIndex]
  const allDone = plan?.items.every((item) =>
    isTerminal(attemptByItem.get(item.id)?.status),
  )

  const {
    submit,
    submitting,
    attempt,
    submitError,
    reset: resetAttempt,
  } = useAttemptSubmit({
    itemType: (currentItem?.type as "repeat" | "question") ?? "repeat",
    itemId: currentItem?.id ?? "",
    studentId: student?.id,
    sessionId: plan?.session_id,
  })

  const recorder = useRecorder({
    onComplete: (rec) => {
      if (currentItem) setPinnedItemId(currentItem.id)
      submit({ blob: rec.blob, duration: rec.duration })
    },
  })

  useEffect(() => {
    if (submitError) {
      toast.error("上传失败", { description: "请检查网络后再录一次" })
    }
  }, [submitError])

  // 当前题评分完成后同步今日计划（进度、allDone、升降档后的问答）
  const attemptDone = attempt !== undefined && attempt.status === "done"
  useEffect(() => {
    if (attemptDone) {
      void queryClient.invalidateQueries({
        queryKey: ["classroom", code, "today", student?.id],
      })
    }
  }, [attemptDone, queryClient, code, student?.id])

  const repractice = () => recorder.reset()

  // 下一题：清空当前反馈态，进度由服务端 attempts 推进
  const goNext = () => {
    resetAttempt()
    recorder.reset()
    setFocusItemId(null)
    setPinnedItemId(null)
    void queryClient.invalidateQueries({
      queryKey: ["classroom", code, "today", student?.id],
    })
  }

  if (student === null) return null

  if (todayQuery.isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        正在加载今天的练习…
      </div>
    )
  }
  if (todayQuery.isError || !plan) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 text-muted-foreground">
        练习加载失败，请刷新重试。
        <Button variant="outline" onClick={() => todayQuery.refetch()}>
          重试
        </Button>
      </div>
    )
  }

  if (!currentItem) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        今天没有练习内容。
      </div>
    )
  }

  const previousItem = currentIndex > 0 ? items[currentIndex - 1] : null
  const previousAttempt = previousItem
    ? attemptByItem.get(previousItem.id)
    : undefined

  const isQuestion = currentItem.type === "question"

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 p-6">
        {/* 顶部进度（PRD §8.5：第 2/5 题 · 中档） */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold tracking-tight">
              第 {currentIndex + 1}/{items.length} 题 ·{" "}
              {BAND_LABELS[plan.band] ?? plan.band}
            </h1>
            {plan.assigned_unit_title && (
              <p className="text-sm font-medium text-primary">
                📌 今日课堂：{plan.assigned_unit_title}（老师指派）
              </p>
            )}
            <p className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
              {displayName(student)} · 课堂 {plan.classroom_code}
              {plan.gamification && (
                <>
                  <span className="flex items-center gap-1">
                    <Flame className="size-4 text-orange-500" />
                    {plan.gamification.streak_days} 天
                  </span>
                  <span className="flex items-center gap-1 font-medium text-foreground">
                    <Sparkles className="size-4 text-primary" />
                    {plan.gamification.xp} XP
                  </span>
                </>
              )}
            </p>
          </div>
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" asChild>
              <Link to="/map/$code" params={{ code }}>
                关卡地图
              </Link>
            </Button>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/me/$code" params={{ code }}>
                我的进步
              </Link>
            </Button>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/p/$code/result" params={{ code }}>
                结果页
              </Link>
            </Button>
          </div>
        </div>

        <Card>
          <CardHeader>
            <CardDescription>
              {ITEM_TYPE_LABELS[currentItem.type] ?? currentItem.type}
              {isQuestion && currentItem.band
                ? ` · ${BAND_LABELS[currentItem.band] ?? currentItem.band}`
                : ""}
              {" · "}
              建议时长 {formatSeconds(currentItem.suggested_seconds ?? 20)}
            </CardDescription>
            <CardTitle className="text-lg leading-relaxed">
              {currentItem.text}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <SpeakButton
              text={currentItem.text}
              audioUrl={currentItem.audio_url}
            />

            <Separator />

            <div className="flex flex-col gap-2">
              {recorder.status === "recording" ? (
                <Button
                  variant="destructive"
                  size="lg"
                  onClick={recorder.stop}
                  className="w-fit"
                >
                  <Square />
                  停止（{formatSeconds(recorder.elapsed)} /{" "}
                  {formatSeconds(MAX_RECORD_SECONDS)}）
                </Button>
              ) : (
                <Button
                  size="lg"
                  onClick={() => recorder.start()}
                  disabled={submitting}
                  className="w-fit"
                >
                  <Mic />
                  开始录音
                </Button>
              )}
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                {recorder.status === "recording" && (
                  <>
                    <Circle className="size-2 animate-pulse fill-destructive text-destructive" />
                    正在录音 {recorder.elapsed.toFixed(0)}s，读完点「停止」
                  </>
                )}
                {recorder.status === "idle" && <>录音状态：未录</>}
                {recorder.status === "ready" && submitting && (
                  <>已提交，正在出反馈…</>
                )}
                {recorder.status === "ready" && !submitting && <>录音完成</>}
              </p>
              {recorder.error && (
                <p className="text-sm text-destructive">{recorder.error}</p>
              )}
            </div>
          </CardContent>
        </Card>

        {/* 当前题反馈：先显示轮询中的，再显示历史完成态 */}
        {attempt !== undefined ? (
          <FeedbackCard
            attempt={attempt}
            itemType={currentItem.type as "repeat" | "question"}
            onRepractice={repractice}
            extraActions={
              <>
                {attemptDone && (
                  <Button onClick={goNext}>
                    下一题
                    <ArrowRight />
                  </Button>
                )}
                {isQuestion && (
                  <Button
                    variant="secondary"
                    onClick={() => nextQuestionMutation.mutate()}
                    disabled={nextQuestionMutation.isPending}
                  >
                    换一题（同主题）
                  </Button>
                )}
              </>
            }
          />
        ) : attemptByItem.has(currentItem.id) ? (
          <PreviousScoreCard
            item={currentItem}
            attempt={attemptByItem.get(currentItem.id)}
          />
        ) : null}

        {/* 底部上一题分数（PRD §8.5） */}
        {previousItem &&
          previousAttempt?.overall !== null &&
          previousAttempt && (
            <p className="text-sm text-muted-foreground">
              上一题（{ITEM_TYPE_LABELS[previousItem.type] ?? previousItem.type}
              ）总评：{" "}
              <span className="font-semibold text-foreground">
                {previousAttempt.overall ?? "–"}
              </span>
            </p>
          )}

        {allDone && (
          <Button size="lg" asChild>
            <Link to="/p/$code/result" params={{ code }}>
              查看本轮结果
            </Link>
          </Button>
        )}

        <p className="pb-6 text-center text-xs text-muted-foreground">
          分数是参考反馈，不是考试成绩。
        </p>
      </div>
    </div>
  )
}

function PreviousScoreCard({
  item,
  attempt,
}: {
  item: PlanItem
  attempt: PlanAttempt | undefined
}) {
  if (attempt === undefined) return null
  return (
    <Card>
      <CardContent className="space-y-2 py-4">
        <p className="text-sm text-muted-foreground">
          {ITEM_TYPE_LABELS[item.type] ?? item.type} · 最近一次
        </p>
        {attempt.status === "failed" ? (
          <p className="text-sm text-destructive">
            上次没有评出来（{attempt.error ?? "原因未知"}），可以再录
          </p>
        ) : (
          <p className="text-2xl font-bold tabular-nums">
            总评 {attempt.overall ?? "–"}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
