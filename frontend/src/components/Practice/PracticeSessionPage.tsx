import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  useBlocker,
  useNavigate,
  useParams,
  useSearch,
} from "@tanstack/react-router"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import type { PlanItem } from "@/client"
import { ClassesService } from "@/client"
import AttemptStatusBar from "@/components/Practice/AttemptStatusBar"
import DraftRecoveryCard from "@/components/Practice/DraftRecoveryCard"
import ExamBanner from "@/components/Practice/ExamBanner"
import ExamStartConfirm from "@/components/Practice/ExamStartConfirm"
import InstructionPanel from "@/components/Practice/InstructionPanel"
import PracticeFeedbackSection from "@/components/Practice/PracticeFeedbackSection"
import PracticeFooter from "@/components/Practice/PracticeFooter"
import PracticeHeader from "@/components/Practice/PracticeHeader"
import PracticeItemCard from "@/components/Practice/PracticeItemCard"
import {
  PracticeLoadError,
  PracticeSkeleton,
} from "@/components/Practice/PracticeLoadState"
import PracticeNavigator from "@/components/Practice/PracticeNavigator"
import PracticeSidebar from "@/components/Practice/PracticeSidebar"
import RecordArea from "@/components/Practice/RecordArea"
import StepProgressBar from "@/components/Practice/StepProgressBar"
import StudentShell from "@/components/Practice/StudentShell"
import { Separator } from "@/components/ui/separator"
import { useAttemptSubmit } from "@/hooks/useAttemptSubmit"
import { useClassroomActivity } from "@/hooks/useClassroomActivity"
import { useExamClockValue } from "@/hooks/useExamClock"
import { useNextQuestion } from "@/hooks/useNextQuestion"
import { useRecordingFlow } from "@/hooks/useRecordingFlow"
import { useRuntimeIssue } from "@/hooks/useRuntimeIssue"
import { useStudentGuard } from "@/hooks/useStudentGuard"
import { loadStudent } from "@/lib/classroom-student"
import { useI18n } from "@/lib/i18n"
import { pollWhileVisible } from "@/lib/poll"
import { practiceItemCopy } from "@/lib/practice-copy"
import {
  blockerNotice,
  buildAttemptByItem,
  isAttemptTerminal,
  mergeItemsWithExtra,
  nextItemIdAfterCompletion,
  resolvePracticeIndex,
} from "@/lib/practice-derive"
import { resolveRecordLimitSeconds } from "@/lib/recording-limit"

export function PracticeSessionPage({ mode }: { mode: "practice" | "exam" }) {
  const { t } = useI18n()
  const { code } = useParams({ strict: false }) as { code: string }
  const {
    focus: focusParam,
    next: nextFlag,
    explore: exploreSessionId,
    session: sessionParam,
    homework,
  } = useSearch({ strict: false })
  const navigate = useNavigate()
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
  // 模考任何已接收的提交都锁定，包含 queued/failed（录音状态机读写）
  const acceptedExamItemsRef = useRef(new Set<string>())
  // 自动跳结果页的闩锁：每次挂载最多跳一次
  const navigatedRef = useRef(false)

  // 有效会话：优先钉住的会话（录音/回看期间保持同一轮），其次探索轮
  const sessionId = pinnedSessionId ?? exploreSessionId
  // 今日计划查询键：sessionId 为空时与 StudentShell 的 NotificationBell 同 key
  // （共享缓存，避免进练习页后铃铛+页面各拉一次同端点）；有会话时多一位区分数据。
  // invalidate 用同一变量，避免前缀匹配错位。
  // useMemo 稳定键身份：多个 effect 依赖它做 invalidate，若每次渲染都是新数组，
  // 会形成 invalidate → refetch → 渲染 → effect 重跑 的死循环（评分失败场景
  // toast 每圈重弹刷屏，即新 e2e 在 CI 暴露的问题）
  const todayQueryKey = useMemo(
    () =>
      [
        "classroom",
        code,
        "today",
        student?.id,
        ...(sessionId ? [sessionId] : []),
        ...(homework ? ["homework"] : []),
      ] as const,
    [code, student?.id, sessionId, homework],
  )

  const todayQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: todayQueryKey,
    queryFn: () =>
      ClassesService.readTodayPlan({
        code: code.toUpperCase(),
        ...(sessionId ? { sessionId } : {}),
        ...(homework && !sessionId ? { slot: "homework" } : {}),
      }),
    enabled: student !== null,
    refetchInterval: pollWhileVisible((query) =>
      query.state.data?.attempts.some((a) => !isAttemptTerminal(a.status))
        ? 2000
        : 30000,
    ), // 慢速同步：老师中途指派新单元时学生端最迟 30 秒感知
  })

  // 身份守卫：无本地身份跳加入页；查询报"学生不存在"清身份重进（5 页共用 hook）
  useStudentGuard(code, student, todayQuery)

  // 模考开考：确认页「开始考试」显式触发计时（后端幂等，重复点击不重置）
  const startExamMutation = useMutation({
    mutationFn: async () => {
      const sid = todayQuery.data?.session_id
      if (sid !== undefined) {
        await ClassesService.startExam({
          code: code.toUpperCase(),
          requestBody: { session_id: sid },
        })
      }
    },
    onSuccess: () => {
      setPinnedSessionId(todayQuery.data?.session_id ?? null)
      void queryClient.invalidateQueries({ queryKey: todayQueryKey })
    },
    onError: () => {
      toast.error(
        t({
          zh: "开始考试失败，请重试",
          en: "Could not start the exam — please try again",
        }),
      )
    },
  })

  const plan = todayQuery.data
  const boundSessionId = sessionId ?? (homework ? plan?.session_id : undefined)
  const exam = plan?.exam ?? null
  const examStarted = exam?.started ?? false
  const examActive = exam !== null && !exam.ended
  const examEnded = exam?.ended ?? false
  // 考试时钟渲染隔离：页面层只订阅「到点」布尔跳变（稳态零重渲染），
  // 秒级倒计时数字由 ExamCountdowns 里的 memo 叶子组件自行订阅展示。
  const syncedAt = todayQuery.dataUpdatedAt
  const itemExpired = useExamClockValue(
    exam,
    syncedAt,
    (clock) => exam !== null && clock.itemRemaining === 0,
  )
  const examPrepDone = useExamClockValue(
    exam,
    syncedAt,
    (clock) => exam === null || clock.prepRemaining === 0,
  )
  const examExpired = useExamClockValue(
    exam,
    syncedAt,
    (clock) => exam !== null && clock.remaining === 0,
  )

  // 追加换来的题（本地状态；完成后随 attempts 展示）
  const [extraQuestion, setExtraQuestion] = useState<PlanItem | null>(null)
  const items = useMemo(
    () => (plan ? mergeItemsWithExtra(plan.items, extraQuestion) : []),
    [plan, extraQuestion],
  )

  // 换一题（US-06）：同主题同档未做过；探索轮绑定 session_id
  const { nextQuestionMutation } = useNextQuestion({
    code,
    sessionId: boundSessionId,
    items,
    todayQueryKey,
    nextFlag: nextFlag === true,
    studentReady: student !== null,
    planLoaded: todayQuery.isSuccess,
    planError: todayQuery.isError,
    hasExam: Boolean(todayQuery.data?.exam),
    onExtraQuestion: setExtraQuestion,
  })

  const attemptByItem = useMemo(
    () => buildAttemptByItem(plan?.attempts ?? []),
    [plan],
  )

  // 题目说明「已读」：服务端 acked_at + 本地乐观 ack 集合（点「继续」立即生效）
  const [ackedIds, setAckedIds] = useState<ReadonlySet<string>>(new Set())
  const isItemDone = useCallback(
    (item: PlanItem) =>
      item.type === "instruction"
        ? ackedIds.has(item.id) || item.acked_at != null
        : isAttemptTerminal(attemptByItem.get(item.id)?.status),
    [ackedIds, attemptByItem],
  )

  // 当前题定位（优先级：钉住题 > 模考题序 > 手动聚焦 > 第一道未完成）
  const currentIndex = useMemo(
    () =>
      resolvePracticeIndex({
        items,
        focusItemId,
        pinnedItemId,
        examIndex: exam ? (exam.current_item_index ?? 0) : null,
        isItemDone,
      }),
    [items, focusItemId, pinnedItemId, exam, isItemDone],
  )

  const currentItem = items[currentIndex]
  const recordLimitSeconds = resolveRecordLimitSeconds(
    currentItem?.suggested_seconds,
  )

  // ── 模考态 ──
  // 模考任何已接收的提交都锁定，包含 queued/failed。
  const currentItemDone = currentItem
    ? currentItem.type === "instruction"
      ? ackedIds.has(currentItem.id) || currentItem.acked_at != null
      : exam
        ? attemptByItem.has(currentItem.id) ||
          acceptedExamItemsRef.current.has(
            `${plan?.session_id}:${currentItem.id}`,
          )
        : isAttemptTerminal(attemptByItem.get(currentItem.id)?.status)
    : false

  // 分级题型训练：exam_kind（考试式题型）× exam_level（五级）两维分别建模；
  // 可空 = 普通课堂内容，展示与流程不变。hook 必须在条件 return 之前。
  const examKind = currentItem?.exam_kind ?? null
  const examLevel = currentItem?.exam_level ?? null
  const isIeltsPart2 = examKind === "ielts_p2"
  const cueBullets = currentItem?.cue_card_bullets ?? []
  const prepSeconds = isIeltsPart2 ? (currentItem?.prep_seconds ?? 60) : 0
  const [practicePrepLeft, setPrepLeft] = useState(0)
  const [practicePrepDone, setPrepDone] = useState(true)
  // 模考：准备是否结束来自考试时钟（布尔跳变才重渲染）；练习：本地秒表
  const prepDone = exam ? examPrepDone : practicePrepDone
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
    if (exam || practicePrepDone) return
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
  }, [practicePrepDone, exam])
  const skipPrep = () => {
    setPrepDone(true)
    setPrepLeft(0)
  }
  const {
    submitAsync,
    submitting,
    attempt,
    submitError,
    submitErrorData,
    rubricPending: attemptRubricPending,
    pollError: attemptPollError,
    refetchAttempt,
    reset: resetAttempt,
  } = useAttemptSubmit({
    itemType:
      (currentItem?.type as "passage" | "repeat" | "question") ?? "repeat",
    itemId: currentItem?.id ?? "",
    sessionId: plan?.session_id,
  })

  const allDone =
    items.length > 0 &&
    items.every(
      (item) =>
        (item.id === attempt?.item_id && isAttemptTerminal(attempt?.status)) ||
        isItemDone(item),
    )

  // 录音状态机：开始/结束/上传/重传 + 到点自动停录音（详见 hook 注释）
  const {
    recorder,
    recordingTargetRef,
    submittedRef,
    startRecording,
    retrySubmit,
    pendingBlockerActive,
    submissionClosed,
    leaveState,
  } = useRecordingFlow({
    code,
    exam,
    examStarted,
    examActive,
    examEnded,
    itemExpired,
    prepDone,
    currentItemDone,
    currentItem,
    sessionId: plan?.session_id,
    syncedAt,
    recordLimitSeconds,
    acceptedExamItemsRef,
    submitAsync,
    submitting,
    submitError,
    submitErrorData,
    resetAttempt,
    setPinnedSessionId,
    setPinnedItemId,
    setFocusItemId,
  })
  useClassroomActivity(
    code,
    recorder.status === "recording"
      ? "recording"
      : submitting
        ? "uploading"
        : "idle",
    plan?.session_id,
  )
  useRuntimeIssue(
    code,
    plan?.session_id,
    recorder.deviceFault ? "device" : submitError ? "upload" : null,
  )

  // 录音/上传/失败待重传期间的离开保护（站内跳转 + 浏览器关闭/刷新）
  const blockerToastRef = useRef(false)
  useBlocker({
    shouldBlockFn: ({ current, next }) => {
      if (
        exam &&
        (next.pathname === `/exam/${code}/result` ||
          next.pathname === `/p/${code}/result`)
      )
        return false
      if (!pendingBlockerActive) return false
      // 同一路径跳转沿用原行为；撤销后切换会话仍须保护未保存录音。
      if (current.pathname === next.pathname && !submissionClosed) return false
      if (leaveState === "confirm") {
        return !window.confirm(
          t({
            zh: "补练已撤销，这段录音未上传，也未能保存到本设备。离开将丢失这段录音，确定离开吗？",
            en: "This task was withdrawn. This recording was neither uploaded nor saved on this device. Leaving will lose it. Leave anyway?",
          }),
        )
      }
      if (!blockerToastRef.current) {
        blockerToastRef.current = true
        toast.warning(
          submissionClosed
            ? t({
                zh: "正在保存录音草稿，请稍候再离开。",
                en: "Saving your recording draft. Please wait before leaving.",
              })
            : t(blockerNotice(recorder.status, submitting, Boolean(exam))),
        )
        window.setTimeout(() => {
          blockerToastRef.current = false
        }, 2000)
      }
      return true
    },
    enableBeforeUnload: () => pendingBlockerActive,
  })

  // 普通练习等待单题反馈；模考只等待录音上传。
  const attemptStatus = attempt?.status
  const attemptTerminal = isAttemptTerminal(attemptStatus)
  const attemptFailed = attemptStatus === "failed"

  // 题目说明「继续」：普通练习乐观推进（ack 失败不阻塞，下次 today 校准）；
  // 模考必须等 ack 落库——服务端题窗靠它推进，提前刷新会被锁在说明页
  const ackPendingRef = useRef(false)
  const ackMutation = useMutation({
    mutationFn: (itemId: string) =>
      ClassesService.recordInstructionAck({
        code: code.toUpperCase(),
        requestBody: {
          session_id: plan?.session_id ?? "",
          item_id: itemId,
        },
      }),
  })
  const continueFromInstruction = async () => {
    if (!currentItem || ackPendingRef.current) return
    ackPendingRef.current = true
    const itemId = currentItem.id
    try {
      if (exam) {
        try {
          await ackMutation.mutateAsync(itemId)
        } catch {
          toast.error(
            t({
              zh: "确认失败，请稍候再点「继续」",
              en: "Couldn't confirm — tap Continue again in a moment",
            }),
          )
          return
        }
        setAckedIds((prev) => new Set(prev).add(itemId))
        await queryClient.invalidateQueries({ queryKey: todayQueryKey })
        return
      }
      setAckedIds((prev) => new Set(prev).add(itemId))
      ackMutation.mutate(itemId, {
        onError: () =>
          toast.error(
            t({
              zh: "「继续」确认未记录成功，练习进度不受影响",
              en: "Recording the Continue tap failed — your progress is unaffected",
            }),
          ),
      })
      const nextItemId = nextItemIdAfterCompletion(
        items,
        currentIndex,
        (item) => isItemDone(item) || item.id === itemId,
      )
      if (nextItemId) {
        setFocusItemId(nextItemId)
      } else {
        navigatedRef.current = true
        void navigate({
          to: exam ? "/exam/$code/result" : "/p/$code/result",
          params: { code },
          search: boundSessionId ? { session: boundSessionId } : {},
        })
      }
    } finally {
      ackPendingRef.current = false
    }
  }

  // 倒计时归零：拉取服务端终态（惰性交卷在那边落库）。
  // 归零期间保持每秒拉取直到服务端判卷结束，与旧实现节奏一致
  useEffect(() => {
    if (!examExpired || !examActive) return
    void queryClient.invalidateQueries({ queryKey: todayQueryKey })
    const timer = window.setInterval(() => {
      void queryClient.invalidateQueries({ queryKey: todayQueryKey })
    }, 1000)
    return () => window.clearInterval(timer)
  }, [examExpired, examActive, queryClient, todayQueryKey])
  // 考试结束（到时/服务端判定）：自动进结果页（= 交卷）
  useEffect(() => {
    if (!examEnded) return
    if (recorder.status === "recording") {
      recorder.stop()
      return
    }
    if (submitting) return
    void navigate({
      to: exam ? "/exam/$code/result" : "/p/$code/result",
      params: { code },
      search: plan?.session_id ? { session: plan.session_id } : {},
    })
  }, [
    examEnded,
    navigate,
    code,
    plan?.session_id,
    recorder.status,
    recorder.stop,
    submitting,
    exam,
  ])

  // 防切屏：开考后离开页面（切 tab/最小化）计数并提示；切回时补报离屏时长
  const hiddenAtRef = useRef<number | null>(null)
  useEffect(() => {
    if (!examActive || !examStarted || !plan?.session_id) return
    const sessionId = plan.session_id
    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        hiddenAtRef.current = Date.now()
        void ClassesService.reportExamViolation({
          code: code.toUpperCase(),
          requestBody: { session_id: sessionId },
        }).catch(() => {
          /* 上报失败不打断考试 */
        })
        toast.warning(
          t({
            zh: "考试中请勿切屏",
            en: "Stay on this screen during the exam",
          }),
          {
            description: t({
              zh: "本次切屏已被记录，老师可见",
              en: "This switch has been recorded and is visible to your teacher",
            }),
          },
        )
        return
      }
      // visible 相位：带上本次离屏秒数（服务端封顶 1 小时/次）
      const hiddenAt = hiddenAtRef.current
      hiddenAtRef.current = null
      const awaySeconds =
        hiddenAt === null ? 0 : Math.round((Date.now() - hiddenAt) / 1000)
      if (awaySeconds <= 0) return
      void ClassesService.reportExamViolation({
        code: code.toUpperCase(),
        requestBody: { session_id: sessionId, away_seconds: awaySeconds },
      }).catch(() => {
        /* 时长补报失败仅损失该次时长，次数已记 */
      })
    }
    document.addEventListener("visibilitychange", onVisibility)
    return () => document.removeEventListener("visibilitychange", onVisibility)
  }, [examActive, examStarted, plan?.session_id, code, t])
  const scoring =
    submitting || (!exam && attemptStatus !== undefined && !attemptTerminal)

  // 评分完成：同步今日计划（进度、升降档后的问答）；保留单题简短反馈，学生点击后继续。
  // 文案经 ref 解耦：t 进依赖数组会在切语言时重播 toast 并多做一次 invalidate
  const attemptFailedToast = () => {
    toast.error(t({ zh: "这次没有评出来", en: "No score this time" }), {
      description: t({
        zh: "可以再录一次",
        en: "You can record again",
      }),
    })
  }
  const attemptFailedToastRef = useRef(attemptFailedToast)
  attemptFailedToastRef.current = attemptFailedToast
  useEffect(() => {
    if (!attemptTerminal) return
    void queryClient.invalidateQueries({ queryKey: todayQueryKey })
    if (attemptFailed && !exam) {
      attemptFailedToastRef.current()
      return
    }
  }, [attemptTerminal, attemptFailed, queryClient, todayQueryKey, exam])

  // 考试全部完成后进入结果页；练习保留题面，允许继续选题和重练。
  useEffect(() => {
    if (!exam || !allDone || !submittedRef.current || navigatedRef.current)
      return
    if (attemptStatus !== undefined) return
    if (attemptFailed) return
    navigatedRef.current = true
    void navigate({
      to: exam ? "/exam/$code/result" : "/p/$code/result",
      params: { code },
      // 结果页绑定实际完成会话（钉住的会话），老师发布新计划也不串轮
      search: sessionId ? { session: sessionId } : {},
    })
  }, [
    allDone,
    attemptStatus,
    attemptFailed,
    navigate,
    code,
    sessionId,
    submittedRef.current,
    exam,
  ])

  useEffect(() => {
    if (mode === "practice" && plan?.exam) {
      void navigate({
        to: "/exam/$code",
        params: { code },
        search: { session: plan.session_id },
        replace: true,
      })
    }
  }, [mode, plan, navigate, code])

  if (student === null) return null

  if (todayQuery.isPending) {
    return (
      <StudentShell active={mode}>
        <PracticeSkeleton />
      </StudentShell>
    )
  }
  if (todayQuery.isError || !plan) {
    return (
      <PracticeLoadError
        error={todayQuery.error}
        onRetry={() => todayQuery.refetch()}
      />
    )
  }

  if (mode === "exam" && !exam) {
    return (
      <StudentShell active="exam">
        <p className="rounded-xl border p-6">
          {t({
            zh: "当前没有考试。练习请前往「今日练习」，历史考试反馈可在「我的成长」查看。",
            en: "No exam is currently assigned. Open Today's Practice for practice, or My Growth for past exam feedback.",
          })}
        </p>
      </StudentShell>
    )
  }
  if (mode === "practice" && exam) return null

  if (!currentItem) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        {t({ zh: "今天没有练习内容。", en: "No practice content today." })}
      </div>
    )
  }

  // 模考开考确认页：计时以显式确认为准（服务端落时间），防止误触打开即烧时间。
  // 只渲染确认卡，题目/录音在开考前一律不可触达。
  if (exam !== null && !examStarted) {
    return (
      <StudentShell active={mode}>
        <ExamStartConfirm
          exam={exam}
          startPending={startExamMutation.isPending}
          onStart={() => startExamMutation.mutate()}
        />
      </StudentShell>
    )
  }

  const isQuestion = currentItem.type === "question"
  // 其余题都已完成 → 当前是最后一题（评分完成后直接进结果页）
  const isLastQuestion = items.every(
    (item) => item.id === currentItem.id || isItemDone(item),
  )

  // 题面文案（角标/提示）与题型判定收敛在纯函数层（lib/practice-copy，可单测）
  const { isPassage, isInstruction, promptLabel, hint } = practiceItemCopy(
    {
      type: currentItem.type,
      examKind,
      sentenceIndex: currentItem.sentence_index,
      sentenceTotal: currentItem.sentence_total,
    },
    t,
  )

  return (
    <StudentShell active={mode}>
      <div className="flex flex-col gap-6">
        {/* 顶部：标题 HUD + 结果页入口（展示组件） */}
        <PracticeHeader
          currentIndex={
            items
              .slice(0, currentIndex)
              .filter((item) => item.type !== "instruction").length
          }
          isInstruction={isInstruction}
          total={items.filter((item) => item.type !== "instruction").length}
          unitTitle={plan.assigned_unit_title}
          classroomCode={plan.classroom_code}
          student={student}
          streakDays={plan.gamification?.streak_days}
          xp={plan.gamification?.xp}
          resultsTo={exam ? "/exam/$code/result" : "/p/$code/result"}
          resultsSearch={
            boundSessionId ? { session: boundSessionId } : undefined
          }
        />

        {exam && (
          <ExamBanner
            exam={exam}
            examEnded={examEnded}
            examActive={examActive}
            syncedAt={syncedAt}
          />
        )}

        <StepProgressBar
          items={items}
          currentIndex={currentIndex}
          isItemDone={isItemDone}
        />

        {/* 批次08B：刷新/断网前未上传的录音草稿——用户明确选择才上传/丢弃 */}
        <DraftRecoveryCard
          code={code}
          items={items}
          submitAsync={submitAsync}
        />

        <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_270px]">
          <div className="grid gap-5">
            {/* 练习主卡：题面展示（展示组件）；作答区接线留在本页经 footer 注入 */}
            <PracticeNavigator
              items={exam ? [currentItem] : items}
              index={exam ? 0 : currentIndex}
              disabled={pendingBlockerActive || submissionClosed}
              onSelect={(id) => {
                if (
                  exam ||
                  submissionClosed ||
                  pendingBlockerActive ||
                  recorder.isStarting() ||
                  id === currentItem.id
                )
                  return
                submittedRef.current = false
                setPinnedItemId(null)
                setPinnedSessionId(plan?.session_id ?? null)
                setFocusItemId(id)
                setHideText(false)
                recordingTargetRef.current = null
                recorder.reset()
                resetAttempt()
              }}
              hidden={Boolean(exam)}
            >
              <PracticeItemCard
                item={currentItem}
                promptLabel={promptLabel}
                hint={hint}
                isPassage={isPassage}
                isInstruction={isInstruction}
                isQuestion={isQuestion}
                hideText={hideText}
                onToggleHideText={() => setHideText(!hideText)}
                exam={exam}
                syncedAt={syncedAt}
                examKind={examKind}
                examLevel={examLevel}
                cueBullets={cueBullets}
                isIeltsPart2={isIeltsPart2}
                prepDone={prepDone}
                practicePrepLeft={practicePrepLeft}
                onSkipPrep={skipPrep}
                code={code}
                sessionId={plan?.session_id}
                todayQueryKey={todayQueryKey}
                recordLimitSeconds={recordLimitSeconds}
                onNextQuestion={() => nextQuestionMutation.mutate()}
                nextQuestionPending={nextQuestionMutation.isPending}
                footer={
                  isInstruction ? (
                    <InstructionPanel
                      suggestedSeconds={currentItem.suggested_seconds}
                      itemDone={currentItemDone}
                      ackPending={ackMutation.isPending}
                      onContinue={() => void continueFromInstruction()}
                      exam={exam}
                      syncedAt={syncedAt}
                      hint={hint}
                    />
                  ) : (
                    <>
                      <Separator />
                      <RecordArea
                        recorder={recorder}
                        recordLimitSeconds={recordLimitSeconds}
                        examKind={examKind}
                        inExam={Boolean(exam)}
                        examActive={examActive}
                        examEnded={examEnded}
                        itemExpired={itemExpired}
                        currentItemDone={currentItemDone}
                        prepDone={prepDone}
                        scoring={scoring}
                        attemptFailed={attemptFailed}
                        isLastQuestion={isLastQuestion}
                        submitting={submitting}
                        submitError={submitError}
                        submissionClosed={submissionClosed}
                        closedLeaveState={leaveState}
                        onClosedLeave={() => {
                          void navigate({ to: "/home/$code", params: { code } })
                        }}
                        onStart={startRecording}
                        onStop={recorder.stop}
                        onRetry={retrySubmit}
                        onExpiredContinue={() => {
                          recorder.reset()
                          resetAttempt()
                          setPinnedItemId(null)
                          void queryClient.invalidateQueries({
                            queryKey: ["classroom", code, "today"],
                          })
                        }}
                      />
                    </>
                  )
                }
              />
            </PracticeNavigator>
          </div>

          {!exam && (
            <PracticeSidebar isQuestion={isQuestion} allDone={allDone} />
          )}
        </div>

        {/* 08A 状态接线（展示组件）：评定中指示 + 403/404 停轮后的只读重试 */}
        {!exam && (
          <AttemptStatusBar
            rubricPending={attemptRubricPending}
            pollErrorStatus={
              attemptPollError.present
                ? (attemptPollError.status ?? null)
                : null
            }
            onRefetch={refetchAttempt}
          />
        )}
        {/* 反馈必须绑定实际作答的题型与题目：录音期间老师发布新计划后，
            旧反馈不会挂到新题（attempt 自带 item_type / item_id）。 */}
        {attempt && attemptTerminal && !exam && (
          <PracticeFeedbackSection
            attempt={attempt}
            attemptFailed={attemptFailed}
            allDone={allDone}
            items={items}
            attemptByItem={attemptByItem}
            currentIndex={currentIndex}
            onRepractice={() => {
              // 主动重录：清提交标记，避免重置后 allDone 触发自动跳转结果页
              submittedRef.current = false
              resetAttempt()
              recorder.reset()
            }}
            onNextItem={(nextItemId) => {
              if (nextItemId) {
                setFocusItemId(nextItemId)
              } else {
                navigatedRef.current = true
                void navigate({
                  to: exam ? "/exam/$code/result" : "/p/$code/result",
                  params: { code },
                  search: boundSessionId ? { session: boundSessionId } : {},
                })
              }
              setPinnedItemId(null)
              recordingTargetRef.current = null
              recorder.reset()
              resetAttempt()
            }}
          />
        )}
        <PracticeFooter
          allDone={allDone}
          resultsTo={exam ? "/exam/$code/result" : "/p/$code/result"}
          resultsParams={{ code }}
          resultsSearch={
            boundSessionId ? { session: boundSessionId } : undefined
          }
        />
      </div>
    </StudentShell>
  )
}
