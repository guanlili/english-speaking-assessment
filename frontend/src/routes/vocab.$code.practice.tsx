import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  useNavigate,
  useParams,
} from "@tanstack/react-router"
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Headphones,
  RotateCcw,
  SpellCheck,
  Volume2,
  XCircle,
} from "lucide-react"
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
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { APP_NAME } from "@/config"
import { loadStudent } from "@/lib/classroom-student"
import { useI18n } from "@/lib/i18n"
import { TERMS } from "@/lib/terms"
import { speakEnglish } from "@/lib/tts"

export const Route = createFileRoute("/vocab/$code/practice")({
  component: VocabPracticePage,
  head: () => ({
    meta: [{ title: `拼写练习 / Spelling Practice - ${APP_NAME}` }],
  }),
})

/** 一题的最新作答反馈（含重试次数；重试在练习模式随时可以） */
interface AnswerState {
  isCorrect: boolean
  correctSpelling: string
  attemptNo: number
}

function VocabPracticePage() {
  const { t } = useI18n()
  const { code } = useParams({ from: "/vocab/$code/practice" })
  const navigate = useNavigate({ from: "/vocab/$code/practice" })
  const queryClient = useQueryClient()
  const student = loadStudent(code)

  const todayQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: ["vocab", code, "today", student?.id],
    queryFn: () =>
      VocabularyService.readVocabToday({ code: code.toUpperCase() }),
    enabled: student !== null,
  })

  const assignment = todayQuery.data?.assignment ?? null
  const items = useMemo(
    () =>
      [...(todayQuery.data?.items ?? [])].sort(
        (a, b) => a.item_index - b.item_index,
      ),
    [todayQuery.data],
  )

  // 已答状态（刷新恢复：服务端 plan 里带回首答结果）
  const [answers, setAnswers] = useState<Record<number, AnswerState>>({})
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
  }, [todayQuery.data])

  // 进入时定位到第一道未作答的题
  const [current, setCurrent] = useState(0)
  const initialized = useRef(false)
  useEffect(() => {
    if (initialized.current || items.length === 0) return
    initialized.current = true
    const firstUnanswered = items.findIndex((item) => !item.answered)
    setCurrent(firstUnanswered >= 0 ? firstUnanswered : 0)
  }, [items])

  // 会话创建（幂等）：任务就绪且尚无会话时自动开始
  const [sessionId, setSessionId] = useState<string | null>(null)
  const startSession = useMutation({
    mutationFn: (assignmentId: string) =>
      VocabularyService.startVocabSession({
        code: code.toUpperCase(),
        requestBody: { assignment_id: assignmentId },
      }),
    onSuccess: (data) => {
      setSessionId((data as { session_id: string }).session_id)
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
      }
    },
  })
  useEffect(() => {
    if (todayQuery.data?.session_id) {
      setSessionId(todayQuery.data.session_id)
      return
    }
    if (
      assignment &&
      !sessionId &&
      !startSession.isPending &&
      !startSession.isError
    ) {
      startSession.mutate(assignment.id)
    }
  }, [assignment, sessionId, startSession, todayQuery.data])

  const [input, setInput] = useState("")
  const inputRef = useRef<HTMLInputElement>(null)
  // 幂等键跟随「一次作答意图」：提交前生成，网络失败保留（断网重试原样重发、
  // 服务端重放返回同一判分）；成功或学生开始新意图（换题/重练）时清除
  const pendingKeyRef = useRef<string | null>(null)
  const submitAnswer = useMutation({
    mutationFn: (payload: {
      itemIndex: number
      promptType: string
      answer: string
    }) => {
      if (pendingKeyRef.current === null) {
        pendingKeyRef.current = crypto.randomUUID()
      }
      return VocabularyService.submitVocabAnswer({
        sessionId: sessionId as string,
        requestBody: {
          item_index: payload.itemIndex,
          prompt_type: payload.promptType,
          answer: payload.answer,
          idempotency_key: pendingKeyRef.current,
        },
      })
    },
    onSuccess: (result) => {
      pendingKeyRef.current = null
      setAnswers((prev) => ({
        ...prev,
        [result.item_index]: {
          isCorrect: result.is_correct,
          correctSpelling: result.correct_spelling,
          attemptNo: result.attempt_no,
        },
      }))
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        // 422 幂等键冲突等业务拒绝：作答意图已无效，清键换新意图重试
        pendingKeyRef.current = null
        toast.error(
          error.status === 422
            ? t({
                zh: "这道题暂时不能这样作答，请刷新后重试。",
                en: "This item can't be answered this way — refresh and retry.",
              })
            : t({
                zh: "提交失败，请重试（同一作答不会重复记分）。",
                en: "Submit failed — please retry (the same answer won't be scored twice).",
              }),
        )
      } else {
        // 网络错误：保留幂等键，重试复用同一判分
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
    audioInTask && Boolean(item?.audio_url || answer !== undefined)
  const [useAudio, setUseAudio] = useState(false)
  useEffect(() => {
    setUseAudio(audioInTask && !meaningInTask && audioUsableHere)
  }, [audioInTask, meaningInTask, audioUsableHere])

  const answeredCount = Object.keys(answers).length
  const correctFirst = items.filter(
    (it) => it.answered && it.is_correct === true,
  ).length
  const allDone = items.length > 0 && answeredCount >= items.length

  const playAudio = () => {
    if (!item) return
    if (item.audio_url) {
      const audio = new Audio(item.audio_url)
      audio.play().catch(() => {
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
    if (!item || !sessionId || input.trim() === "" || submitAnswer.isPending)
      return
    submitAnswer.mutate({
      itemIndex: item.item_index,
      promptType: useAudio ? "audio" : "meaning",
      answer: input.trim(),
    })
  }

  const retry = () => {
    if (!item) return
    pendingKeyRef.current = null // 重练是一次新作答意图
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
    pendingKeyRef.current = null
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
          <p className="text-xs text-muted-foreground">
            {t({
              zh: `第 ${current + 1} / ${items.length} 题 · 首答正确 ${correctFirst}`,
              en: `Item ${current + 1} / ${items.length} · ${correctFirst} correct on first try`,
            })}
          </p>
        </div>

        {/* 进度点：点选跳题；对=主色、错=灰、当前=实心 */}
        <ul
          className="flex flex-wrap gap-1.5"
          aria-label={t({ zh: "作答进度", en: "Answer progress" })}
        >
          {items.map((it, index) => {
            const state = answers[it.item_index]
            return (
              <li key={it.item_index}>
                <button
                  type="button"
                  aria-label={t({
                    zh: `第 ${index + 1} 题${state ? (state.isCorrect ? "（对）" : "（错）") : "（未答）"}`,
                    en: `Item ${index + 1}${state ? (state.isCorrect ? " (correct)" : " (missed)") : " (not answered)"}`,
                  })}
                  aria-current={index === current ? "true" : undefined}
                  onClick={() => {
                    setCurrent(index)
                    setInput("")
                    pendingKeyRef.current = null // 换题 = 新作答意图
                  }}
                  className={`size-11 rounded-xl border text-sm font-semibold transition-colors ${
                    index === current
                      ? "border-primary bg-primary text-primary-foreground"
                      : state
                        ? state.isCorrect
                          ? "border-primary/30 bg-secondary text-primary"
                          : "border-border bg-secondary/60 text-muted-foreground"
                        : "border-border text-muted-foreground hover:border-primary/40"
                  }`}
                >
                  {index + 1}
                </button>
              </li>
            )
          })}
        </ul>

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

            {/* 作答区 */}
            {!answer ? (
              <form
                onSubmit={handleSubmit}
                className="flex flex-col gap-3 sm:flex-row"
              >
                <label className="sr-only" htmlFor="vocab-answer">
                  {t({ zh: "输入英文单词", en: "Type the English word" })}
                </label>
                <Input
                  id="vocab-answer"
                  ref={inputRef}
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  placeholder={t({
                    zh: "在这里输入英文单词…",
                    en: "Type the English word here…",
                  })}
                  autoComplete="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  className="h-12 flex-1 text-base"
                  disabled={!sessionId || startSession.isPending}
                />
                <Button
                  type="submit"
                  className="h-12 px-6"
                  disabled={
                    input.trim() === "" || submitAnswer.isPending || !sessionId
                  }
                >
                  {submitAnswer.isPending
                    ? t({ zh: "判分中…", en: "Checking…" })
                    : t({ zh: "提交", en: "Submit" })}
                </Button>
              </form>
            ) : (
              <div className="space-y-4">
                <div
                  role="status"
                  className={`flex items-start gap-3 rounded-2xl border p-4 ${
                    answer.isCorrect
                      ? "border-primary/30 bg-primary/5"
                      : "border-border bg-secondary/50"
                  }`}
                >
                  {answer.isCorrect ? (
                    <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-primary" />
                  ) : (
                    <XCircle className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
                  )}
                  <div className="min-w-0 space-y-1">
                    <p className="font-semibold">
                      {answer.isCorrect
                        ? t({ zh: "拼对了！", en: "Correct!" })
                        : t({
                            zh: "差一点点，再看看正确拼写。",
                            en: "So close — check the correct spelling.",
                          })}
                    </p>
                    <p className="text-sm">
                      <span className="font-semibold">
                        {answer.correctSpelling}
                      </span>
                      <span className="ml-2 text-muted-foreground">
                        {item.meaning_zh}
                      </span>
                    </p>
                    {!answer.isCorrect && input.trim() !== "" && (
                      <p className="text-sm text-muted-foreground">
                        {t({ zh: "你拼的是：", en: "You typed: " })}
                        <span className="font-mono">{input.trim()}</span>
                      </p>
                    )}
                    {answer.attemptNo > 1 && (
                      <p className="text-xs text-muted-foreground">
                        {t({
                          zh: `第 ${answer.attemptNo} 次尝试（成绩按第一次计算）`,
                          en: `Try #${answer.attemptNo} (score counts the first try)`,
                        })}
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {!answer.isCorrect && (
                    <Button variant="outline" onClick={retry}>
                      <RotateCcw />
                      {t({ zh: "再试一次", en: "Try again" })}
                    </Button>
                  )}
                  <Button onClick={goNext}>
                    {current < items.length - 1
                      ? t({ zh: "下一个词", en: "Next word" })
                      : allDone || answeredCount >= items.length
                        ? t({ zh: "完成练习", en: "Finish" })
                        : t({ zh: "下一个词", en: "Next word" })}
                    <ArrowRight />
                  </Button>
                </div>
              </div>
            )}

            {/* 走完全部题后的收尾提示 */}
            {allDone && answer && (
              <div className="rounded-2xl border border-primary/20 bg-secondary/40 p-4">
                <p className="text-sm font-semibold">
                  {t({
                    zh: `这一轮完成了：${answeredCount} 词，首答正确 ${correctFirst} 个。`,
                    en: `Round complete: ${answeredCount} words, ${correctFirst} correct on first try.`,
                  })}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t({
                    zh: "错词已收进错词本；点上面的数字方块可以回来重练任意词。",
                    en: "Missed words are in your Wrong Words book; tap any number above to re-practice it.",
                  })}
                </p>
                <Button asChild size="sm" className="mt-3">
                  <Link to="/vocab/$code" params={{ code }}>
                    {t({ zh: "回词汇首页", en: "Back to Vocabulary home" })}
                    <ArrowRight />
                  </Link>
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        <p className="pb-4 text-center text-xs text-muted-foreground">
          {t({
            zh: "练习里可以反复重试；成绩统计按每题第一次作答计算。",
            en: "Practice allows retries; your stats count the first answer of each item.",
          })}
        </p>
      </div>
    </StudentShell>
  )
}
