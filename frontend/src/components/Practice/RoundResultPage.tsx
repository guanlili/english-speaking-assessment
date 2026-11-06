import { useMutation, useQuery } from "@tanstack/react-query"
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router"
import confetti from "canvas-confetti"
import { ArrowRight, Repeat, Shuffle } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import type { PlanAttempt, PlanItem } from "@/client"
import { ClassesService } from "@/client"
import { RoundItemCard } from "@/components/Practice/RoundResult/RoundItemCard"
import { RoundReplayDialog } from "@/components/Practice/RoundResult/RoundReplayDialog"
import { RoundStatsGrid } from "@/components/Practice/RoundResult/RoundStatsGrid"
import { SessionStarsCard } from "@/components/Practice/RoundResult/SessionStarsCard"
import StudentShell from "@/components/Practice/StudentShell"
import { TeacherFeedbackBlock } from "@/components/Practice/TeacherFeedbackBlock"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useExpressionFavorites } from "@/hooks/useExpressionFavorites"
import { displayName, loadStudent } from "@/lib/classroom-student"
import {
  manualSaveOutcome,
  readSavedExpressions,
  saveSavedExpressions,
} from "@/lib/favorites"
import { useI18n } from "@/lib/i18n"
import { pollWhileVisible } from "@/lib/poll"
import { extractErrorMessage } from "@/utils"

export function RoundResultPage() {
  const { t } = useI18n()
  const { code } = useParams({ strict: false }) as { code: string }
  const { explore: exploreSessionId, session: sessionParam } = useSearch({
    strict: false,
  })
  const navigate = useNavigate()
  const student = loadStudent(code)
  const expressions = useExpressionFavorites(code, student)
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
    refetchInterval: pollWhileVisible((query) =>
      query.state.data?.attempts.some(
        (a) =>
          a.status === "queued" ||
          a.status === "scoring" ||
          a.rubric?.status === "pending",
      )
        ? 2000
        : false,
    ),
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
  const isExam = Boolean(plan?.exam)
  const questionItems =
    plan?.items.filter((item) => item.type !== "instruction") ?? []
  const submittedCount = questionItems.filter((item) =>
    plan?.attempts.some((attempt) => attempt.item_id === item.id),
  ).length
  useEffect(() => {
    if (plan?.exam && !plan.exam.ended) {
      void navigate({
        to: "/exam/$code",
        params: { code },
        search: { session: plan.session_id },
      })
    }
  }, [plan, navigate, code])
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
    const scored = plan.items
      .filter((item) => item.type !== "instruction")
      .flatMap((item) => {
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

  // 本轮汇总（BELP 4 统计卡）
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

  // 收藏表达：从逐题卡片提到页面级，子组件只负责渲染
  const saveUpgrades = student
    ? async (texts: string[]) => {
        try {
          const stored = await expressions.add.mutateAsync(texts)
          const outcome = manualSaveOutcome(
            texts,
            stored.map((row) => row.text),
          )
          if (outcome.complete) {
            toast.success(
              t({
                zh: "已收藏到我的成长",
                en: "Saved to My Growth",
              }),
            )
            return true
          }
          const local = readSavedExpressions(student)
          const pending = [
            ...local,
            ...outcome.missing.filter(
              (text) => !local.some((item) => item.trim() === text),
            ),
          ]
          saveSavedExpressions(student, pending)
          toast.message(
            t({
              zh: `收藏最多 50 条，这次没存上：${outcome.missing.join("；")}`,
              en: `Favorites hold 50. Not saved this time: ${outcome.missing.join("; ")}`,
            }),
          )
          return false
        } catch (err) {
          toast.error(extractErrorMessage(err))
          return false
        }
      }
    : undefined

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
      <StudentShell active={isExam ? "exam" : "practice"}>
        <div className="flex flex-col gap-6" aria-busy="true">
          <div className="space-y-2">
            <Skeleton className="h-7 w-64" />
            <Skeleton className="h-4 w-72" />
          </div>
          <Skeleton className="h-32 w-full rounded-2xl" />
          <Skeleton className="h-64 w-full rounded-2xl" />
        </div>
      </StudentShell>
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
  if (plan.exam && !plan.exam.ended) {
    return (
      <div role="status">
        {t({
          zh: "考试进行中，正在返回试题…",
          en: "Exam in progress. Returning to your items…",
        })}
      </div>
    )
  }

  return (
    <StudentShell active={isExam ? "exam" : "practice"}>
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

        {isExam && (
          <p role="status" className="rounded-xl bg-secondary/60 p-4 text-sm">
            {t({
              zh: `考试已结束 · 已提交 ${submittedCount}/${questionItems.length} 题 · 未作答 ${Math.max(0, questionItems.length - submittedCount)} 题`,
              en: `Exam finished · ${submittedCount}/${questionItems.length} items submitted · ${Math.max(0, questionItems.length - submittedCount)} unanswered`,
            })}
            {plan.attempts.some(
              (a) => a.status === "queued" || a.status === "scoring",
            ) && (
              <span className="mt-1 block">
                {t({
                  zh: "录音正在评分，结果会自动更新",
                  en: "Recordings are being scored. Results will update automatically.",
                })}
              </span>
            )}
          </p>
        )}

        {gamification && gamification.session_stars !== null && (
          <SessionStarsCard gamification={gamification} newBadges={newBadges} />
        )}
        {doneItems.length > 0 && (
          <>
            <RoundStatsGrid roundStats={roundStats} />

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
                zh: isExam
                  ? "暂无已出分的作答。已提交的录音会在评分完成后显示，未作答的题保留为未作答。"
                  : "还没有完成的作答。回到练习页开始第一题。",
                en: isExam
                  ? "No scores are available yet. Submitted recordings appear after scoring; unanswered items remain unanswered."
                  : "No completed attempts yet. Head back to practice and start the first item.",
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
                  zh: `已完成 ${doneItems.length} / ${questionItems.length} 题 · 参考分来自转写文本与语速规则，模型四维分单独统计。`,
                  en: `${doneItems.length} / ${questionItems.length} items done · reference scores come from transcript text and speaking-rate rules; model dimension scores are counted separately.`,
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

        {plan.attempts
          .filter(
            (attempt) =>
              attempt.status !== "done" &&
              (attempt.teacher_feedback || attempt.teacher_focus),
          )
          .map((attempt) => (
            <div key={attempt.attempt_id} className="space-y-2">
              <p className="text-sm">
                {plan.items.find((item) => item.id === attempt.item_id)?.text}
              </p>
              <TeacherFeedbackBlock attempt={attempt} />
            </div>
          ))}
        {doneItems.map(({ item, attempt }, index) => (
          <RoundItemCard
            key={item.id}
            item={item}
            attempt={attempt}
            index={index}
            onSaveUpgrades={saveUpgrades}
            onReplay={() => setReplay({ item, attempt })}
          />
        ))}

        <RoundReplayDialog
          replay={replay}
          isExam={isExam}
          onClose={() => setReplay(null)}
          onPracticeAgain={(itemId) =>
            void navigate({
              to: "/p/$code",
              params: { code },
              search: {
                focus: itemId,
                ...(sessionId ? { session: sessionId } : {}),
              },
            })
          }
        />

        <div className="flex flex-wrap gap-3">
          {!isExam && weakest && (
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
          {!isExam && (
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
          )}
          <Button variant="ghost" asChild>
            <Link
              to={isExam ? "/home/$code" : "/p/$code"}
              params={{ code }}
              search={!isExam && sessionId ? { session: sessionId } : {}}
            >
              {t({
                zh: isExam ? "返回首页" : "回练习页",
                en: isExam ? "Back to home" : "Back to practice",
              })}
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
