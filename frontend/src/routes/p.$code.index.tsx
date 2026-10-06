import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  useBlocker,
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
  Star,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import type { PlanAttempt, PlanItem } from "@/client"
import { ClassesService } from "@/client"
import FeedbackCard from "@/components/Practice/FeedbackCard"
import LimitedListenButton from "@/components/Practice/LimitedListenButton"
import SpeakButton from "@/components/Practice/SpeakButton"
import StudentShell from "@/components/Practice/StudentShell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { APP_NAME } from "@/config"
import type { AttemptSubmitTarget } from "@/hooks/useAttemptSubmit"
import { useAttemptSubmit } from "@/hooks/useAttemptSubmit"
import { MAX_RECORD_SECONDS, useRecorder } from "@/hooks/useRecorder"
import { useStudentGuard } from "@/hooks/useStudentGuard"
import { displayName, loadStudent } from "@/lib/classroom-student"
import { useI18n } from "@/lib/i18n"
import {
  EXAM_KIND_LABELS,
  EXAM_LEVEL_LABELS,
  EXAM_PRACTICE_NOTE,
  FRAME_PURPOSE_LABELS,
  ITEM_TYPE_LABELS,
  TERMS,
} from "@/lib/terms"
import { randomId } from "@/utils"

export const Route = createFileRoute("/p/$code/")({
  component: ClassroomPracticePage,
  validateSearch: (
    search: Record<string, unknown>,
  ): {
    focus?: string
    next?: boolean
    explore?: string
    session?: string
  } => {
    // 只序列化真值，避免 URL 出现 ?focus=undefined&next=false
    const result: {
      focus?: string
      next?: boolean
      explore?: string
      session?: string
    } = {}
    if (typeof search.focus === "string") result.focus = search.focus
    if (search.next === true) result.next = true
    if (typeof search.explore === "string") result.explore = search.explore
    if (typeof search.session === "string") result.session = search.session
    return result
  },
  head: () => ({
    meta: [{ title: `今日练习 / Today's Practice - ${APP_NAME}` }],
  }),
})

function formatSeconds(seconds: number): string {
  const whole = Math.floor(seconds)
  return `${String(Math.floor(whole / 60)).padStart(1, "0")}:${String(whole % 60).padStart(2, "0")}`
}

function formatExamCountdown(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60)
  const s = totalSeconds % 60
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
}

function isTerminal(status: string | undefined): boolean {
  return status === "done" || status === "failed"
}

function ClassroomPracticePage() {
  const { t } = useI18n()
  const { code } = useParams({ from: "/p/$code/" })
  const {
    focus: focusParam,
    next: nextFlag,
    explore: exploreSessionId,
    session: sessionParam,
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
  // 活动会话边界：录音开始（或从结果页带回 session）时钉住本轮会话，
  // 期间老师发布新计划也不会把旧反馈/旧题挂到新题；点「下一题」后解除。
  const [pinnedSessionId, setPinnedSessionId] = useState<string | null>(
    sessionParam ?? null,
  )
  // 复述题「收起原文」练记忆（Charcoal）
  const [hideText, setHideText] = useState(false)
  // 录音开始时钉住 item_id / session_id / 题型：录音期间老师切换指派不影响旧录音
  const recordingTargetRef = useRef<AttemptSubmitTarget | null>(null)
  // 本次停留是否提交过录音：防止从结果页回来时 allDone 直接又跳回结果页
  const submittedRef = useRef(false)
  // 自动跳结果页的闩锁：每次挂载最多跳一次
  const navigatedRef = useRef(false)

  // 有效会话：优先钉住的会话（录音/回看期间保持同一轮），其次探索轮
  const sessionId = pinnedSessionId ?? exploreSessionId
  // 今日计划查询键：sessionId 为空时与 StudentShell 的 NotificationBell 同 key
  // （共享缓存，避免进练习页后铃铛+页面各拉一次同端点）；有会话时多一位区分数据。
  // invalidate 用同一变量，避免前缀匹配错位
  const todayQueryKey = [
    "classroom",
    code,
    "today",
    student?.id,
    ...(sessionId ? [sessionId] : []),
  ] as const

  const todayQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: todayQueryKey,
    queryFn: () =>
      ClassesService.readTodayPlan({
        code: code.toUpperCase(),
        ...(sessionId ? { sessionId } : {}),
      }),
    enabled: student !== null,
    refetchInterval: (query) =>
      query.state.data?.attempts.some((a) => !isTerminal(a.status))
        ? 2000
        : 30000, // 慢速同步：老师中途指派新单元时学生端最迟 30 秒感知
  })

  // 身份守卫：无本地身份跳加入页；查询报"学生不存在"清身份重进（5 页共用 hook）
  useStudentGuard(code, student, todayQuery)

  // 换一题：同主题同档未做过（US-06）；探索轮绑定 session_id
  const nextQuestionMutation = useMutation({
    mutationFn: () =>
      ClassesService.readNextQuestion({
        code: code.toUpperCase(),
        ...(sessionId ? { sessionId } : {}),
        ...(items.length ? { excludeIds: items.map((i) => i.id) } : {}),
      }),
    onSuccess: (data) => {
      if (data.question) {
        // 显式契约转换：ScenarioQuestionPublic → PlanItem(type="question")，
        // 不使用类型断言冒充数据转换。换来的题必须带 question 题型才能正确
        // 展示/提交/进结果页，刷新后由后端从 attempt.item_snapshot 恢复。
        const q = data.question
        const extraItem: PlanItem = {
          type: "question",
          id: q.id,
          text: q.text,
          band: q.band,
          audio_url: q.audio_url,
          suggested_seconds: q.suggested_seconds,
          // 分级题型训练：换一题保留考试字段（话题卡/准备时间不丢）
          exam_kind: q.exam_kind ?? null,
          exam_level: q.exam_level ?? null,
          cue_card_bullets: q.cue_card_bullets ?? null,
          prep_seconds: q.prep_seconds ?? null,
        }
        setExtraQuestion(extraItem)
        queryClient.invalidateQueries({ queryKey: todayQueryKey })
      } else {
        toast.info(
          t({
            zh: "这个主题的题已练完",
            en: "You've finished the questions on this topic",
          }),
          {
            description: t({
              zh: "可以重录上一题继续 polish",
              en: "Re-record the last one to keep polishing",
            }),
          },
        )
      }
    },
  })

  // 结果页「换同主题下一问」跳转过来（?next=1）时执行换题（闩锁保证只触发一次）
  const nextFlagConsumedRef = useRef(false)
  useEffect(() => {
    // 等计划加载后再换题：否则 plan?.session_id 为空，探索轮会取错主题
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
      toast.error(t({ zh: "换题失败", en: "Couldn't switch question" }), {
        description: t({
          zh: "练习计划加载失败，请返回重试",
          en: "The practice plan failed to load — please go back and retry",
        }),
      })
    }
  }, [nextFlag, todayQuery.isError, t])

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
  // 句型收藏（PR B）：按单条表达收藏/取消，挂课堂档案跨设备可见
  const frameFavorite = useMutation({
    mutationFn: (frameId: string) =>
      ClassesService.addFrameFavorite({
        code: code.toUpperCase(),
        requestBody: { frame_id: frameId },
      }),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: todayQueryKey }),
  })
  const unfavorite = useMutation({
    mutationFn: (frameId: string) =>
      ClassesService.removeFrameFavorite({
        code: code.toUpperCase(),
        frameId,
      }),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: todayQueryKey }),
  })

  // 分级题型训练：exam_kind（考试式题型）× exam_level（五级）两维分别建模；
  // 可空 = 普通课堂内容，展示与流程不变。hook 必须在条件 return 之前。
  const examKind = currentItem?.exam_kind ?? null
  const examLevel = currentItem?.exam_level ?? null
  const isIeltsPart2 = examKind === "ielts_p2"
  const cueBullets = currentItem?.cue_card_bullets ?? []
  const prepSeconds = isIeltsPart2 ? (currentItem?.prep_seconds ?? 60) : 0
  const [prepLeft, setPrepLeft] = useState(0)
  const [prepDone, setPrepDone] = useState(true)
  const [prepForItem, setPrepForItem] = useState<string | null>(null)
  // 切题即重置准备计时（渲染期比较是 React 官方认可的 state 调整模式，
  // 避免 biome 判定 effect 依赖多余）
  const itemId = currentItem?.id ?? null
  if (itemId !== prepForItem) {
    setPrepForItem(itemId)
    setPrepLeft(isIeltsPart2 ? prepSeconds : 0)
    setPrepDone(!isIeltsPart2 || prepSeconds <= 0)
  }
  useEffect(() => {
    if (prepDone) return
    const timer = window.setInterval(() => {
      setPrepLeft((left) => {
        if (left <= 1) {
          window.clearInterval(timer)
          setPrepDone(true)
          return 0
        }
        return left - 1
      })
    }, 1000)
    return () => window.clearInterval(timer)
  }, [prepDone])
  const skipPrep = () => {
    setPrepDone(true)
    setPrepLeft(0)
  }
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
      // 模考不钉住题目：提交后自动推进到下一道未做题（也不展示本题反馈）
      if (currentItem && !examActive) setPinnedItemId(currentItem.id)
      // 使用录音开始时钉住的目标，避免录音期间计划刷新导致提交到新题新轮
      submit(
        { blob: rec.blob, duration: rec.duration },
        recordingTargetRef.current ?? undefined,
      )
    },
  })

  // 开始录音前钉住当前题 / 会话 / 题型 / 幂等键 / 凭证；
  // 同时钉住会话：录音→上传→反馈期间老师发布新计划，练习页仍保持本轮，
  // 结果页也绑定这个实际完成的会话，不挂到新题新轮。
  const startRecording = () => {
    recordingTargetRef.current = {
      itemType:
        (currentItem?.type as "passage" | "repeat" | "question") ?? "repeat",
      itemId: currentItem?.id ?? "",
      sessionId: plan?.session_id,
      idempotencyKey: randomId(),
    }
    setPinnedSessionId(plan?.session_id ?? null)
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

  // 录音/上传/失败待重传期间的离开保护（站内跳转 + 浏览器关闭/刷新）
  const pendingBlockerActive =
    recorder.status === "recording" ||
    submitting ||
    (submitError && Boolean(recorder.recording))
  const blockerToastRef = useRef(false)
  useBlocker({
    shouldBlockFn: ({ current, next }) => {
      if (!pendingBlockerActive) return false
      // 同一课堂内练习页互相跳转不算离开（结果页 / 练习页 / 加入页保留原状）
      if (current.pathname === next.pathname) return false
      if (!blockerToastRef.current) {
        blockerToastRef.current = true
        toast.warning(
          recorder.status === "recording"
            ? t({
                zh: "正在录音，先结束或确认录音后再离开",
                en: "Recording in progress — stop or confirm the recording before leaving",
              })
            : submitting
              ? t({
                  zh: "录音正在上传，请稍候或完成后再离开",
                  en: "Your recording is uploading — please wait or finish before leaving",
                })
              : t({
                  zh: "录音上传失败，请先重传或重录",
                  en: "Upload failed — please retry the upload or re-record first",
                }),
        )
        window.setTimeout(() => {
          blockerToastRef.current = false
        }, 2000)
      }
      return true
    },
    enableBeforeUnload: () => pendingBlockerActive,
  })

  useEffect(() => {
    if (submitError) {
      const status = submitErrorData?.status
      if (status === 503) {
        toast.error(t({ zh: "评分队列繁忙", en: "Scoring queue is busy" }), {
          description: t({
            zh: "录音已保留，请稍后点重传",
            en: "Your recording is saved — tap retry in a moment",
          }),
        })
      } else {
        toast.error(t({ zh: "上传失败", en: "Upload failed" }), {
          description: t({
            zh: "录音已保留，可以点重传或重新录一次",
            en: "Your recording is saved — retry the upload or record again",
          }),
        })
      }
    }
  }, [submitError, submitErrorData, t])

  // 评分状态：上传中或排队/评分中都算「评分中」，期间禁用麦克风
  const attemptStatus = attempt?.status
  const attemptTerminal = isTerminal(attemptStatus)
  const attemptFailed = attemptStatus === "failed"

  // ── 模考态 ──
  const exam = plan?.exam ?? null
  const examActive = exam !== null && !exam.ended
  const examEnded = exam?.ended ?? false
  // 当前题是否已作答（考试一次性口径：有终态作答即锁定）
  const currentItemDone = currentItem
    ? isTerminal(attemptByItem.get(currentItem.id)?.status)
    : false

  // 本地倒计时：以服务端 remaining_seconds 为准心，每秒递减仅作展示
  const examServerRemaining = exam?.remaining_seconds
  const [examRemaining, setExamRemaining] = useState<number | null>(null)
  useEffect(() => {
    if (examServerRemaining !== undefined) setExamRemaining(examServerRemaining)
  }, [examServerRemaining])
  const examTimerActive = examRemaining !== null
  useEffect(() => {
    if (!examTimerActive) return
    const timer = setInterval(() => {
      setExamRemaining((v) => (v === null ? v : Math.max(0, v - 1)))
    }, 1000)
    return () => clearInterval(timer)
  }, [examTimerActive])
  // 倒计时归零：拉取服务端终态（惰性交卷在那边落库）
  useEffect(() => {
    if (examRemaining === 0 && examActive) {
      void queryClient.invalidateQueries({ queryKey: todayQueryKey })
    }
  }, [examRemaining, examActive, queryClient, todayQueryKey])
  // 考试结束（到时/服务端判定）：自动进结果页（= 交卷）
  const examNavigatedRef = useRef(false)
  useEffect(() => {
    if (!examEnded || examNavigatedRef.current) return
    examNavigatedRef.current = true
    void navigate({
      to: "/p/$code/result",
      params: { code },
      search: sessionId ? { session: sessionId } : {},
    })
  }, [examEnded, navigate, code, sessionId])

  // 防切屏：考试期间离开页面（切 tab/最小化）上报并提示
  useEffect(() => {
    if (!examActive || !plan?.session_id) return
    const onVisibility = () => {
      if (document.visibilityState !== "hidden") return
      void ClassesService.reportExamViolation({
        code: code.toUpperCase(),
        requestBody: { session_id: plan.session_id },
      }).catch(() => {
        /* 上报失败不打断考试 */
      })
      toast.warning(
        t({ zh: "考试中请勿切屏", en: "Stay on this screen during the exam" }),
        {
          description: t({
            zh: "本次切屏已被记录，老师可见",
            en: "This switch has been recorded and is visible to your teacher",
          }),
        },
      )
    }
    document.addEventListener("visibilitychange", onVisibility)
    return () => document.removeEventListener("visibilitychange", onVisibility)
  }, [examActive, plan?.session_id, code, t])
  const scoring =
    submitting || (attemptStatus !== undefined && !attemptTerminal)
  const recorderReset = recorder.reset

  // 评分完成：同步今日计划（进度、升降档后的问答）；保留单题简短反馈，学生点击后继续
  useEffect(() => {
    if (!attemptTerminal) return
    void queryClient.invalidateQueries({ queryKey: todayQueryKey })
    if (attemptFailed) {
      toast.error(t({ zh: "这次没有评出来", en: "No score this time" }), {
        description: t({
          zh: "可以再录一次",
          en: "You can record again",
        }),
      })
      return
    }
  }, [attemptTerminal, attemptFailed, queryClient, todayQueryKey, t])

  // 全部完成后自动进入结果页统一展示（本次停留提交过 + 本地评分已结束 + 服务端计划全部完成）
  useEffect(() => {
    if (!allDone || !submittedRef.current || navigatedRef.current) return
    if (attemptStatus !== undefined) return
    if (attemptFailed) return
    navigatedRef.current = true
    void navigate({
      to: "/p/$code/result",
      params: { code },
      // 结果页绑定实际完成会话（钉住的会话），老师发布新计划也不串轮
      search: sessionId ? { session: sessionId } : {},
    })
  }, [allDone, attemptStatus, attemptFailed, navigate, code, sessionId])

  if (student === null) return null

  if (todayQuery.isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        {t({ zh: "正在加载今日练习…", en: "Loading today's practice…" })}
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
            {t({
              zh: "今天还没有可以练习的内容。",
              en: "No practice content is available today.",
            })}
            <span className="text-sm">
              {t({
                zh: "请联系老师在后台配置篇目和复述句，配好后回来刷新即可。",
                en: "Please ask your teacher to set up passages and repeat sentences; refresh here once they're ready.",
              })}
            </span>
          </>
        ) : (
          t({
            zh: "练习加载失败，请刷新重试。",
            en: "Practice failed to load — please refresh and retry.",
          })
        )}
        <Button variant="outline" onClick={() => todayQuery.refetch()}>
          {t({ zh: "重试", en: "Retry" })}
        </Button>
      </div>
    )
  }

  if (!currentItem) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        {t({ zh: "今天没有练习内容。", en: "No practice content today." })}
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
  const itemPromptLabel = examKind
    ? t(EXAM_KIND_LABELS[examKind] ?? { zh: examKind, en: examKind })
    : isQuestion
      ? t({
          zh: "YOUR TURN · 分享你的想法",
          en: "YOUR TURN · Share your thoughts",
        })
      : isPassage
        ? t({
            zh: "READ ALOUD · 大声朗读全文",
            en: "READ ALOUD · Read the full text aloud",
          })
        : t({
            zh: "LISTEN & REPEAT · 听一听，再试着说",
            en: "LISTEN & REPEAT · Listen, then try to say it",
          })
  const itemHintZh = isQuestion
    ? t({
        zh: "试着说出你的观点，再用一个理由或小例子支持它。",
        en: "State your opinion, then back it up with a reason or a quick example.",
      })
    : isPassage
      ? t({
          zh: "先扫一眼生词，然后完整朗读。停顿和语调自然比逐词准确更重要。",
          en: "Skim the new words first, then read it through. Natural pauses and intonation matter more than word-by-word accuracy.",
        })
      : t({
          zh: "先听完整句子，再跟着节奏说。比起说得快，说得自然更重要。",
          en: "Listen to the full sentence first, then follow its rhythm. Sounding natural beats speaking fast.",
        })

  return (
    <StudentShell active="practice">
      <div className="flex flex-col gap-6">
        {/* 顶部：进度步骤条 + HUD */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold tracking-tight">
              {t({
                zh: `第 ${currentIndex + 1}/${items.length} 题`,
                en: `Item ${currentIndex + 1}/${items.length}`,
              })}
              {plan.assigned_unit_title && (
                <span className="ml-2 text-sm font-medium text-primary">
                  📌 {plan.assigned_unit_title}
                </span>
              )}
            </h1>
            <p className="mt-1 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
              {displayName(student)} ·{" "}
              {t({
                zh: `课堂 ${plan.classroom_code}`,
                en: `Classroom ${plan.classroom_code}`,
              })}
              {plan.gamification && (
                <>
                  <span className="flex items-center gap-1">
                    <Flame className="size-4 text-orange-500" />
                    {t({
                      zh: `${plan.gamification.streak_days} 天`,
                      en: `${plan.gamification.streak_days} days`,
                    })}
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
                search={sessionId ? { session: sessionId } : {}}
              >
                {t({ zh: "结果页", en: "Results" })}
              </Link>
            </Button>
          </div>
        </div>

        {exam && (
          <div
            role="status"
            className={`flex flex-wrap items-center justify-between gap-2 rounded-xl border px-4 py-3 ${
              examEnded
                ? "border-destructive/30 bg-destructive/5"
                : "border-orange-300/50 bg-orange-50 dark:bg-orange-950/30"
            }`}
          >
            <p className="text-sm font-semibold">
              {examEnded
                ? t({ zh: "考试已结束", en: "The exam has ended" })
                : t({ zh: "模考进行中", en: "Exam in progress" })}
              {examActive && (
                <span className="ml-2 font-mono text-base tabular-nums">
                  {formatExamCountdown(examRemaining ?? exam.remaining_seconds)}
                </span>
              )}
            </p>
            <p className="text-xs text-muted-foreground">
              {examEnded
                ? t({
                    zh: "时间到已自动交卷，正在进入结果页…",
                    en: "Time is up — auto-submitted. Opening results…",
                  })
                : t({
                    zh: "整场限时 · 每题只能作答一次 · 切屏会被记录",
                    en: "Time-limited · one attempt per item · screen switches are recorded",
                  })}
            </p>
          </div>
        )}

        {/* 步骤条 */}
        <div
          role="progressbar"
          className="flex items-center gap-2"
          aria-label={t({ zh: "练习进度", en: "Practice progress" })}
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
                    {t(
                      ITEM_TYPE_LABELS[currentItem.type] ?? {
                        zh: currentItem.type,
                        en: currentItem.type,
                      },
                    )}
                    {" · "}
                    {formatSeconds(currentItem.suggested_seconds ?? 20)}
                  </span>
                </div>

                {/* 分级题型徽标：题型 × 级别（两维分别建模） */}
                {examKind && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge variant="secondary">
                      {t(
                        EXAM_KIND_LABELS[examKind] ?? {
                          zh: examKind,
                          en: examKind,
                        },
                      )}
                    </Badge>
                    {examLevel && (
                      <Badge variant="outline">
                        {t(
                          EXAM_LEVEL_LABELS[examLevel] ?? {
                            zh: examLevel,
                            en: examLevel,
                          },
                        )}
                      </Badge>
                    )}
                  </div>
                )}

                {/* 可替换句型（PR B）：按表达用途分组，可收藏 */}
                {(currentItem.frames?.length ?? 0) > 0 && (
                  <div className="rounded-xl border border-dashed border-primary/30 bg-secondary/30 p-4">
                    <p className="text-xs font-semibold tracking-wide text-primary">
                      {t({
                        zh: "可替换句型 · 套用或改成你自己的表达",
                        en: "Sentence frames · use as-is or make them yours",
                      })}
                    </p>
                    <div className="mt-3 space-y-2">
                      {(currentItem.frames ?? []).map((frame) => (
                        <div
                          key={frame.id}
                          className="flex items-start justify-between gap-2 rounded-lg bg-background px-3 py-2"
                        >
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium">
                              {frame.text_en}
                            </p>
                            <p className="truncate text-xs text-muted-foreground">
                              {frame.text_zh}
                              {" · "}
                              {t(
                                FRAME_PURPOSE_LABELS[frame.purpose] ?? {
                                  zh: frame.purpose,
                                  en: frame.purpose,
                                },
                              )}
                            </p>
                          </div>
                          <button
                            type="button"
                            aria-pressed={frame.favorited}
                            aria-label={
                              frame.favorited
                                ? t({
                                    zh: "取消收藏",
                                    en: "Remove from favorites",
                                  })
                                : t({
                                    zh: "收藏这条句型",
                                    en: "Favorite this frame",
                                  })
                            }
                            disabled={frameFavorite.isPending}
                            onClick={() => {
                              if (frame.favorited) {
                                unfavorite.mutate(frame.id)
                              } else {
                                frameFavorite.mutate(frame.id)
                              }
                            }}
                            className="shrink-0 p-1 text-muted-foreground transition-colors hover:text-primary"
                          >
                            <Star
                              className={
                                frame.favorited
                                  ? "size-4 fill-amber-400 text-amber-400"
                                  : "size-4"
                              }
                            />
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* IELTS Part 2 话题卡 */}
                {isIeltsPart2 && cueBullets.length > 0 && (
                  <div className="rounded-xl border border-dashed border-primary/40 bg-secondary/40 p-4">
                    <p className="text-xs font-semibold tracking-wide text-primary">
                      {t({
                        zh: "话题卡 · 你可以谈到这些要点",
                        en: "Cue card · points you can cover",
                      })}
                    </p>
                    <ul className="mt-2 space-y-1 text-sm">
                      {cueBullets.map((bullet) => (
                        <li key={bullet} className="flex items-start gap-2">
                          <span
                            aria-hidden
                            className="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary/60"
                          />
                          <span>{bullet}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Part 2 准备时间倒计时（结束或跳过后才能开始录音） */}
                {isIeltsPart2 && !prepDone && (
                  <div
                    role="timer"
                    className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-secondary/60 px-4 py-3"
                  >
                    <p className="text-sm">
                      <span className="font-mono text-lg font-bold tabular-nums">
                        {formatSeconds(prepLeft)}
                      </span>{" "}
                      {t({
                        zh: "· 准备时间：先想好要说的要点，不用开口",
                        en: "· Prep time: plan your points, no need to speak yet",
                      })}
                    </p>
                    <Button variant="ghost" size="sm" onClick={skipPrep}>
                      {t({ zh: "跳过准备，直接开始", en: "Skip prep" })}
                    </Button>
                  </div>
                )}

                {currentItem.type === "repeat" ? (
                  <p className="prompt-display min-h-24 text-muted-foreground">
                    {t({
                      zh: "本题不显示文字。点下方「听示范」听语音，听完后复述出来。",
                      en: "No text for this item. Tap Listen below to hear it, then repeat what you heard.",
                    })}
                  </p>
                ) : (
                  <>
                    <p
                      className={`prompt-display min-h-24 ${exam ? "select-none" : ""}`}
                    >
                      {hideText
                        ? t({
                            zh: "原文已收起。试着回想刚刚听到的内容。",
                            en: "The text is hidden. Try to recall what you just heard.",
                          })
                        : currentItem.text}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {hideText
                        ? t({
                            zh: "想不起来也没关系，随时可以重新看看。",
                            en: "It's fine if you can't remember — you can peek anytime.",
                          })
                        : (currentItem.translation ?? itemHintZh)}
                    </p>
                  </>
                )}
                {currentItem.type === "repeat" && (
                  <p className="text-xs text-muted-foreground">{itemHintZh}</p>
                )}

                {currentItem.type === "repeat" ? (
                  // 听音状态按 session_id + item_id 隔离：会话变化时重建计数状态，
                  // 避免同一道题在新会话里沿用旧会话的已听次数。
                  <LimitedListenButton
                    key={`${plan?.session_id ?? ""}:${currentItem.id}`}
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
                {isPassage && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-xs text-primary"
                    onClick={() => setHideText(!hideText)}
                  >
                    {hideText
                      ? t({ zh: "显示原文", en: "Show text" })
                      : t({
                          zh: "收起原文（练记忆）",
                          en: "Hide text (memory practice)",
                        })}
                  </Button>
                )}
                {isQuestion && !exam && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-xs text-primary"
                    onClick={() => nextQuestionMutation.mutate()}
                    disabled={nextQuestionMutation.isPending}
                  >
                    {t({
                      zh: "再来一题（同主题，追加到本轮）",
                      en: "One more question (same topic)",
                    })}
                  </Button>
                )}

                <Separator />

                {/* 录音区（Charcoal：大圆钮 + 波形） */}
                <div className="flex flex-col items-center gap-1 border-t pt-5 text-center">
                  {examKind && (
                    <p className="mb-2 text-[11px] text-muted-foreground">
                      {t(EXAM_PRACTICE_NOTE)}
                    </p>
                  )}
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
                        aria-label={t({ zh: "结束录音", en: "Stop recording" })}
                        className="record-pulse mt-3 grid size-[72px] place-items-center rounded-full bg-destructive text-white shadow-[0_0_0_7px_var(--accent)] transition hover:scale-105"
                      >
                        <Square className="size-7" />
                      </button>
                      <p className="mt-4 text-sm">
                        <span className="font-mono tabular-nums">
                          {formatSeconds(recorder.elapsed)}
                        </span>{" "}
                        {t({
                          zh: "· 说完后点一下结束",
                          en: "· Tap stop when you're done",
                        })}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {t({
                          zh: `最长 ${formatSeconds(MAX_RECORD_SECONDS)} · 不用着急，按自己的节奏说`,
                          en: `Max ${formatSeconds(MAX_RECORD_SECONDS)} · No rush, speak at your own pace`,
                        })}
                      </p>
                    </>
                  ) : submitError && recorder.recording ? (
                    <>
                      <button
                        type="button"
                        onClick={retrySubmit}
                        disabled={submitting}
                        aria-label={t({
                          zh: "重传录音",
                          en: "Retry uploading recording",
                        })}
                        className="mt-1 grid size-[72px] place-items-center rounded-full bg-primary text-white shadow-[0_0_0_7px_var(--secondary)] transition hover:scale-105 disabled:opacity-50"
                      >
                        <ArrowRight className="size-7" />
                      </button>
                      <p className="mt-4 text-sm text-destructive">
                        {t({
                          zh: "上传失败，录音已保留",
                          en: "Upload failed — your recording is saved",
                        })}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {t({
                          zh: "点这里重传 · 或",
                          en: "Tap to retry · or",
                        })}
                        <button
                          type="button"
                          onClick={startRecording}
                          className="ml-1 underline text-primary"
                        >
                          {t({ zh: "重新录", en: "record again" })}
                        </button>
                      </p>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={startRecording}
                        disabled={
                          scoring ||
                          (examActive && currentItemDone) ||
                          examEnded ||
                          !prepDone
                        }
                        aria-label={t({
                          zh: "开始录音",
                          en: "Start recording",
                        })}
                        className="mt-1 grid size-[72px] place-items-center rounded-full bg-primary text-white shadow-[0_0_0_7px_var(--secondary)] transition hover:scale-105 disabled:opacity-50"
                      >
                        <Mic className="size-7" />
                      </button>
                      <p className="mt-4 text-sm">
                        {examEnded
                          ? t({ zh: "考试已结束", en: "The exam has ended" })
                          : examActive && currentItemDone
                            ? t({
                                zh: "本题已作答，考试中不能重录",
                                en: "Already answered — one attempt per item",
                              })
                            : scoring
                              ? t({
                                  zh: "已提交，正在出反馈…",
                                  en: "Submitted — feedback is on its way…",
                                })
                              : recorder.status === "ready"
                                ? t({
                                    zh: "这一次开口，已记录",
                                    en: "This speaking attempt is recorded",
                                  })
                                : !prepDone
                                  ? t({
                                      zh: "先利用准备时间组织思路",
                                      en: "Use the prep time to organise your ideas",
                                    })
                                  : t({
                                      zh: "准备好了，就点一下麦克风",
                                      en: "When you're ready, tap the microphone",
                                    })}
                      </p>
                      {scoring ? (
                        <p className="text-xs text-muted-foreground">
                          {isLastQuestion
                            ? t({
                                zh: "先显示本题分数和转写",
                                en: "Showing this item's score and transcript first",
                              })
                            : t({
                                zh: "先显示本题分数和转写，详细评价最后看",
                                en: "Score and transcript first — full feedback at the end",
                              })}
                        </p>
                      ) : attemptFailed ? (
                        <p className="text-xs text-destructive">
                          {t({
                            zh: "这次没有评出来，再录一次就好",
                            en: "No score this time — just record again",
                          })}
                        </p>
                      ) : (
                        <p className="text-xs text-muted-foreground">
                          {t({
                            zh: "需要麦克风权限 · 每一次练习都有意义",
                            en: "Microphone permission needed · Every practice counts",
                          })}
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
                  <Sparkles className="size-4 text-primary" />{" "}
                  {t({ zh: "一个小小的提示", en: "A little tip" })}
                </p>
                {isQuestion ? (
                  <>
                    <p className="text-sm text-muted-foreground">
                      {t({
                        zh: "不用寻找「标准答案」。试试这个顺序，让你的表达更完整。",
                        en: 'There\'s no "right answer" to find. Try this order to make your answer more complete.',
                      })}
                    </p>
                    <p className="font-serif text-xl">I think… because…</p>
                    <p className="text-xs text-muted-foreground">
                      {t({
                        zh: "我的观点 → 一个理由 → 一个小例子",
                        en: "My opinion → one reason → one small example",
                      })}
                    </p>
                  </>
                ) : (
                  <>
                    <p className="text-sm text-muted-foreground">
                      {t({
                        zh: "先听完整句子，再跟着意群停顿。比起说得快，说得自然更重要。",
                        en: "Listen to the whole sentence first, then pause with its chunks. Sounding natural beats speaking fast.",
                      })}
                    </p>
                    <p className="font-serif text-xl">Listen. Pause. Speak.</p>
                    <p className="text-xs text-muted-foreground">
                      {t({
                        zh: "听一遍 · 想一想 · 大胆说",
                        en: "Listen once · think · speak boldly",
                      })}
                    </p>
                  </>
                )}
              </CardContent>
            </Card>

            <Card className="hidden lg:block">
              <CardContent className="py-4">
                <p className="mb-3 text-sm font-semibold">
                  {t({ zh: "今天的路线", en: "Today's route" })}
                </p>
                {[
                  {
                    icon: Headphones,
                    title: t(TERMS.typeRepeat),
                    sub: t({ zh: "3 个短句", en: "3 sentences" }),
                    active: !isQuestion,
                  },
                  {
                    icon: MessageCircle,
                    title: t(TERMS.typeQa),
                    sub: t({ zh: "2 个问题", en: "2 questions" }),
                    active: isQuestion,
                  },
                  {
                    icon: ChartLine,
                    title: t({ zh: "看看收获", en: "See your gains" }),
                    sub: t({
                      zh: "全部完成后一起看",
                      en: "View together after finishing",
                    }),
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
                {t({
                  zh: "每次录音只有你自己和本课授权老师能回听。说错了没关系，再录一次就好。",
                  en: "Only you and your classroom's authorized teacher can play back your recordings. Mistakes are fine — just record again.",
                })}
              </CardContent>
            </Card>
          </aside>
        </div>

        {/* 反馈必须绑定实际作答的题型与题目：录音期间老师发布新计划后，
            旧反馈不会挂到新题（attempt 自带 item_type / item_id）。 */}
        {attempt && attemptTerminal && !exam && (
          <FeedbackCard
            attempt={attempt}
            itemType={attempt.item_type as "passage" | "repeat" | "question"}
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
                    // 下一题：解除本轮会话/题目钉住，回到最新活动计划。
                    // 已全部完成时保留会话钉住，让自动跳结果页仍绑定本轮会话。
                    if (!allDone) setPinnedSessionId(null)
                    setPinnedItemId(null)
                    setFocusItemId(null)
                    recordingTargetRef.current = null
                    recorderReset()
                    resetAttempt()
                  }}
                >
                  {allDone
                    ? t({
                        zh: "查看详细总反馈",
                        en: "View detailed feedback",
                      })
                    : t({ zh: "下一题", en: "Next item" })}
                  <ArrowRight />
                </Button>
              )
            }
          />
        )}
        <p className="text-center text-sm text-muted-foreground">
          {t({
            zh: "每题先看分数和转写，完成后查看全面评价与改进建议。",
            en: "See each item's score and transcript first, then view full feedback and tips once you finish.",
          })}
        </p>

        {allDone && (
          <Button size="lg" asChild>
            <Link
              to="/p/$code/result"
              params={{ code }}
              search={sessionId ? { session: sessionId } : {}}
            >
              {t({ zh: "查看本轮结果", en: "View this round's results" })}
            </Link>
          </Button>
        )}

        <p className="pb-6 text-center text-xs text-muted-foreground">
          {t({
            zh: "分数是参考反馈，不是考试成绩。",
            en: "Scores are reference feedback, not exam results.",
          })}
        </p>
      </div>
    </StudentShell>
  )
}
