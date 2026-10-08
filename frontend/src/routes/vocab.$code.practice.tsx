import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  useNavigate,
  useParams,
} from "@tanstack/react-router"
import { ArrowLeft, Headphones, SpellCheck, Volume2 } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import type { VocabularyTodayItem } from "@/client"
import { ApiError, VocabularyService } from "@/client"
import StudentShell from "@/components/Practice/StudentShell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  PracticeFeedbackCard,
  QuizSubmittedCard,
} from "@/components/Vocabulary/Practice/AnswerFeedback"
import AnswerForm from "@/components/Vocabulary/Practice/AnswerForm"
import type { AnswerState } from "@/components/Vocabulary/Practice/answer-state"
import FinishBanner from "@/components/Vocabulary/Practice/FinishBanner"
import ProgressDots from "@/components/Vocabulary/Practice/ProgressDots"
import QuizRulesCard from "@/components/Vocabulary/Practice/QuizRulesCard"
import RoundSwitcher from "@/components/Vocabulary/Practice/RoundSwitcher"
import { SubmitQuizButton } from "@/components/Vocabulary/Practice/SubmitQuizButton"
import {
  SessionInsightDialog,
  WordExplanationDialog,
} from "@/components/Vocabulary/VocabAi"
import { APP_NAME } from "@/config"
import {
  playAudio as playCachedAudio,
  preloadAudio,
  stopAudio,
} from "@/lib/audio"
import { loadStudent } from "@/lib/classroom-student"
import { useI18n } from "@/lib/i18n"
import { EXPLAIN_QUIZ_PUBLISH, TERMS } from "@/lib/terms"
import { speakEnglish } from "@/lib/tts"

export const Route = createFileRoute("/vocab/$code/practice")({
  component: VocabPracticePage,
  validateSearch: (
    search: Record<string, unknown>,
  ): { assignment?: string; round?: string } => {
    const assignment = search.assignment
    const round = search.round
    return {
      ...(typeof assignment === "string" && assignment !== ""
        ? { assignment }
        : {}),
      ...(typeof round === "string" && /^\d+$/.test(round) ? { round } : {}),
    }
  },
  head: () => ({
    meta: [{ title: `拼写练习 / Spelling Practice - ${APP_NAME}` }],
  }),
})

/** 一题的最新作答反馈与测验提交占位（见 components/Vocabulary/Practice/answer-state） */

function VocabPracticePage() {
  const { t } = useI18n()
  const { code } = useParams({ from: "/vocab/$code/practice" })
  const { assignment: assignmentParam, round: roundParam } = Route.useSearch()
  const navigate = useNavigate({ from: "/vocab/$code/practice" })
  const queryClient = useQueryClient()
  const student = loadStudent(code)

  const todayQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: [
      "vocab",
      code,
      "today",
      student?.id,
      assignmentParam ?? "",
      roundParam ?? "",
    ],
    queryFn: () =>
      VocabularyService.readVocabToday({
        code: code.toUpperCase(),
        assignmentId: assignmentParam,
        roundNo: roundParam ? Number(roundParam) : undefined,
      }),
    enabled: student !== null,
  })

  const assignment = todayQuery.data?.assignment ?? null
  // 任务级作答门禁（截止/归档）；回看历史轮同样只读
  const closedReason = todayQuery.data?.session_closed_reason ?? null
  const viewingRoundNo = roundParam ? Number(roundParam) : null
  // 当前可练轮由后端独立下发（current_round）：展示轮号（session_round）
  // 是回看轮自己的轮号，不能拿来判断「我看的是不是当前轮」
  const currentRoundNo = todayQuery.data?.current_round ?? null
  const isCurrentRound =
    viewingRoundNo === null || viewingRoundNo === currentRoundNo
  const rounds = todayQuery.data?.rounds ?? []
  const activeRoundNo = viewingRoundNo ?? todayQuery.data?.session_round ?? null
  // 测验模式：规则先行（未开始不自动开轮）、服务端计时、每题一次、回执不泄露
  const quiz = todayQuery.data?.quiz ?? null
  const isQuiz = quiz !== null
  const quizFinished =
    isQuiz && (quiz.status === "submitted" || quiz.status === "timed_out")
  const readOnly = closedReason !== null || !isCurrentRound || quizFinished
  const items = useMemo(
    () =>
      [...(todayQuery.data?.items ?? [])].sort(
        (a, b) => a.item_index - b.item_index,
      ),
    [todayQuery.data],
  )

  // 进入练习即固定任务：聚焦任务加载后写入 URL（replace），
  // 之后作答/刷新/完成都不会再漂移到其他任务
  useEffect(() => {
    if (assignmentParam || !assignment || todayQuery.isFetching) return
    void navigate({
      to: "/vocab/$code/practice",
      params: { code },
      search: { assignment: assignment.id },
      replace: true,
    })
  }, [assignment, assignmentParam, code, navigate, todayQuery.isFetching])

  // 任务/轮次绑定键：任一变化即清空本地作答状态——禁止新题面沿用旧会话的
  // 会话号、题号、输入与反馈（跨任务/跨轮切换的唯一重置入口）。
  // 渲染期重置模式（React 官方推荐）：绑定键变化时在渲染中重置 state
  const bindingKey = `${assignment?.id ?? ""}:${todayQuery.data?.session_id ?? ""}:${activeRoundNo ?? ""}`
  const [answers, setAnswers] = useState<Record<number, AnswerState>>({})
  // 测验本地提交标记（乐观）：plan 换轮/换会话时清空
  const [quizLocalSubmitted, setQuizLocalSubmitted] = useState<
    Record<number, true>
  >({})
  const quizLocalRenderedRef = useRef<string | null>(null)
  const quizRenderedSession = quiz?.status ?? ""
  if (quizRenderedSession !== (quizLocalRenderedRef.current ?? "")) {
    quizLocalRenderedRef.current = quizRenderedSession
    setQuizLocalSubmitted({})
  }
  const [current, setCurrent] = useState(0)
  const [input, setInput] = useState("")
  const [renderedBinding, setRenderedBinding] = useState(bindingKey)
  if (renderedBinding !== bindingKey) {
    setRenderedBinding(bindingKey)
    setAnswers({})
    setCurrent(0)
    setInput("")
  }

  // 服务端恢复已答状态（刷新/换端进入：plan 里带回首答结果）
  useEffect(() => {
    if (!todayQuery.data) return
    const restored: Record<number, AnswerState> = {}
    for (const item of todayQuery.data.items ?? []) {
      if (item.answered && item.headword) {
        restored[item.item_index] = {
          isCorrect: item.is_correct === true,
          correctSpelling: item.headword,
          attemptNo: item.attempt_count ?? 1,
        }
      }
    }
    setAnswers(restored)
    const firstUnanswered = (todayQuery.data.items ?? []).findIndex(
      (item) => !item.answered,
    )
    setCurrent(firstUnanswered >= 0 ? firstUnanswered : 0)
  }, [todayQuery.data])

  // 会话号与任务强绑定：优先用 today 返回（key 已含任务 ID），
  // 自动开练的窗口期用 createdSession（记着它属于哪个任务），
  // 任务切换后旧任务的会话号永远不会被用来提交新任务的题目
  const [createdSession, setCreatedSession] = useState<{
    assignmentId: string
    sessionId: string
  } | null>(null)
  const remoteSessionId = todayQuery.data?.session_id ?? null
  const sessionId =
    remoteSessionId ??
    (createdSession && createdSession.assignmentId === (assignment?.id ?? "")
      ? createdSession.sessionId
      : null)
  const startSession = useMutation({
    mutationFn: (payload: { assignmentId: string; round?: string }) =>
      VocabularyService.startVocabSession({
        code: code.toUpperCase(),
        requestBody: {
          assignment_id: payload.assignmentId,
          ...(payload.round ? { round: payload.round } : {}),
        },
      }),
    onSuccess: (data, payload) => {
      setCreatedSession({
        assignmentId: payload.assignmentId,
        sessionId: (data as { session_id: string }).session_id,
      })
      // 练习「再练一轮」/ 测验「明确开始」后都要重拉 today：
      // 测验开始后 today 才带答卷与题面（未开始不下发题面）
      void queryClient.invalidateQueries({
        queryKey: ["vocab", code, "today"],
      })
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 403) {
        toast.error(
          t({
            zh: "你不在此任务的名单内，请联系老师补派。",
            en: "You are not on this task's roster — ask your teacher to assign it.",
          }),
        )
        void navigate({ to: "/vocab/$code", params: { code } })
        return
      }
      if (error instanceof ApiError && error.status === 422) {
        // 任务已结束/已过截止/没有可续做的轮次：明确提示而非静默
        toast.error(
          t({
            zh: "这个任务已结束或本轮已完成，不能开始作答。",
            en: "This task has ended or the round is already finished — can't start.",
          }),
        )
      }
    },
  })
  useEffect(() => {
    // 测验：规则页明确「开始测验」才创建答卷（本页不自动开轮）
    if (remoteSessionId || readOnly || isQuiz) return
    if (
      assignment &&
      !sessionId &&
      !startSession.isPending &&
      !startSession.isError
    ) {
      startSession.mutate({ assignmentId: assignment.id })
    }
  }, [assignment, readOnly, remoteSessionId, sessionId, startSession, isQuiz])

  // 测验倒计时：以服务器下发的剩余秒数为基准本地递减（只是展示；
  // 到时由服务端结算判定，改客户端时间无法影响交卷与判分）
  const [serverRemaining, setServerRemaining] = useState<number | null>(
    quiz?.remaining_seconds ?? null,
  )
  useEffect(() => {
    setServerRemaining(quiz?.remaining_seconds ?? null)
  }, [quiz?.remaining_seconds])
  useEffect(() => {
    if (!isQuiz || quiz?.status !== "in_progress") return
    const timer = window.setInterval(() => {
      setServerRemaining((prev) =>
        prev === null ? null : Math.max(0, prev - 1),
      )
    }, 1000)
    return () => window.clearInterval(timer)
  }, [isQuiz, quiz?.status])
  // 倒计时归零触发一次重拉（服务端结算收口；幂等）
  useEffect(() => {
    if (isQuiz && quiz?.status === "in_progress" && serverRemaining === 0) {
      void queryClient.invalidateQueries({
        queryKey: ["vocab", code, "today"],
      })
    }
  }, [isQuiz, quiz?.status, serverRemaining, queryClient, code])

  // 测验切屏上报：只计事件，不阻断作答（教师参考，不自动认定作弊）
  useEffect(() => {
    if (!isQuiz || quiz?.status !== "in_progress" || !sessionId) return
    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        void VocabularyService.reportQuizTabSwitch({
          sessionId: sessionId as string,
        }).catch(() => undefined)
      }
    }
    document.addEventListener("visibilitychange", onVisibility)
    return () => document.removeEventListener("visibilitychange", onVisibility)
  }, [isQuiz, quiz?.status, sessionId])

  const [explainOpen, setExplainOpen] = useState(false)
  const [insightOpen, setInsightOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  // 幂等键跟随「一次作答意图」：键与题号/题型/作答内容绑定——只有原样重试
  // （断网、5xx 等送达不确定的失败）才复用同键，服务端重放返回同一判分；
  // 学生改了输入、换了题或明确重练都视为新意图换新键，避免旧键提交新内容
  const pendingRef = useRef<{
    key: string
    itemIndex: number
    promptType: string
    answer: string
  } | null>(null)
  const submitAnswer = useMutation({
    mutationFn: (payload: {
      itemIndex: number
      promptType: string
      answer: string
      binding: string
    }) => {
      const pending = pendingRef.current
      const sameIntent =
        pending !== null &&
        pending.itemIndex === payload.itemIndex &&
        pending.promptType === payload.promptType &&
        pending.answer === payload.answer
      if (!sameIntent) {
        pendingRef.current = {
          key: crypto.randomUUID(),
          ...payload,
        }
      }
      return VocabularyService.submitVocabAnswer({
        sessionId: sessionId as string,
        requestBody: {
          item_index: payload.itemIndex,
          prompt_type: payload.promptType,
          answer: payload.answer,
          idempotency_key: pendingRef.current?.key,
        },
      })
    },
    onSuccess: (result, variables) => {
      // 迟到响应隔离：提交后已切换任务/轮次的响应只丢弃不落当前视图
      if (variables.binding !== bindingKey) return
      pendingRef.current = null
      const receipt = result as { item_index: number; received: boolean }
      const graded = result as {
        is_correct: boolean
        correct_spelling: string
        attempt_no: number
      }
      if ("received" in result) {
        // 测验回执：只确认接收，不提前返回答案与正误（公布前零泄露）
        setQuizLocalSubmitted((prev) => ({
          ...prev,
          [receipt.item_index]: true,
        }))
        return
      }
      setAnswers((prev) => ({
        ...prev,
        [variables.itemIndex]: {
          isCorrect: graded.is_correct,
          correctSpelling: graded.correct_spelling,
          attemptNo: graded.attempt_no,
        },
      }))
    },
    onError: (error, variables) => {
      if (variables.binding !== bindingKey) return
      if (error instanceof ApiError && error.status < 500) {
        // 4xx 业务拒绝（422 幂等冲突等）：作答已被服务端明确拒绝，清键换新意图
        pendingRef.current = null
        toast.error(
          error.status === 422
            ? t({
                zh: "这道题暂时不能这样作答，请刷新后重试。",
                en: "This item can't be answered this way — refresh and retry.",
              })
            : t({
                zh: "提交被拒绝，请重试。",
                en: "Submit was rejected — please retry.",
              }),
        )
      } else {
        // 网络错误 / 5xx：送达状态不确定，保留键——原样重试会重放同一判分
        toast.error(
          t({
            zh: "网络不稳定，请重试；已送达的作答不会重复计分。",
            en: "Network hiccup — please retry; a delivered answer won't be double-counted.",
          }),
        )
      }
    },
  })

  // 出题方式：任务允许的题型决定初始模式（纯听音任务默认听音）；
  // 听音在当前题可用 = 有标准音，或该词已作答（拼写已揭示，可设备朗读）
  const taskPromptTypes = assignment?.prompt_types ?? ["meaning"]
  const meaningInTask = taskPromptTypes.includes("meaning")
  const audioInTask = taskPromptTypes.includes("audio")
  const item: VocabularyTodayItem | undefined = items[current]
  const answer = item ? answers[item.item_index] : undefined
  const audioUsableHere =
    audioInTask &&
    (isQuiz
      ? Boolean(item?.audio_url) // 测验：浏览器合成语音不能作题源
      : Boolean(item?.audio_url || answer !== undefined))
  const [useAudio, setUseAudio] = useState(false)
  useEffect(() => {
    setUseAudio(audioInTask && !meaningInTask && audioUsableHere)
  }, [audioInTask, meaningInTask, audioUsableHere])

  const answeredCount = Object.keys(answers).length
  const correctFirst = items.filter(
    (it) => it.answered && it.is_correct === true,
  ).length
  // 测验口径：提交态来自 plan（刷新恢复）+ 本地乐观标记；不显示对错
  const quizAnsweredCount = items.filter(
    (it) => it.answered || quizLocalSubmitted[it.item_index],
  ).length
  const allDone =
    items.length > 0 &&
    (isQuiz ? quizAnsweredCount >= items.length : answeredCount >= items.length)
  const itemQuizSubmitted =
    isQuiz &&
    Boolean(item?.answered || quizLocalSubmitted[item?.item_index ?? -1])
  const quizItemSubmitted = itemQuizSubmitted

  // 听音预载与防串音：进题即预载本题标准音（顺带下一题），切题/卸载停掉在播音频
  const nextAudioUrl = items[current + 1]?.audio_url
  useEffect(() => {
    if (!item?.audio_url) return
    preloadAudio([item.audio_url, nextAudioUrl])
    return () => stopAudio(item.audio_url)
  }, [item?.audio_url, nextAudioUrl])

  const playAudio = () => {
    if (!item) return
    if (item.audio_url) {
      playCachedAudio(item.audio_url).catch(() => {
        toast.error(t({ zh: "音频播放失败", en: "Audio playback failed" }))
      })
      return
    }
    // 无标准音的词：仅已作答（拼写已揭示）时允许浏览器朗读兜底，界面标明设备合成语音
    const word = answer?.correctSpelling ?? item.headword ?? ""
    if (word) {
      const utterance = speakEnglish(word)
      if (utterance === null) {
        toast.error(
          t({
            zh: "当前设备不支持语音朗读",
            en: "This device doesn't support speech playback",
          }),
        )
      }
    }
  }

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault()
    if (
      !item ||
      !sessionId ||
      input.trim() === "" ||
      submitAnswer.isPending ||
      readOnly
    )
      return
    submitAnswer.mutate({
      itemIndex: item.item_index,
      promptType: useAudio ? "audio" : "meaning",
      answer: input.trim(),
      binding: bindingKey,
    })
  }

  const retry = () => {
    if (!item) return
    pendingRef.current = null // 重练是一次新作答意图
    setAnswers((prev) => {
      const next = { ...prev }
      delete next[item.item_index]
      return next
    })
    setInput("")
    inputRef.current?.focus()
  }

  const goNext = () => {
    setInput("")
    pendingRef.current = null
    if (current < items.length - 1) {
      setCurrent(current + 1)
      window.setTimeout(() => inputRef.current?.focus(), 50)
    } else {
      // 走完一轮：刷新任务与错词数据，让首页统计最新
      queryClient.invalidateQueries({ queryKey: ["vocab", code] })
    }
  }

  if (student === null) return null

  if (todayQuery.isPending) {
    return (
      <StudentShell active="vocab">
        <div role="status" className="space-y-6">
          <span className="sr-only">
            {t({ zh: "正在加载拼写练习…", en: "Loading spelling practice…" })}
          </span>
          <Skeleton className="h-64 rounded-2xl" />
        </div>
      </StudentShell>
    )
  }

  // 测验规则页：未明确开始不下发题面；这里给出规则与「开始测验」入口
  if (isQuiz && quiz?.status === "not_started" && assignment) {
    return (
      <StudentShell active="vocab">
        <div className="flex flex-col gap-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Button variant="ghost" size="sm" asChild>
              <Link to="/vocab/$code" params={{ code }}>
                <ArrowLeft />
                {t({ zh: "返回词汇学习", en: "Back to Vocabulary" })}
              </Link>
            </Button>
          </div>
          <QuizRulesCard
            quiz={quiz}
            assignmentTitle={assignment.title}
            startPending={startSession.isPending}
            onStart={() => startSession.mutate({ assignmentId: assignment.id })}
          />
        </div>
      </StudentShell>
    )
  }

  if (
    todayQuery.isError ||
    assignment === null ||
    items.length === 0 ||
    !item
  ) {
    return (
      <StudentShell active="vocab">
        <Card className="items-center px-6 py-12 text-center">
          <SpellCheck className="size-10 text-primary" />
          <h1 className="mt-3 text-xl font-semibold">
            {t({
              zh: "现在没有可练习的词汇任务",
              en: "No vocabulary task to practice right now",
            })}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t({
              zh: "老师发布任务后，这里就能开始拼写练习。",
              en: "Once your teacher publishes a task, spelling practice starts here.",
            })}
          </p>
          <Button asChild className="mt-4">
            <Link to="/vocab/$code" params={{ code }}>
              {t({ zh: "返回词汇学习", en: "Back to Vocabulary" })}
            </Link>
          </Button>
        </Card>
      </StudentShell>
    )
  }

  return (
    <StudentShell active="vocab">
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Button variant="ghost" size="sm" asChild>
            <Link to="/vocab/$code" params={{ code }}>
              <ArrowLeft />
              {t({ zh: "返回词汇学习", en: "Back to Vocabulary" })}
            </Link>
          </Button>
          <div className="flex flex-wrap items-center gap-3">
            {isQuiz && quiz?.status === "in_progress" && (
              <span
                role="timer"
                aria-label={t({ zh: "剩余时间", en: "Time remaining" })}
                className={`rounded-xl px-3 py-1.5 font-mono text-sm font-semibold tabular-nums ${
                  (serverRemaining ?? 0) <= 60
                    ? "bg-amber-500/15 text-amber-600"
                    : "bg-secondary text-primary"
                }`}
              >
                {t({ zh: "剩余", en: "Left" })}{" "}
                {String(Math.floor((serverRemaining ?? 0) / 60)).padStart(
                  2,
                  "0",
                )}
                :{String((serverRemaining ?? 0) % 60).padStart(2, "0")}
              </span>
            )}
            {isQuiz && quiz?.status === "in_progress" && (
              <SubmitQuizButton
                sessionId={sessionId}
                disabled={!sessionId}
                onDone={() => {
                  void queryClient.invalidateQueries({
                    queryKey: ["vocab", code, "today"],
                  })
                }}
              />
            )}
            <p className="text-xs text-muted-foreground">
              {t(
                isQuiz
                  ? {
                      zh: `${assignment?.title ?? ""} · 第 ${current + 1} / ${items.length} 题（每题一次，提交后不能修改）`,
                      en: `${assignment?.title ?? ""} · Item ${current + 1} / ${items.length} (one submission per item)`,
                    }
                  : {
                      zh: `${assignment?.title ?? ""} · 第 ${activeRoundNo ?? 1} 轮 · 第 ${current + 1} / ${items.length} 题 · 首答正确 ${correctFirst}`,
                      en: `${assignment?.title ?? ""} · Round ${activeRoundNo ?? 1} · Item ${current + 1} / ${items.length} · ${correctFirst} correct on first try`,
                    },
              )}
            </p>
          </div>
        </div>

        {/* 只读提示：截止/归档/回看历史轮 */}
        {readOnly && (
          <div
            role="status"
            className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm"
          >
            <p className="font-semibold">
              {!isCurrentRound
                ? t({
                    zh: "正在回看这一轮的记录（只读）；切回最新轮可继续练习。",
                    en: "Viewing this round's records (read-only); switch back to the latest round to keep practicing.",
                  })
                : quizFinished
                  ? t(EXPLAIN_QUIZ_PUBLISH)
                  : closedReason === "archived"
                    ? t({
                        zh: "老师已结束这个任务，不能再作答；下面的记录可以回看。",
                        en: "Your teacher ended this task — no more answering, but your records below stay viewable.",
                      })
                    : t({
                        zh: "这个任务已过截止时间，不能再作答；下面的记录可以回看。",
                        en: "This task is past its due time — no more answering, but your records below stay viewable.",
                      })}
            </p>
          </div>
        )}

        {/* 轮次切换：回看各轮记录；当前展示轮高亮 */}
        <RoundSwitcher
          code={code}
          assignmentId={assignmentParam ?? assignment?.id ?? ""}
          rounds={rounds}
          activeRoundNo={activeRoundNo}
          currentRoundNo={currentRoundNo}
        />

        {/* 进度点：点选跳题；对=主色、错=灰、当前=实心 */}
        <ProgressDots
          items={items}
          answers={answers}
          quizLocalSubmitted={quizLocalSubmitted}
          isQuiz={isQuiz}
          current={current}
          onSelect={(index) => {
            setCurrent(index)
            setInput("")
            pendingRef.current = null // 换题 = 新作答意图
          }}
        />

        <Card>
          <CardHeader className="space-y-1.5">
            <CardTitle className="text-base">
              {useAudio ? t(TERMS.promptAudio) : t(TERMS.promptMeaning)}
            </CardTitle>
            <CardDescription>
              {useAudio
                ? t({
                    zh: "听单词发音，拼出英文。听不清可以再点一次。",
                    en: "Listen and spell the word. Tap again to replay.",
                  })
                : t({
                    zh: "看中文释义，拼出对应的英文单词。",
                    en: "Read the Chinese meaning and spell the English word.",
                  })}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {/* 题面 */}
            {useAudio ? (
              <div className="flex flex-col items-center gap-3 rounded-2xl bg-secondary/50 py-8">
                <Button
                  type="button"
                  size="lg"
                  className="size-16 rounded-full"
                  aria-label={t({ zh: "播放单词发音", en: "Play the word" })}
                  onClick={playAudio}
                >
                  <Volume2 className="size-7" />
                </Button>
                <p className="text-xs text-muted-foreground">
                  {item.audio_url
                    ? t({ zh: "标准音", en: "Standard audio" })
                    : t({
                        zh: "设备合成语音（仅练习用）",
                        en: "Device voice (practice only)",
                      })}
                </p>
              </div>
            ) : (
              <div className="rounded-2xl bg-secondary/50 p-5 sm:p-6">
                {item.part_of_speech && (
                  <Badge variant="outline" className="mb-2">
                    {item.part_of_speech}
                  </Badge>
                )}
                <p className="text-xl font-semibold leading-snug sm:text-2xl">
                  {item.meaning_zh}
                </p>
                {item.meaning_en && (
                  <p className="mt-1.5 text-sm text-muted-foreground">
                    {item.meaning_en}
                  </p>
                )}
              </div>
            )}

            {/* 题型切换：任务同时允许看义/听音时学生可自选；
                无标准音且未作答的词禁用听音（设计文档：不进入听音题并说明原因） */}
            {audioInTask && (
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant={useAudio ? "default" : "outline"}
                  size="sm"
                  disabled={!audioUsableHere}
                  aria-disabled={!audioUsableHere}
                  onClick={() => setUseAudio(true)}
                >
                  <Headphones />
                  {t(TERMS.promptAudio)}
                </Button>
                {meaningInTask && (
                  <Button
                    type="button"
                    variant={!useAudio ? "default" : "outline"}
                    size="sm"
                    onClick={() => setUseAudio(false)}
                  >
                    <SpellCheck />
                    {t(TERMS.promptMeaning)}
                  </Button>
                )}
                {!audioUsableHere && (
                  <p className="text-xs text-muted-foreground">
                    {t({
                      zh: "这个词还没有标准音，先用看义拼词；答过后可用设备语音再听。",
                      en: "No standard audio for this word yet — spell from meaning first; after answering you can replay it with device voice.",
                    })}
                  </p>
                )}
              </div>
            )}

            {/* 作答区：练习=即时反馈；测验=只确认接收（不提前泄露答案） */}
            {!answer && !quizItemSubmitted ? (
              <AnswerForm
                input={input}
                onInputChange={setInput}
                onSubmit={handleSubmit}
                inputRef={inputRef}
                submitPending={submitAnswer.isPending}
                isQuiz={isQuiz}
                inputDisabled={!sessionId || startSession.isPending || readOnly}
                submitDisabled={
                  input.trim() === "" ||
                  submitAnswer.isPending ||
                  !sessionId ||
                  readOnly
                }
              />
            ) : isQuiz && quizItemSubmitted ? (
              <QuizSubmittedCard
                hasNext={current < items.length - 1}
                onNext={() => {
                  setInput("")
                  pendingRef.current = null
                  setCurrent(current + 1)
                }}
                onRefresh={() => {
                  setInput("")
                  pendingRef.current = null
                  void queryClient.invalidateQueries({
                    queryKey: ["vocab", code, "today"],
                  })
                }}
              />
            ) : answer ? (
              <PracticeFeedbackCard
                answer={answer}
                meaningZh={item.meaning_zh}
                typedInput={input.trim()}
                onRetry={retry}
                canExplain={Boolean(item.headword)}
                onExplain={() => setExplainOpen(true)}
                nextLabel={
                  current < items.length - 1
                    ? t({ zh: "下一个词", en: "Next word" })
                    : allDone || answeredCount >= items.length
                      ? t({ zh: "完成练习", en: "Finish" })
                      : t({ zh: "下一个词", en: "Next word" })
                }
                onNext={goNext}
              />
            ) : null}

            {/* 走完全部题后的收尾提示：测验=交卷提醒；练习=完成统计 */}
            <FinishBanner
              code={code}
              isQuiz={isQuiz}
              quizFinished={quizFinished}
              quizStatus={quiz?.status}
              sessionId={sessionId}
              onQuizSubmitted={() => {
                void queryClient.invalidateQueries({
                  queryKey: ["vocab", code, "today"],
                })
              }}
              allDone={allDone}
              hasAnswer={Boolean(answer)}
              answeredCount={answeredCount}
              correctFirst={correctFirst}
              onOpenInsight={() => setInsightOpen(true)}
              canNewRound={
                assignment?.mode === "practice" && !readOnly && isCurrentRound
              }
              newRoundPending={startSession.isPending}
              onNewRound={() => {
                pendingRef.current = null
                startSession.mutate({
                  assignmentId: assignment?.id ?? "",
                  round: "new",
                })
              }}
            />
          </CardContent>
        </Card>

        <p className="pb-4 text-center text-xs text-muted-foreground">
          {t(
            isQuiz
              ? {
                  zh: "测验每题只能提交一次；到时自动交卷，成绩与答案由老师公布。",
                  en: "Each item accepts one submission. Auto-submit at time-up; grades and answers are published by your teacher.",
                }
              : {
                  zh: "练习里可以反复重试；成绩统计按每题第一次作答计算。",
                  en: "Practice allows retries; your stats count the first answer of each item.",
                },
          )}
        </p>
        {explainOpen && item?.headword && (
          <WordExplanationDialog
            code={code}
            headword={item.headword}
            meaningZh={item.meaning_zh}
            partOfSpeech={item.part_of_speech}
            open={explainOpen}
            onClose={() => setExplainOpen(false)}
          />
        )}
        {!isQuiz && (
          <SessionInsightDialog
            code={code}
            sessionId={remoteSessionId}
            open={insightOpen}
            onClose={() => setInsightOpen(false)}
          />
        )}
      </div>
    </StudentShell>
  )
}
