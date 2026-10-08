import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link, useParams } from "@tanstack/react-router"
import {
  ArrowLeft,
  ArrowRight,
  BookOpenCheck,
  CheckCircle2,
  Circle,
  Headphones,
  RotateCcw,
  SpellCheck,
  Volume2,
  XCircle,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import type { VocabularyStudentPlan } from "@/client"
import { ApiError, VocabularyService } from "@/client"
import InfoHint from "@/components/Common/InfoHint"
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
import { WordExplanationDialog } from "@/components/Vocabulary/VocabAi"
import { APP_NAME } from "@/config"
import { useStudentGuard } from "@/hooks/useStudentGuard"
import {
  playAudio as playCachedAudio,
  preloadAudio,
  stopAudio,
} from "@/lib/audio"
import { loadStudent } from "@/lib/classroom-student"
import { useI18n } from "@/lib/i18n"
import {
  EXPLAIN_FIRST_TRY_ACCURACY,
  EXPLAIN_ROUND_TIMES,
  TERMS,
} from "@/lib/terms"
import { speakEnglish } from "@/lib/tts"

export const Route = createFileRoute("/vocab/$code/self")({
  component: VocabSelfPracticePage,
  validateSearch: (search: Record<string, unknown>): { session?: string } => {
    const session = search.session
    return {
      ...(typeof session === "string" && session !== "" ? { session } : {}),
    }
  },
  head: () => ({
    meta: [{ title: `自主练习 / Self Practice - ${APP_NAME}` }],
  }),
})

const KIND_LABELS: Record<string, { zh: string; en: string }> = {
  self: { zh: "自主练习", en: "Self Practice" },
  review: { zh: "错词复习", en: "Wrong-word Review" },
  task: { zh: "词汇任务", en: "Vocabulary Task" },
}

/** 一题的最新作答反馈（含重试次数；重试在练习模式随时可以） */
interface AnswerState {
  isCorrect: boolean
  correctSpelling: string
  attemptNo: number
}

function VocabSelfPracticePage() {
  const { t } = useI18n()
  const { code } = useParams({ from: "/vocab/$code/self" })
  const { session: sessionParam } = Route.useSearch()
  const queryClient = useQueryClient()
  const student = loadStudent(code)

  const planQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: [
      "vocab",
      code,
      "student-session",
      sessionParam ?? "",
      student?.id,
    ],
    queryFn: () =>
      VocabularyService.readStudentSession({
        code: code.toUpperCase(),
        sessionId: sessionParam as string,
      }),
    enabled: student !== null && sessionParam !== undefined,
  })

  useStudentGuard(code, student, planQuery)

  const plan = planQuery.data ?? null
  // 题单按题号排序（后端按快照下标回填，顺序天然稳定）
  const items = useMemo(
    () => [...(plan?.items ?? [])].sort((a, b) => a.item_index - b.item_index),
    [plan],
  )

  // 本地作答反馈（即时渲染）；计划数据是刷新恢复与报告的最终事实源
  const [answers, setAnswers] = useState<Record<number, AnswerState>>({})
  const [current, setCurrent] = useState(0)
  const [input, setInput] = useState("")
  const [explainOpen, setExplainOpen] = useState(false)
  // 重试覆盖：刷新后 plan 里该题 answered 仍为真（那是首答记录），
  // 点「再试一次」时用它放行作答输入框，覆盖首答的已答展示
  const [retryOverrides, setRetryOverrides] = useState<Record<number, true>>({})
  // 轮次绑定键：plan 换轮/换会话时清空本地反馈（防旧反馈沿用新题面）
  const bindingKey = plan?.session_id ?? ""
  const [renderedBinding, setRenderedBinding] = useState(bindingKey)
  if (renderedBinding !== bindingKey) {
    setRenderedBinding(bindingKey)
    setAnswers({})
    setRetryOverrides({})
    setCurrent(0)
    setInput("")
  }

  // 服务端恢复已答状态（刷新/换端进入）；只换会话时才重置当前题位——
  // 普通重拉（提交后/窗口聚焦）不打断学生所在的题
  const restoredSessionRef = useRef<string | null>(null)
  useEffect(() => {
    if (!plan) return
    const restored: Record<number, AnswerState> = {}
    for (const item of plan.items ?? []) {
      if (item.answered && item.headword) {
        restored[item.item_index] = {
          isCorrect: item.is_correct === true,
          correctSpelling: item.headword,
          attemptNo: item.attempt_count ?? 1,
        }
      }
    }
    setAnswers(restored)
    if (restoredSessionRef.current !== plan.session_id) {
      restoredSessionRef.current = plan.session_id
      const firstUnanswered = (plan.items ?? []).findIndex(
        (item) => !item.answered,
      )
      setCurrent(firstUnanswered >= 0 ? firstUnanswered : 0)
    }
  }, [plan])

  // 幂等键跟随「一次作答意图」（与任务练习页同口径）：
  // 只有原样重试才复用同键；改输入/换题/重练都换新键
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
        sessionId: sessionParam as string,
        requestBody: {
          item_index: payload.itemIndex,
          prompt_type: payload.promptType,
          answer: payload.answer,
          idempotency_key: pendingRef.current?.key,
        },
      })
    },
    onSuccess: (result) => {
      pendingRef.current = null
      // 自主/复习轮永远是练习口径（即时反馈）；测验只发生在任务轮
      const graded = result as {
        item_index: number
        is_correct: boolean
        correct_spelling: string
        attempt_no: number
      }
      setAnswers((prev) => ({
        ...prev,
        [graded.item_index]: {
          isCorrect: graded.is_correct,
          correctSpelling: graded.correct_spelling,
          attemptNo: graded.attempt_no,
        },
      }))
      // 全部答完即重拉计划：报告需要服务端的 submitted_at 与逐词首答
      if (result.session_status === "submitted") {
        void queryClient.invalidateQueries({
          queryKey: ["vocab", code, "student-session"],
        })
        void queryClient.invalidateQueries({ queryKey: ["vocab", code] })
      }
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status < 500) {
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
        toast.error(
          t({
            zh: "网络不稳定，请重试；已送达的作答不会重复计分。",
            en: "Network hiccup — please retry; a delivered answer won't be double-counted.",
          }),
        )
      }
    },
  })

  const item = items[current]
  const answer = item ? answers[item.item_index] : undefined
  const planItemAnswered = item?.answered ?? false
  // 本题正在重练（覆盖首答的已答展示，放行输入框）
  const isRetrying = item ? retryOverrides[item.item_index] === true : false
  // 听音在当前题可用 = 有标准音，或该词已作答（拼写已揭示，可设备朗读）
  const audioUsableNow = Boolean(
    item && (item.audio_url || answer || planItemAnswered),
  )
  const planHasAudio = (plan?.items ?? []).some(
    (it) => it.audio_url || it.prompt_type === "audio",
  )
  const [useAudio, setUseAudio] = useState(false)
  // 当前题不可听音时回落看义；默认始终看义（不自动切走学生的选择）
  useEffect(() => {
    if (!audioUsableNow) setUseAudio(false)
  }, [audioUsableNow])

  const answeredCount = new Set([
    ...Object.keys(answers).map(Number),
    ...(plan?.items ?? [])
      .filter((it) => it.answered)
      .map((it) => it.item_index),
  ]).size
  const correctFirst = (plan?.items ?? []).filter(
    (it) => it.answered && it.is_correct === true,
  ).length
  const allDone =
    plan !== null && items.length > 0 && answeredCount >= items.length
  const submitted = plan?.status === "submitted"
  const readOnly = submitted

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
    // 无标准音：仅已作答（拼写已揭示）时设备朗读兜底，界面标明
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
    if (!item || input.trim() === "" || submitAnswer.isPending || readOnly)
      return
    submitAnswer.mutate({
      itemIndex: item.item_index,
      promptType: useAudio ? "audio" : "meaning",
      answer: input.trim(),
    })
  }

  const retry = () => {
    if (!item || readOnly) return
    pendingRef.current = null // 重练是一次新作答意图
    setRetryOverrides((prev) => ({ ...prev, [item.item_index]: true }))
    setAnswers((prev) => {
      const next = { ...prev }
      delete next[item.item_index]
      return next
    })
    setInput("")
  }

  const goNext = () => {
    setInput("")
    pendingRef.current = null
    if (current < items.length - 1) {
      setCurrent(current + 1)
    }
  }

  if (student === null) return null

  if (sessionParam === undefined) {
    return (
      <StudentShell active="vocab">
        <EmptyCard
          code={code}
          title={t({ zh: "还没有选择练习", en: "No practice selected" })}
          body={t({
            zh: "去词库挑一本词，或从错词本开一轮复习。",
            en: "Pick a word book, or start a review from your Wrong Words.",
          })}
        />
      </StudentShell>
    )
  }

  if (planQuery.isPending) {
    return (
      <StudentShell active="vocab">
        <div role="status" className="space-y-6">
          <span className="sr-only">
            {t({ zh: "正在加载练习…", en: "Loading practice…" })}
          </span>
          <Skeleton className="h-64 rounded-2xl" />
        </div>
      </StudentShell>
    )
  }

  if (planQuery.isError || !plan || items.length === 0 || !item) {
    return (
      <StudentShell active="vocab">
        <EmptyCard
          code={code}
          title={t({
            zh: "找不到这次练习",
            en: "This practice round can't be found",
          })}
          body={t({
            zh: "它可能不属于你的账号。可以去词库重新开一轮练习。",
            en: "It may not belong to your account. You can start a fresh round from the word books.",
          })}
        />
      </StudentShell>
    )
  }

  const kindLabel = t(KIND_LABELS[plan.kind] ?? KIND_LABELS.self)
  const mixedWrong = (plan.items ?? []).filter((it) => it.from_wrong).length
  const answeredCountPlan = plan.answered_count ?? 0
  const accuracy =
    answeredCountPlan > 0
      ? Math.round(((plan.correct_first_count ?? 0) / answeredCountPlan) * 100)
      : null

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

        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="text-muted-foreground">
            {kindLabel}
          </Badge>
          <h1 className="min-w-0 truncate text-base font-semibold">
            {plan.title}
          </h1>
          {plan.mix_wrong && mixedWrong > 0 && (
            <Badge variant="secondary" className="text-primary">
              <BookOpenCheck className="size-3" />
              {t({
                zh: `混入错词 ${mixedWrong}`,
                en: `${mixedWrong} wrong words mixed in`,
              })}
            </Badge>
          )}
          {submitted && (
            <Badge variant="secondary">
              {t({ zh: "已完成", en: "Completed" })}
            </Badge>
          )}
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
                    zh: `第 ${index + 1} 题${state ? (state.isCorrect ? "（对）" : "（错）") : it.answered ? (it.is_correct ? "（对）" : "（错）") : "（未答）"}`,
                    en: `Item ${index + 1}${state ? (state.isCorrect ? " (correct)" : " (missed)") : it.answered ? (it.is_correct ? " (correct)" : " (missed)") : " (not answered)"}`,
                  })}
                  aria-current={index === current ? "true" : undefined}
                  onClick={() => {
                    setCurrent(index)
                    setInput("")
                    pendingRef.current = null // 换题 = 新作答意图
                  }}
                  className={`size-11 rounded-xl border text-sm font-semibold transition-colors ${
                    index === current
                      ? "border-primary bg-primary text-primary-foreground"
                      : state || it.answered
                        ? (state ? state.isCorrect : it.is_correct)
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

            {/* 题型切换：听音在无标准音且未作答时禁用（不提前泄露拼写） */}
            {planHasAudio && (
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant={useAudio ? "default" : "outline"}
                  size="sm"
                  disabled={!audioUsableNow}
                  aria-disabled={!audioUsableNow}
                  onClick={() => setUseAudio(true)}
                >
                  <Headphones />
                  {t(TERMS.promptAudio)}
                </Button>
                <Button
                  type="button"
                  variant={!useAudio ? "default" : "outline"}
                  size="sm"
                  onClick={() => setUseAudio(false)}
                >
                  <SpellCheck />
                  {t(TERMS.promptMeaning)}
                </Button>
                {!audioUsableNow && (
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
            {/* 作答区：首答未答或正在重练时放行输入框；已答展示首答反馈 */}
            {!answer && (!planItemAnswered || isRetrying) ? (
              <form
                onSubmit={handleSubmit}
                className="flex flex-col gap-3 sm:flex-row"
              >
                <label className="sr-only" htmlFor="self-vocab-answer">
                  {t({ zh: "输入英文单词", en: "Type the English word" })}
                </label>
                <Input
                  id="self-vocab-answer"
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
                  disabled={submitAnswer.isPending || readOnly}
                />
                <Button
                  type="submit"
                  className="h-12 px-6"
                  disabled={
                    input.trim() === "" || submitAnswer.isPending || readOnly
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
                    (answer ? answer.isCorrect : item.is_correct)
                      ? "border-primary/30 bg-primary/5"
                      : "border-border bg-secondary/50"
                  }`}
                >
                  {(answer ? answer.isCorrect : item.is_correct) ? (
                    <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-primary" />
                  ) : (
                    <XCircle className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
                  )}
                  <div className="min-w-0 space-y-1">
                    <p className="font-semibold">
                      {(answer ? answer.isCorrect : item.is_correct)
                        ? t({ zh: "拼对了！", en: "Correct!" })
                        : t({
                            zh: "差一点点，再看看正确拼写。",
                            en: "So close — check the correct spelling.",
                          })}
                    </p>
                    <p className="text-sm">
                      <span className="font-semibold">
                        {answer?.correctSpelling ?? item.headword}
                      </span>
                      <span className="ml-2 text-muted-foreground">
                        {item.meaning_zh}
                      </span>
                    </p>
                    {!(answer ? answer.isCorrect : item.is_correct) &&
                      (answer && input.trim() !== ""
                        ? input.trim()
                        : (item.first_answer ?? "")) !== "" && (
                        <p className="text-sm text-muted-foreground">
                          {t({ zh: "你拼的是：", en: "You typed: " })}
                          <span className="font-mono">
                            {answer && input.trim() !== ""
                              ? input.trim()
                              : item.first_answer}
                          </span>
                        </p>
                      )}
                    {(answer?.attemptNo ?? item.attempt_count ?? 1) > 1 && (
                      <p className="text-xs text-muted-foreground">
                        {t({
                          zh: `第 ${answer?.attemptNo ?? item.attempt_count} 次尝试（成绩按第一次计算）`,
                          en: `Try #${answer?.attemptNo ?? item.attempt_count} (score counts the first try)`,
                        })}
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {/* 已完成的轮只读回看：不再提供重练入口（成绩锁定首答） */}
                  {!answer?.isCorrect && !readOnly && (
                    <Button variant="outline" onClick={retry}>
                      <RotateCcw />
                      {t({ zh: "再试一次", en: "Try again" })}
                    </Button>
                  )}
                  {item.headword && (
                    <Button
                      variant="ghost"
                      onClick={() => setExplainOpen(true)}
                    >
                      {t(TERMS.aiWordExplanation)}
                    </Button>
                  )}
                  <Button onClick={goNext}>
                    {current < items.length - 1
                      ? t({ zh: "下一个词", en: "Next word" })
                      : t({ zh: "查看本轮报告", en: "See round report" })}
                    <ArrowRight />
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* 本轮报告：全部答完或已提交时展示 */}
        {(allDone || submitted) && (
          <RoundReport
            plan={plan}
            accuracy={accuracy}
            kindLabel={kindLabel}
            code={code}
          />
        )}

        <p className="pb-4 text-center text-xs text-muted-foreground">
          {t({
            zh: "练习里可以反复重试；统计按每题第一次作答计算。",
            en: "Practice allows retries; stats count the first answer of each item.",
          })}
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
      </div>
    </StudentShell>
  )
}

/** 本轮报告：口径分开——正确率分母=已答，完成进度分母=总题数 */
function RoundReport({
  plan,
  accuracy,
  kindLabel,
  code,
}: {
  plan: VocabularyStudentPlan
  accuracy: number | null
  kindLabel: string
  code: string
}) {
  const { t } = useI18n()
  const answered = plan.answered_count ?? 0
  const total = plan.total_count ?? 0
  const items = plan.items ?? []
  const wrongItems = items.filter(
    (it) => it.answered && it.is_correct === false,
  )
  const correctedWrong = items.filter(
    (it) => it.from_wrong && it.is_correct === true,
  )
  const fmtTime = (value?: string | null) =>
    value ? new Date(value).toLocaleString() : "–"

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {t({ zh: "本轮报告", en: "Round Report" })}
          <Badge variant="outline" className="ml-2 text-muted-foreground">
            {kindLabel}
          </Badge>
        </CardTitle>
        <CardDescription>
          {t({
            zh: `已答 ${answered} / ${total} 题（完成进度按本轮总题数计）`,
            en: `${answered} / ${total} answered (progress counts this round's total items)`,
          })}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-2 sm:grid-cols-3">
          <div className="rounded-2xl bg-secondary/50 p-4">
            <p className="text-xs text-muted-foreground">
              {t({ zh: "首答正确数", en: "Correct on first try" })}
            </p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">
              {plan.correct_first_count ?? 0}
            </p>
          </div>
          <div className="rounded-2xl bg-secondary/50 p-4">
            <p className="text-xs text-muted-foreground">
              {t({ zh: "首答正确率", en: "First-try accuracy" })}
              <InfoHint label={t(EXPLAIN_FIRST_TRY_ACCURACY)} />
            </p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">
              {accuracy === null
                ? t({ zh: "未作答", en: "Not answered" })
                : `${accuracy}%`}
            </p>
          </div>
          <div className="rounded-2xl bg-secondary/50 p-4">
            <p className="text-xs text-muted-foreground">
              {t({ zh: "本轮起止", en: "Round times" })}
              <InfoHint label={t(EXPLAIN_ROUND_TIMES)} />
            </p>
            <p className="mt-1 text-sm font-medium leading-5">
              {fmtTime(plan.started_at)}
              <br />
              ↓<br />
              {fmtTime(plan.submitted_at)}
            </p>
          </div>
        </div>

        {correctedWrong.length > 0 && (
          <div className="rounded-2xl border border-primary/20 bg-primary/5 p-4">
            <p className="text-sm font-semibold">
              {t({
                zh: `本轮纠正了 ${correctedWrong.length} 个历史错词。`,
                en: `You corrected ${correctedWrong.length} previously missed word(s) this round.`,
              })}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {t({
                zh: "它们仍会留在错词本里，多练几轮再放心。",
                en: "They stay in your Wrong Words book — a few more rounds to be sure.",
              })}
            </p>
          </div>
        )}

        {wrongItems.length > 0 && (
          <div>
            <p className="mb-2 text-sm font-medium">
              {t({
                zh: `本轮拼错的词（${wrongItems.length}）`,
                en: `Missed this round (${wrongItems.length})`,
              })}
            </p>
            <ul className="grid gap-1.5 sm:grid-cols-2">
              {wrongItems.map((it) => (
                <li
                  key={it.item_index}
                  className="min-w-0 flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-xl border px-3 py-2"
                >
                  <span className="max-w-full break-all text-sm font-semibold">
                    {it.headword}
                  </span>
                  <span className="min-w-0 flex-1 basis-24 truncate text-xs text-muted-foreground">
                    {it.meaning_zh}
                  </span>
                  {it.first_answer && (
                    <span className="max-w-full truncate font-mono text-xs text-muted-foreground line-through">
                      {it.first_answer}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div>
          <p className="mb-2 text-sm font-medium">
            {t({ zh: "正确拼写对答案", en: "Correct spellings" })}
          </p>
          <ul className="grid gap-1.5 sm:grid-cols-2">
            {items.map((it) => (
              <li
                key={it.item_index}
                className="flex items-center gap-2 rounded-xl border px-3 py-2"
              >
                {it.answered ? (
                  it.is_correct ? (
                    <CheckCircle2 className="size-4 shrink-0 text-primary" />
                  ) : (
                    <XCircle className="size-4 shrink-0 text-muted-foreground" />
                  )
                ) : (
                  <Circle className="size-4 shrink-0 text-border" />
                )}
                <span className="min-w-0 flex-1 truncate text-sm">
                  {it.answered && it.headword ? (
                    <span className="font-semibold">{it.headword}</span>
                  ) : (
                    <span className="text-muted-foreground">?</span>
                  )}
                  <span className="ml-2 text-muted-foreground">
                    {it.meaning_zh}
                  </span>
                </span>
              </li>
            ))}
          </ul>
          {answered < total && (
            <p className="mt-2 text-xs text-muted-foreground">
              {t({
                zh: `还有 ${total - answered} 题未作答，不显示拼写。`,
                en: `${total - answered} item(s) unanswered — spellings stay hidden.`,
              })}
            </p>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          <Button asChild size="sm" variant="outline">
            <Link to="/vocab/$code/records" params={{ code }}>
              {t({ zh: "查看练习记录", en: "View Practice Records" })}
              <ArrowRight />
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function EmptyCard({
  code,
  title,
  body,
}: {
  code: string
  title: string
  body: string
}) {
  const { t } = useI18n()
  return (
    <Card className="items-center px-6 py-12 text-center">
      <SpellCheck className="size-10 text-primary" />
      <h1 className="mt-3 text-xl font-semibold">{title}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{body}</p>
      <Button asChild className="mt-4">
        <Link to="/vocab/$code/books" params={{ code }}>
          {t({ zh: "去词库挑词", en: "Browse Word Books" })}
        </Link>
      </Button>
    </Card>
  )
}
