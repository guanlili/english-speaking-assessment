import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  useNavigate,
  useParams,
} from "@tanstack/react-router"
import {
  ArrowRight,
  ChartLine,
  Flame,
  Headphones,
  MessageCircle,
  Mic,
  Shield,
  Sparkles,
  Square,
  Volume2,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import type { PlanAttempt, PlanItem } from "@/client"
import { ApiError, ClassesService } from "@/client"
import FeedbackCard from "@/components/Practice/FeedbackCard"

const API_BASE = import.meta.env.VITE_API_URL ?? ""

import SpeakButton from "@/components/Practice/SpeakButton"
import StudentShell from "@/components/Practice/StudentShell"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { APP_NAME } from "@/config"
import type { AttemptSubmitTarget } from "@/hooks/useAttemptSubmit"
import { useAttemptSubmit } from "@/hooks/useAttemptSubmit"
import { MAX_RECORD_SECONDS, useRecorder } from "@/hooks/useRecorder"
import {
  clearStudent,
  displayName,
  isStudentNotFound,
  loadStudent,
} from "@/lib/classroom-student"

export const Route = createFileRoute("/p/$code/")({
  component: ClassroomPracticePage,
  validateSearch: (
    search: Record<string, unknown>,
  ): { focus?: string; next?: boolean; explore?: string } => {
    // 只序列化真值，避免 URL 出现 ?focus=undefined&next=false
    const result: { focus?: string; next?: boolean; explore?: string } = {}
    if (typeof search.focus === "string") result.focus = search.focus
    if (search.next === true) result.next = true
    if (typeof search.explore === "string") result.explore = search.explore
    return result
  },
  head: () => ({
    meta: [{ title: `今日练习 - ${APP_NAME}` }],
  }),
})

const BAND_LABELS: Record<string, string> = {
  A2: "A2 档",
  B1: "B1 档",
  B2: "B2 档",
}

const ITEM_TYPE_LABELS: Record<string, string> = {
  passage: "文章朗读",
  repeat: "听句复述",
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
  const {
    focus: focusParam,
    next: nextFlag,
    explore: exploreSessionId,
  } = Route.useSearch()
  const navigate = useNavigate({ from: "/p/$code/" })
  const queryClient = useQueryClient()
  const student = loadStudent(code)
  // 手动定位的题（结果页「重练最弱一题」跳转过来）
  const [focusItemId, setFocusItemId] = useState<string | null>(
    focusParam ?? null,
  )
  // 提交后钉住当前题，直到用户点「下一题」
  const [pinnedItemId, setPinnedItemId] = useState<string | null>(null)
  // 复述题「收起原文」练记忆（SpeakUp）
  const [hideText, setHideText] = useState(false)
  // 录音开始时钉住 item_id / session_id / 题型：录音期间老师切换指派不影响旧录音
  const recordingTargetRef = useRef<AttemptSubmitTarget | null>(null)
  // 本次停留是否提交过录音：防止从结果页回来时 allDone 直接又跳回结果页
  const submittedRef = useRef(false)
  // 自动跳结果页的闩锁：每次挂载最多跳一次
  const navigatedRef = useRef(false)

  const todayQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: ["classroom", code, "today", student?.id, exploreSessionId],
    queryFn: () =>
      ClassesService.readTodayPlan({
        code: code.toUpperCase(),
        ...(exploreSessionId ? { sessionId: exploreSessionId } : {}),
      }),
    enabled: student !== null,
    refetchInterval: (query) =>
      query.state.data?.attempts.some((a) => !isTerminal(a.status))
        ? 2000
        : 30000, // 慢速同步：老师中途指派新单元时学生端最迟 30 秒感知
  })

  // 身份失效（清库/课堂重建后 404）：清除本地身份，引导重新进入
  useEffect(() => {
    if (todayQuery.isError && isStudentNotFound(todayQuery.error)) {
      clearStudent(code)
      void navigate({ to: "/j/$code", params: { code } })
    }
  }, [todayQuery.isError, todayQuery.error, code, navigate])

  // 未留名 → 回加入页
  useEffect(() => {
    if (student === null) {
      void navigate({ to: "/j/$code", params: { code } })
    }
  }, [student, code, navigate])

  // 换一题：同主题同档未做过（US-06）；探索轮绑定 session_id
  const nextQuestionMutation = useMutation({
    mutationFn: () =>
      ClassesService.readNextQuestion({
        code: code.toUpperCase(),
        ...(plan?.session_id ? { sessionId: plan.session_id } : {}),
        ...(items.length ? { excludeIds: items.map((i) => i.id) } : {}),
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
    // 等计划加载后再换题：否则 plan?.session_id 为空，探索轮会取错主题/档位
    if (
      nextFlag &&
      !nextFlagConsumedRef.current &&
      student !== null &&
      todayQuery.isSuccess
    ) {
      nextFlagConsumedRef.current = true
      nextQuestionMutation.mutate()
    }
  }, [nextFlag, student, nextQuestionMutation, todayQuery.isSuccess])

  // ?next=1 但计划加载失败：提示换题未成功（否则静默无反应）
  useEffect(() => {
    if (nextFlag && todayQuery.isError) {
      toast.error("换题失败", { description: "练习计划加载失败，请返回重试" })
    }
  }, [nextFlag, todayQuery.isError])

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
  const allDone =
    items.length > 0 &&
    items.every((item) => isTerminal(attemptByItem.get(item.id)?.status))

  const {
    submit,
    submitting,
    attempt,
    submitError,
    submitErrorData,
    reset: resetAttempt,
  } = useAttemptSubmit({
    itemType:
      (currentItem?.type as "passage" | "repeat" | "question") ?? "repeat",
    itemId: currentItem?.id ?? "",
    sessionId: plan?.session_id,
  })

  const recorder = useRecorder({
    onComplete: (rec) => {
      submittedRef.current = true
      if (currentItem) setPinnedItemId(currentItem.id)
      // 使用录音开始时钉住的目标，避免录音期间计划刷新导致提交到新题新轮
      submit(
        { blob: rec.blob, duration: rec.duration },
        recordingTargetRef.current ?? undefined,
      )
    },
  })

  // 开始录音前钉住当前题 / 会话 / 题型 / 幂等键 / 凭证
  const startRecording = () => {
    recordingTargetRef.current = {
      itemType:
        (currentItem?.type as "passage" | "repeat" | "question") ?? "repeat",
      itemId: currentItem?.id ?? "",
      sessionId: plan?.session_id,
      idempotencyKey: crypto.randomUUID(),
    }
    recorder.start()
  }

  // 重传：用相同幂等键重新提交同一段录音（断网/超时后恢复）
  const retrySubmit = () => {
    if (recorder.recording) {
      submittedRef.current = true
      submit(
        {
          blob: recorder.recording.blob,
          duration: recorder.recording.duration,
        },
        recordingTargetRef.current ?? undefined,
      )
    }
  }

  // 录音中离开：刷新/关闭浏览器前确认（录音未提交会被丢弃）
  useEffect(() => {
    if (recorder.status !== "recording") return
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault()
    }
    window.addEventListener("beforeunload", handler)
    return () => window.removeEventListener("beforeunload", handler)
  }, [recorder.status])

  useEffect(() => {
    if (submitError) {
      const status = submitErrorData?.status
      if (status === 503) {
        toast.error("评分队列繁忙", {
          description: "录音已保留，请稍后点重传",
        })
      } else {
        toast.error("上传失败", {
          description: "录音已保留，可以点重传或重新录一次",
        })
      }
    }
  }, [submitError, submitErrorData])

  // 评分状态：上传中或排队/评分中都算「评分中」，期间禁用麦克风
  const attemptStatus = attempt?.status
  const attemptTerminal = isTerminal(attemptStatus)
  const attemptFailed = attemptStatus === "failed"
  const scoring =
    submitting || (attemptStatus !== undefined && !attemptTerminal)
  const recorderReset = recorder.reset

  // 评分完成：同步今日计划（进度、升降档后的问答）；保留单题简短反馈，学生点击后继续
  useEffect(() => {
    if (!attemptTerminal) return
    void queryClient.invalidateQueries({
      queryKey: ["classroom", code, "today", student?.id],
    })
    if (attemptFailed) {
      toast.error("这次没有评出来", { description: "可以再录一次" })
      return
    }
  }, [attemptTerminal, attemptFailed, queryClient, code, student?.id])

  // 全部完成后自动进入结果页统一展示（本次停留提交过 + 本地评分已结束 + 服务端计划全部完成）
  useEffect(() => {
    if (!allDone || !submittedRef.current || navigatedRef.current) return
    if (attemptStatus !== undefined) return
    if (attemptFailed) return
    navigatedRef.current = true
    void navigate({
      to: "/p/$code/result",
      params: { code },
      search: exploreSessionId ? { explore: exploreSessionId } : {},
    })
  }, [allDone, attemptStatus, attemptFailed, navigate, code, exploreSessionId])

  if (student === null) return null

  if (todayQuery.isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        正在加载今日练习…
      </div>
    )
  }
  if (todayQuery.isError || !plan) {
    const detail = (todayQuery.error as { body?: { detail?: string } })?.body
      ?.detail
    const contentMissing =
      detail === "No active passage" ||
      detail === "No repeat sentences configured"
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 text-muted-foreground">
        {contentMissing ? (
          <>
            今天还没有可以练习的内容。
            <span className="text-sm">
              请联系老师在后台配置篇目和复述句，配好后回来刷新即可。
            </span>
          </>
        ) : (
          "练习加载失败，请刷新重试。"
        )}
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

  const isQuestion = currentItem.type === "question"
  // 其余题都已完成 → 当前是最后一题（评分完成后直接进结果页）
  const isLastQuestion = items.every(
    (item) =>
      item.id === currentItem.id ||
      isTerminal(attemptByItem.get(item.id)?.status),
  )

  const isPassage = currentItem.type === "passage"
  const itemPromptLabel = isQuestion
    ? "YOUR TURN · 分享你的想法"
    : isPassage
      ? "READ ALOUD · 大声朗读全文"
      : "LISTEN & REPEAT · 听一听，再试着说"
  const itemHintZh = isQuestion
    ? "试着说出你的观点，再用一个理由或小例子支持它。"
    : isPassage
      ? "先扫一眼生词，然后完整朗读。停顿和语调自然比逐词准确更重要。"
      : "先听完整句子，再跟着节奏说。比起说得快，说得自然更重要。"

  return (
    <StudentShell active="practice">
      <div className="flex flex-col gap-6">
        {/* 顶部：进度步骤条 + HUD */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold tracking-tight">
              第 {currentIndex + 1}/{items.length} 题 ·{" "}
              {BAND_LABELS[plan.band] ?? plan.band}
              {plan.assigned_unit_title && (
                <span className="ml-2 text-sm font-medium text-primary">
                  📌 {plan.assigned_unit_title}
                </span>
              )}
            </h1>
            <p className="mt-1 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
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
              <Link
                to="/p/$code/result"
                params={{ code }}
                search={exploreSessionId ? { explore: exploreSessionId } : {}}
              >
                结果页
              </Link>
            </Button>
          </div>
        </div>

        {/* 步骤条 */}
        <div
          role="progressbar"
          className="flex items-center gap-2"
          aria-label="练习进度"
        >
          {items.map((item, i) => {
            const status = attemptByItem.get(item.id)?.status
            const done = status === "done" || status === "failed"
            return (
              <span
                key={item.id}
                className={
                  i === currentIndex
                    ? "h-1.5 flex-1 rounded-full bg-orange-400"
                    : done
                      ? "h-1.5 flex-1 rounded-full bg-primary"
                      : "h-1.5 flex-1 rounded-full bg-border"
                }
              />
            )
          })}
        </div>

        <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_270px]">
          <div className="grid gap-5">
            {/* 练习主卡 */}
            <Card>
              <CardContent className="space-y-5 pt-6">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs font-semibold tracking-wide text-primary">
                    {itemPromptLabel}
                  </span>
                  <span className="rounded-md bg-background px-2 py-0.5 text-[11px] text-muted-foreground">
                    {ITEM_TYPE_LABELS[currentItem.type] ?? currentItem.type}
                    {isQuestion && currentItem.band
                      ? ` · ${BAND_LABELS[currentItem.band] ?? currentItem.band}`
                      : ""}
                    {" · "}
                    {formatSeconds(currentItem.suggested_seconds ?? 20)}
                  </span>
                </div>

                <p className="prompt-display min-h-24">
                  {hideText
                    ? "原文已收起。试着回想刚刚听到的内容。"
                    : currentItem.text}
                </p>
                <p className="text-xs text-muted-foreground">
                  {hideText
                    ? "想不起来也没关系，随时可以重新看看。"
                    : (currentItem.translation ?? itemHintZh)}
                </p>

                {currentItem.type === "repeat" ? (
                  <LimitedListenButton
                    key={currentItem.id}
                    code={code.toUpperCase()}
                    sessionId={plan?.session_id}
                    itemId={currentItem.id}
                    text={currentItem.text}
                    audioUrl={currentItem.audio_url}
                    replayLimit={currentItem.replay_limit ?? 3}
                    initialUsed={currentItem.listen_used ?? 0}
                  />
                ) : (
                  <SpeakButton
                    key={currentItem.id}
                    text={currentItem.text}
                    audioUrl={currentItem.audio_url}
                  />
                )}
                {!isQuestion && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-xs text-primary"
                    onClick={() => setHideText(!hideText)}
                  >
                    {hideText ? "显示原文" : "收起原文（练记忆）"}
                  </Button>
                )}
                {isQuestion && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-xs text-primary"
                    onClick={() => nextQuestionMutation.mutate()}
                    disabled={nextQuestionMutation.isPending}
                  >
                    换一题（同主题）
                  </Button>
                )}

                <Separator />

                {/* 录音区（SpeakUp：大圆钮 + 波形） */}
                <div className="flex flex-col items-center gap-1 border-t pt-5 text-center">
                  {recorder.status === "recording" ? (
                    <>
                      <div
                        className="flex h-8 items-center justify-center gap-1"
                        aria-hidden
                      >
                        {Array.from({ length: 25 }).map((_, i) => (
                          <i
                            key={i}
                            className="wave-bar block w-[3px] rounded bg-primary"
                            style={{
                              height: `${[7, 20, 29, 13, 18, 24, 10, 16, 28, 12][i % 10]}px`,
                              animationDelay: `${(i % 5) * -0.2}s`,
                            }}
                          />
                        ))}
                      </div>
                      <button
                        type="button"
                        onClick={recorder.stop}
                        aria-label="结束录音"
                        className="record-pulse mt-3 grid size-[72px] place-items-center rounded-full bg-destructive text-white shadow-[0_0_0_7px_var(--accent)] transition hover:scale-105"
                      >
                        <Square className="size-7" />
                      </button>
                      <p className="mt-4 text-sm">
                        <span className="font-mono tabular-nums">
                          {formatSeconds(recorder.elapsed)}
                        </span>{" "}
                        · 说完后点一下结束
                      </p>
                      <p className="text-xs text-muted-foreground">
                        最长 {formatSeconds(MAX_RECORD_SECONDS)} ·
                        不用着急，按自己的节奏说
                      </p>
                    </>
                  ) : submitError && recorder.recording ? (
                    <>
                      <button
                        type="button"
                        onClick={retrySubmit}
                        disabled={submitting}
                        aria-label="重传录音"
                        className="mt-1 grid size-[72px] place-items-center rounded-full bg-primary text-white shadow-[0_0_0_7px_var(--secondary)] transition hover:scale-105 disabled:opacity-50"
                      >
                        <ArrowRight className="size-7" />
                      </button>
                      <p className="mt-4 text-sm text-destructive">
                        上传失败，录音已保留
                      </p>
                      <p className="text-xs text-muted-foreground">
                        点这里重传 · 或
                        <button
                          type="button"
                          onClick={startRecording}
                          className="ml-1 underline text-primary"
                        >
                          重新录
                        </button>
                      </p>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={startRecording}
                        disabled={scoring}
                        aria-label="开始录音"
                        className="mt-1 grid size-[72px] place-items-center rounded-full bg-primary text-white shadow-[0_0_0_7px_var(--secondary)] transition hover:scale-105 disabled:opacity-50"
                      >
                        <Mic className="size-7" />
                      </button>
                      <p className="mt-4 text-sm">
                        {scoring
                          ? "已提交，正在出反馈…"
                          : recorder.status === "ready"
                            ? "这一次开口，已记录"
                            : "准备好了，就点一下麦克风"}
                      </p>
                      {scoring ? (
                        <p className="text-xs text-muted-foreground">
                          {isLastQuestion
                            ? "先显示本题分数和转写"
                            : "先显示本题分数和转写，详细评价最后看"}
                        </p>
                      ) : attemptFailed ? (
                        <p className="text-xs text-destructive">
                          这次没有评出来，再录一次就好
                        </p>
                      ) : (
                        <p className="text-xs text-muted-foreground">
                          需要麦克风权限 · 每一次练习都有意义
                        </p>
                      )}
                    </>
                  )}
                  {recorder.error && (
                    <p className="mt-1 text-sm text-destructive">
                      {recorder.error}
                    </p>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>

          <aside className="grid gap-4">
            <Card className="border-secondary bg-secondary/60">
              <CardContent className="space-y-2 py-4">
                <p className="flex items-center gap-1.5 text-sm font-semibold">
                  <Sparkles className="size-4 text-primary" /> 一个小小的提示
                </p>
                {isQuestion ? (
                  <>
                    <p className="text-sm text-muted-foreground">
                      不用寻找「标准答案」。试试这个顺序，让你的表达更完整。
                    </p>
                    <p className="font-serif text-xl">I think… because…</p>
                    <p className="text-xs text-muted-foreground">
                      我的观点 → 一个理由 → 一个小例子
                    </p>
                  </>
                ) : (
                  <>
                    <p className="text-sm text-muted-foreground">
                      先听完整句子，再跟着意群停顿。比起说得快，说得自然更重要。
                    </p>
                    <p className="font-serif text-xl">Listen. Pause. Speak.</p>
                    <p className="text-xs text-muted-foreground">
                      听一遍 · 想一想 · 大胆说
                    </p>
                  </>
                )}
              </CardContent>
            </Card>

            <Card className="hidden lg:block">
              <CardContent className="py-4">
                <p className="mb-3 text-sm font-semibold">今天的路线</p>
                {[
                  {
                    icon: Headphones,
                    title: "听句复述",
                    sub: "3 个短句",
                    active: !isQuestion,
                  },
                  {
                    icon: MessageCircle,
                    title: "情景问答",
                    sub: "2 个问题",
                    active: isQuestion,
                  },
                  {
                    icon: ChartLine,
                    title: "看看收获",
                    sub: "全部完成后一起看",
                    active: allDone,
                  },
                ].map((step) => (
                  <div
                    key={step.title}
                    className={
                      step.active
                        ? "flex items-center gap-2.5 py-2.5 text-sm font-semibold text-primary"
                        : "flex items-center gap-2.5 py-2.5 text-sm text-muted-foreground"
                    }
                  >
                    <span
                      className={
                        step.active
                          ? "grid size-7 place-items-center rounded-full bg-secondary text-primary"
                          : "grid size-7 place-items-center rounded-full bg-background text-muted-foreground"
                      }
                    >
                      <step.icon className="size-3.5" />
                    </span>
                    <span>
                      {step.title}
                      <span className="block text-[10px] font-normal text-muted-foreground">
                        {step.sub}
                      </span>
                    </span>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card className="hidden lg:block">
              <CardContent className="flex items-start gap-2 py-3.5 text-xs text-muted-foreground">
                <Shield className="mt-0.5 size-3.5 shrink-0 text-primary" />
                每次录音只有你自己和本课授权老师能回听。说错了没关系，再录一次就好。
              </CardContent>
            </Card>
          </aside>
        </div>

        {attempt && attemptTerminal && (
          <FeedbackCard
            attempt={attempt}
            itemType={currentItem?.type as "passage" | "repeat" | "question"}
            onRepractice={() => {
              // 主动重录：清提交标记，避免重置后 allDone 触发自动跳转结果页
              submittedRef.current = false
              resetAttempt()
              recorderReset()
            }}
            extraActions={
              !attemptFailed && (
                <Button
                  onClick={() => {
                    setPinnedItemId(null)
                    setFocusItemId(null)
                    recorderReset()
                    resetAttempt()
                  }}
                >
                  {allDone ? "查看详细总反馈" : "下一题"}
                  <ArrowRight />
                </Button>
              )
            }
          />
        )}
        <p className="text-center text-sm text-muted-foreground">
          每题先看分数和转写，完成后查看全面评价与改进建议。
        </p>

        {allDone && (
          <Button size="lg" asChild>
            <Link
              to="/p/$code/result"
              params={{ code }}
              search={exploreSessionId ? { explore: exploreSessionId } : {}}
            >
              查看本轮结果
            </Link>
          </Button>
        )}

        <p className="pb-6 text-center text-xs text-muted-foreground">
          分数是参考反馈，不是考试成绩。
        </p>
      </div>
    </StudentShell>
  )
}

/**
 * 限听版标准音：听句复述题专用。每次播放先到服务端计数（防刷真源），
 * 次数用完禁用；replay_limit=0 不限。朗读/问答仍用不限次 SpeakButton。
 */
function LimitedListenButton({
  code,
  sessionId,
  itemId,
  text,
  audioUrl,
  replayLimit,
  initialUsed,
}: {
  code: string
  sessionId: string | undefined
  itemId: string
  text: string
  audioUrl?: string | null
  replayLimit: number
  initialUsed: number
}) {
  const [used, setUsed] = useState(initialUsed)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const unlimited = replayLimit === 0
  const remaining = unlimited ? Infinity : Math.max(0, replayLimit - used)
  const exhausted = !unlimited && remaining <= 0

  const play = async () => {
    if (exhausted || !sessionId) return
    // 先到服务端计数再播：422 = 次数真用完；其他错误（网络等）不锁死按钮
    const counted = await recordListenCount()
    if (!counted) return
    setUsed((u) => u + 1)
    if (audioUrl) {
      audioRef.current?.play()
      return
    }
    // TTS 兜底：浏览器合成没有服务端文件，仍走计数
    const synth = window.speechSynthesis
    if (!synth) return
    synth.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = "en-US"
    synth.speak(utterance)
  }

  const recordListenCount = async (): Promise<boolean> => {
    if (!sessionId) return false
    try {
      await ClassesService.recordListen({
        code,
        requestBody: { session_id: sessionId, item_id: itemId },
      })
      return true
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        toast.error("可重听次数已用完")
        setUsed(replayLimit)
      } else {
        toast.error("听音失败，请检查网络后重试")
      }
      return false
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      {audioUrl && (
        <audio
          ref={audioRef}
          src={audioUrl.startsWith("/") ? `${API_BASE}${audioUrl}` : audioUrl}
          preload="metadata"
          hidden
        >
          <track kind="captions" />
        </audio>
      )}
      <Button
        variant="secondary"
        size="lg"
        onClick={() => void play()}
        disabled={exhausted}
      >
        <Volume2 />
        {exhausted ? "重听次数已用完" : "听示范"}
      </Button>
      <span className="text-xs text-muted-foreground">
        {unlimited ? "重听不限次" : `还可重听 ${remaining} 次`}
      </span>
    </div>
  )
}
