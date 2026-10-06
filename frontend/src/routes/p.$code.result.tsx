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
import { useEffect, useMemo, useRef, useState } from "react"
import type { PlanAttempt, PlanItem } from "@/client"
import { ClassesService } from "@/client"
import InfoHint from "@/components/Common/InfoHint"
import AttemptAudio from "@/components/Practice/AttemptAudio"
import { RubricBlock } from "@/components/Practice/FeedbackCard"
import StudentShell from "@/components/Practice/StudentShell"
import VocabBlock from "@/components/Practice/VocabBlock"
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
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { APP_NAME } from "@/config"
import { displayName, loadStudent } from "@/lib/classroom-student"
import { savedExpressionsKey } from "@/lib/favorites"
import { useI18n } from "@/lib/i18n"
import { EXPLAIN, ITEM_TYPE_LABELS, TERMS } from "@/lib/terms"

export const Route = createFileRoute("/p/$code/result")({
  component: RoundResultPage,
  validateSearch: (
    search: Record<string, unknown>,
  ): { explore?: string; session?: string } => {
    // session：练习页在录音/完成时钉住的实际会话，结果绑定该轮而非当前活动计划
    if (typeof search.session === "string") return { session: search.session }
    if (typeof search.explore === "string") return { explore: search.explore }
    return {}
  },
  head: () => ({
    meta: [{ title: `本轮结果 / Round Results - ${APP_NAME}` }],
  }),
})

function RoundResultPage() {
  const { t } = useI18n()
  const { code } = useParams({ from: "/p/$code/result" })
  const { explore: exploreSessionId, session: sessionParam } = Route.useSearch()
  const navigate = useNavigate({ from: "/p/$code/result" })
  const student = loadStudent(code)
  // 结果绑定实际完成会话（练习页在录音/完成时传入的 session；探索轮兼容 explore）
  const sessionId = sessionParam ?? exploreSessionId

  const todayQuery = useQuery({
    queryKey: ["classroom", code, "today", student?.id, sessionId],
    queryFn: () =>
      ClassesService.readTodayPlan({
        code: code.toUpperCase(),
        // 主题探索轮/回看会话：结果必须属于该轮会话，而不是当日课堂计划
        ...(sessionId ? { sessionId } : {}),
      }),
    enabled: student !== null,
    refetchInterval: (query) =>
      query.state.data?.attempts.some(
        (a) =>
          a.status === "queued" ||
          a.status === "scoring" ||
          a.rubric?.status === "pending",
      )
        ? 2000
        : false,
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
        search: {
          next: true,
          ...(sessionId ? { session: sessionId } : {}),
        },
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

  // 3 星或新徽章 → 庆祝彩带（每次挂载只放一次；轮询刷新 gamification 对象不重放）
  const confettiFiredRef = useRef(false)
  useEffect(() => {
    if (confettiFiredRef.current) return
    if (
      gamification &&
      (gamification.session_stars === 3 || newBadges.length > 0)
    ) {
      confettiFiredRef.current = true
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

  // 本轮汇总（SpeakUp 4 统计卡）
  const roundStats = useMemo(() => {
    const done = doneItems.map((d) => d.attempt)
    const avg = (nums: Array<number | null | undefined>) => {
      const valid = nums.filter(
        (n): n is number => n !== null && n !== undefined,
      )
      return valid.length
        ? Math.round(valid.reduce((a, b) => a + b, 0) / valid.length)
        : null
    }
    const repeats = doneItems.filter((d) => d.item.type !== "question")
    const questions = doneItems.filter((d) => d.item.type === "question")
    const lastVocab = [...questions].reverse().find((d) => d.attempt.vocab)
    return {
      overall: avg(done.map((a) => a.overall)),
      completeness: avg(repeats.map((d) => d.attempt.completeness)),
      fluency: avg(done.map((a) => a.fluency)),
      vocabCefr:
        (lastVocab?.attempt.vocab as { cefr?: string } | undefined)?.cefr ??
        null,
      hitWords: questions.flatMap((d) => {
        const v = d.attempt.vocab as
          | { hits?: Record<string, string[]> }
          | undefined
        return Object.values(v?.hits ?? {}).flat()
      }),
      rubric: (() => {
        const rubrics = questions
          .map((d) => d.attempt.rubric)
          .filter((r) => r && typeof r.mock_score === "number")
        if (!rubrics.length) return undefined
        const mean = (key: string) => {
          const values = rubrics
            .map((r) => r?.[key])
            .filter((v): v is number => typeof v === "number")
          return values.length
            ? Math.round(
                (values.reduce((a, b) => a + b, 0) / values.length) * 10,
              ) / 10
            : undefined
        }
        return {
          fluency: mean("fluency"),
          vocabulary: mean("vocabulary"),
          grammar: mean("grammar"),
          task: mean("task"),
          mock_score: mean("mock_score"),
          count: rubrics.length,
        }
      })(),
    }
  }, [doneItems])

  if (student === null) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        <Button variant="outline" asChild>
          <Link to="/j/$code" params={{ code }}>
            {t({ zh: "先进入课堂", en: "Join the class first" })}
          </Link>
        </Button>
      </div>
    )
  }

  if (todayQuery.isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        {t({ zh: "正在加载结果…", en: "Loading results…" })}
      </div>
    )
  }
  if (todayQuery.isError || !plan) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        {t({
          zh: "结果加载失败，请刷新重试。",
          en: "Results failed to load — please refresh and retry.",
        })}
      </div>
    )
  }

  return (
    <StudentShell active="practice">
      <div className="flex flex-col gap-6">
        <div>
          <h1 className="text-xl font-bold tracking-tight">
            {t({
              zh: "今天的你，又向前了一步。",
              en: "You moved one step further today.",
            })}
          </h1>
          <p className="text-sm text-muted-foreground">
            {displayName(student)} ·{" "}
            {t({
              zh: `课堂 ${plan.classroom_code} · 每题转写和参考分`,
              en: `Classroom ${plan.classroom_code} · transcripts and reference scores per item`,
            })}
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
                {t({
                  zh: "比起完美，开口本身就很棒。",
                  en: "Speaking up itself is wonderful — perfection can wait.",
                })}
              </h2>
              <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span
                      role="img"
                      aria-label={t({
                        zh: `本轮星级：${gamification.session_stars} / 3`,
                        en: `Stars this round: ${gamification.session_stars} / 3`,
                      })}
                      className="flex items-center gap-1"
                    >
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
                  </TooltipTrigger>
                  <TooltipContent className="max-w-64 text-xs leading-relaxed">
                    {t(EXPLAIN.stars)}
                  </TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="flex items-center gap-1 font-semibold">
                      <Sparkles className="size-4 text-primary" />
                      XP {gamification.xp}
                      <span className="sr-only">{t(EXPLAIN.xp)}</span>
                    </span>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-64 text-xs leading-relaxed">
                    {t(EXPLAIN.xp)}
                  </TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="flex items-center gap-1 text-muted-foreground">
                      <Flame className="size-4 text-orange-500" />
                      {t({
                        zh: `连胜 ${gamification.streak_days} 天`,
                        en: `Streak ${gamification.streak_days} days`,
                      })}
                      <span className="sr-only">{t(EXPLAIN.streak)}</span>
                    </span>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-64 text-xs leading-relaxed">
                    {t(EXPLAIN.streak)}
                  </TooltipContent>
                </Tooltip>
              </div>
              <p className="mt-1.5 text-xs text-muted-foreground">
                {t(EXPLAIN.stars)}
              </p>
              {newBadges.length > 0 && (
                <p className="mt-2 flex items-center gap-1 text-sm">
                  <span className="font-semibold">
                    {t({ zh: "本轮获得徽章：", en: "New badges this round:" })}
                  </span>
                  {newBadges
                    .map((b) => b.label)
                    .join(t({ zh: "、", en: ", " }))}
                  <InfoHint label={t(EXPLAIN.badges)} />
                </p>
              )}
            </div>
          </section>
        )}

        {doneItems.length > 0 && (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {(
                [
                  [
                    t({ zh: "参考分", en: "Reference Score" }),
                    roundStats.overall,
                    t({ zh: "本轮均值", en: "Round average" }),
                  ],
                  [
                    t({ zh: "完整度参考", en: "Completeness" }),
                    roundStats.completeness,
                    t(TERMS.typeRepeat),
                  ],
                  [
                    t({ zh: "流利度参考", en: "Fluency" }),
                    roundStats.fluency,
                    t({ zh: "全部题目", en: "All items" }),
                  ],
                  [
                    t({ zh: "词汇覆盖", en: "Vocabulary" }),
                    roundStats.vocabCefr
                      ? t({ zh: "已分析（历史口径）", en: "Analyzed (legacy)" })
                      : "–",
                    t({
                      zh: "老词表口径仅历史作答保留；现行为五级词库口径",
                      en: "Legacy wordlist kept for past answers; current standard is five-level",
                    }),
                  ],
                ] as const
              ).map(([label, value, note]) => (
                <Card key={label}>
                  <CardContent className="py-4">
                    <p className="text-xs text-muted-foreground">{label}</p>
                    <p className="mt-1 text-2xl font-bold tabular-nums">
                      {value === null ? "–" : value}
                    </p>
                    <p className="text-[10px] text-muted-foreground">{note}</p>
                  </CardContent>
                </Card>
              ))}
            </div>

            {(roundStats.hitWords.length > 0 || roundStats.rubric) && (
              <div className="grid gap-5 md:grid-cols-2">
                {roundStats.hitWords.length > 0 && (
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">
                        {t({
                          zh: "把好表达，变成自己的",
                          en: "Make great expressions your own",
                        })}
                      </CardTitle>
                      <CardDescription>
                        {t({
                          zh: "只分析自主问答 · 来源：分级词表命中",
                          en: "Self-practice Q&A only · source: graded wordlist hits",
                        })}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="flex flex-wrap gap-1.5">
                      {Array.from(new Set(roundStats.hitWords))
                        .slice(0, 24)
                        .map((w) => (
                          <span
                            key={w}
                            className="rounded bg-secondary px-2 py-0.5 text-xs text-primary"
                          >
                            {w}
                          </span>
                        ))}
                    </CardContent>
                  </Card>
                )}
                {roundStats.rubric && (
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">
                        {t({ zh: "说得更自然一点", en: "Sound more natural" })}
                      </CardTitle>
                      <CardDescription>
                        {t({
                          zh: `模拟分 ${roundStats.rubric.mock_score ?? "–"} / 9 · 非官方成绩 · 已评 ${roundStats.rubric.count} 题均值`,
                          en: `Mock score ${roundStats.rubric.mock_score ?? "–"} / 9 · unofficial · average of ${roundStats.rubric.count} rated items`,
                        })}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-2.5">
                      {(
                        [
                          [
                            t({ zh: "流利与连贯", en: "Fluency & coherence" }),
                            roundStats.rubric.fluency,
                          ],
                          [
                            t({ zh: "词汇运用", en: "Vocabulary" }),
                            roundStats.rubric.vocabulary,
                          ],
                          [
                            t({ zh: "语法表达", en: "Grammar" }),
                            roundStats.rubric.grammar,
                          ],
                          [
                            t({ zh: "任务完成", en: "Task" }),
                            roundStats.rubric.task,
                          ],
                        ] as const
                      ).map(([label, dim]) => (
                        <div
                          key={label}
                          className="grid grid-cols-[70px_1fr_30px] items-center gap-2.5 text-xs"
                        >
                          <span className="text-muted-foreground">{label}</span>
                          <div className="h-1.5 overflow-hidden rounded-full bg-background">
                            <div
                              className="h-full rounded-full bg-primary"
                              style={{ width: `${((dim ?? 0) / 4) * 100}%` }}
                            />
                          </div>
                          <span className="text-right tabular-nums">
                            {dim ?? "–"}/4
                          </span>
                        </div>
                      ))}
                    </CardContent>
                  </Card>
                )}
              </div>
            )}
          </>
        )}

        {doneItems.length === 0 && (
          <Card>
            <CardContent className="py-6 text-muted-foreground">
              {t({
                zh: "还没有完成的作答。回到练习页开始第一题。",
                en: "No completed attempts yet. Head back to practice and start the first item.",
              })}
            </CardContent>
          </Card>
        )}

        {doneItems.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                {t({
                  zh: "本轮参考分与练习计划",
                  en: "This round's reference scores and plan",
                })}
              </CardTitle>
              <CardDescription>
                {t({
                  zh: `已完成 ${doneItems.length} / ${plan.items.length} 题 · 参考分来自转写文本与语速规则，模型四维分单独统计。`,
                  en: `${doneItems.length} / ${plan.items.length} items done · reference scores come from transcript text and speaking-rate rules; model dimension scores are counted separately.`,
                })}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p>
                {t({
                  zh: `本轮平均参考分 ${roundStats.overall ?? "–"} / 100。复述完整度 ${roundStats.completeness ?? "–"} / 100，流利度参考 ${roundStats.fluency ?? "–"} / 100。`,
                  en: `Average reference score this round: ${roundStats.overall ?? "–"} / 100. Repeat completeness ${roundStats.completeness ?? "–"} / 100, fluency ${roundStats.fluency ?? "–"} / 100.`,
                })}
              </p>
              <p>
                {roundStats.completeness !== null &&
                roundStats.completeness < 80
                  ? t({
                      zh: "复述优先检查漏读的关键词，对照下面的原文和转写，分句听读后再完整复述。",
                      en: "For repeats, first check for missed keywords: compare the original text below with your transcript, listen and read sentence by sentence, then repeat in full.",
                    })
                  : t({
                      zh: "继续巩固完整表达，复述时注意意群衔接，避免只记住零散单词。",
                      en: "Keep strengthening complete expressions; mind how thought chunks connect when repeating, instead of memorizing scattered words.",
                    })}
              </p>
              <p>
                {roundStats.fluency !== null && roundStats.fluency < 60
                  ? t({
                      zh: "下一次先用短句表达完整意思，再逐步连成两到三句；录音回听检查停顿。",
                      en: "Next time, express a complete idea in short sentences first, then build up to two or three; replay your recording to check pauses.",
                    })
                  : t({
                      zh: "在保持表达节奏的基础上，为观点补充理由和具体例子，让回答更充分。",
                      en: "While keeping your pace, add reasons and concrete examples to your opinions for fuller answers.",
                    })}
              </p>
              <p>
                {t({
                  zh: "练习顺序：回听最需要改进的一题 → 对照逐题建议修改表达 → 重录并比较转写和参考分。",
                  en: "Practice order: replay the item that needs the most work → revise your wording with the per-item tips → re-record and compare transcripts and scores.",
                })}
              </p>
              <p className="text-xs text-muted-foreground">
                {t({
                  zh: "转写可能有误；仅凭文本不能准确判断发音、重音和语调。缺失或失败的评价不计入均值，以下保留各题依据。",
                  en: "Transcripts may contain errors; text alone cannot judge pronunciation, stress or intonation accurately. Missing or failed evaluations are excluded from averages; each item's basis is kept below.",
                })}
              </p>
            </CardContent>
          </Card>
        )}

        {doneItems.map(({ item, attempt }, index) => (
          <Card key={item.id}>
            <CardHeader>
              <CardDescription>
                {index + 1}.{" "}
                {t(
                  ITEM_TYPE_LABELS[item.type] ?? {
                    zh: item.type,
                    en: item.type,
                  },
                )}
              </CardDescription>
              <CardTitle className="text-sm leading-relaxed font-medium">
                {item.text}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm leading-relaxed">
                <span className="text-muted-foreground">
                  {t({ zh: "转写：", en: "Transcript:" })}
                </span>
                {attempt.transcript || t({ zh: "（无）", en: "(none)" })}
              </p>
              <Separator />
              <div className="flex items-center gap-4 text-sm">
                <span className="text-2xl font-bold tabular-nums">
                  {t({ zh: "参考分", en: "Score" })} {attempt.overall ?? "–"}
                </span>
                {item.type !== "question" && (
                  <span className="text-muted-foreground">
                    {t({ zh: "完整度", en: "Completeness" })}{" "}
                    {attempt.completeness ?? "–"} ·{" "}
                    {t({ zh: "流利度", en: "Fluency" })}{" "}
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
              {item.type === "question" && (
                <>
                  <RubricBlock
                    rubric={attempt.rubric}
                    engine=""
                    savedExpressionsKey={
                      student ? savedExpressionsKey(student) : undefined
                    }
                  />
                  <VocabBlock vocab={attempt.vocab} />
                </>
              )}
              {attempt.attempt_id && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setReplay({ item, attempt })}
                >
                  <Play />
                  {t({ zh: "回听这一题", en: "Replay this item" })}
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
                    {t(
                      ITEM_TYPE_LABELS[replay.item.type] ?? {
                        zh: replay.item.type,
                        en: replay.item.type,
                      },
                    )}{" "}
                    · {t({ zh: "回看这次表达", en: "Review this attempt" })}
                  </>
                )}
              </DialogTitle>
              <DialogDescription>{replay?.item.text}</DialogDescription>
            </DialogHeader>
            {replay && (
              <div className="space-y-3">
                <div>
                  <p className="mb-1 text-xs text-muted-foreground">
                    {t({
                      zh: "你说了什么（转写）",
                      en: "What you said (transcript)",
                    })}
                  </p>
                  <p className="rounded-lg bg-background p-3 text-sm leading-relaxed">
                    {replay.attempt.transcript ||
                      t({ zh: "（无转写）", en: "(no transcript)" })}
                  </p>
                </div>
                <div className="flex items-center gap-3 text-sm">
                  <span className="text-2xl font-bold tabular-nums">
                    {replay.attempt.overall ?? "–"}
                  </span>
                  <span className="text-muted-foreground">
                    {t({ zh: "参考分", en: "Reference Score" })}
                  </span>
                </div>
                {replay.attempt.attempt_id && (
                  <AttemptAudio
                    attemptId={replay.attempt.attempt_id}
                    preload="metadata"
                    className="w-full"
                  />
                )}
                <p className="text-xs text-muted-foreground">
                  {t({
                    zh: "听一听自己刚才的声音，找出下一句想说得更好的地方。",
                    en: "Listen to your own voice and find the next sentence you'd like to say better.",
                  })}
                </p>
              </div>
            )}
            <DialogFooter>
              <Button variant="outline" onClick={() => setReplay(null)}>
                {t({ zh: "关闭", en: "Close" })}
              </Button>
              <Button
                onClick={() => {
                  if (replay) {
                    void navigate({
                      to: "/p/$code",
                      params: { code },
                      search: {
                        focus: replay.item.id,
                        ...(sessionId ? { session: sessionId } : {}),
                      },
                    })
                  }
                }}
              >
                <Repeat />
                {t({ zh: "再练这一题", en: "Practice this item again" })}
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
                  search: {
                    focus: weakest,
                    ...(sessionId ? { session: sessionId } : {}),
                  },
                })
              }
            >
              <Repeat />
              {t({ zh: "重练最弱的一题", en: "Redo your weakest item" })}
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
              ? t({
                  zh: "这个主题的题已练完",
                  en: "All questions on this topic are done",
                })
              : t({
                  zh: "换同主题下一问",
                  en: "Next question on this topic",
                })}
          </Button>
          <Button variant="ghost" asChild>
            <Link
              to="/p/$code"
              params={{ code }}
              search={sessionId ? { session: sessionId } : {}}
            >
              {t({ zh: "回练习页", en: "Back to practice" })}
              <ArrowRight />
            </Link>
          </Button>
        </div>

        <p className="pb-6 text-center text-xs text-muted-foreground">
          {t({
            zh: "参考反馈，不是考试成绩。",
            en: "Reference feedback, not exam results.",
          })}
        </p>
      </div>
    </StudentShell>
  )
}
