import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Clock, LogOut, Swords, Trophy, UsersRound } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"

import { type PkMatchView, VocabularyService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { loadStudent } from "@/lib/classroom-student"
import { useI18n } from "@/lib/i18n"
import {
  parseSseBuffer,
  pkAnswerKey,
  pkLobbyPollInterval,
  pkNextItemIndex,
  pkOutcome,
  pkPhase,
  pkRemainingSeconds,
  pkShouldPolling,
} from "@/lib/pk"

const POLL_FALLBACK_MS = 1500

/**
 * 课堂 PK 竞技场：大厅状态 + 1v1 对局（学生侧）。
 *
 * 实时通道：SSE 优先；建连失败或断流超过 1.5 秒自动切轮询，两者读同一套
 * 快照接口（readPkMatchState）。PK 结果仅本局可见，不进入教师任务统计。
 * 教师开厅入口在教师端 `/t/$code/vocab` 的 PK Tab，不经本学生路由。
 */
export default function PkArena({ code }: { code: string }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const student = loadStudent(code)

  const lobbyKey = useMemo(() => ["vocab", code, "pk-lobby"] as const, [code])
  const lobbyQuery = useQuery({
    queryKey: lobbyKey,
    queryFn: () => VocabularyService.readPkLobby({ code: code.toUpperCase() }),
    staleTime: 5_000,
    // 配对由对方加入触发，大厅没有独立推送；排队期间短轮询兜底，配对到达即停。
    refetchInterval: (query) => pkLobbyPollInterval(query.state.data),
  })
  const lobby = lobbyQuery.data ?? null
  const matchId = lobby?.my_match_id ?? null

  const matchKey = useMemo(
    () => ["vocab", code, "pk-match", matchId] as const,
    [code, matchId],
  )
  // refs 必须先于 matchQuery 声明：refetchInterval 闭包在 observer 构造期即读取它们
  const sseAliveRef = useRef(false)
  const lastEventAtRef = useRef<number | null>(null)
  const [, forceTick] = useState(0)

  // 对局快照落地后才挂载面板（见下方 matchId && !match 的加载态与 MatchPanel 空态防护）；
  // 配对状态由大厅快照带出：join/leave 响应直接回填大厅缓存，排队期间短轮询覆盖对方触发的配对。
  const matchQuery = useQuery({
    queryKey: matchKey,
    queryFn: () =>
      VocabularyService.readPkMatchState({
        code: code.toUpperCase(),
        match_id: matchId ?? "",
      }),
    enabled: matchId !== null,
    refetchInterval: (query) => {
      const snapshot = query.state.data as PkMatchView | null
      if (snapshot?.status === "finished") return false
      return pkShouldPolling({
        sseOpen: sseAliveRef.current,
        lastEventAt: lastEventAtRef.current,
        now: Date.now(),
        fallbackAfterMs: POLL_FALLBACK_MS,
      })
        ? POLL_FALLBACK_MS
        : false
    },
  })
  const match = matchQuery.data ?? null

  // SSE 订阅：带 Authorization 头的 fetch 读取（EventSource 不能带头）；
  // 异常/断流由 refetchInterval 轮询兜底，不抛 500。
  useEffect(() => {
    if (!matchId) {
      sseAliveRef.current = false
      return
    }
    let cancelled = false
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null
    sseAliveRef.current = true
    lastEventAtRef.current = Date.now()

    const token = localStorage.getItem("access_token")
    const baseUrl = import.meta.env.VITE_API_URL ?? ""
    const url = `${baseUrl}/api/v1/classes/${code.toUpperCase()}/vocabulary/pk/matches/${matchId}/events`

    fetch(url, { headers: { Authorization: `Bearer ${token ?? ""}` } })
      .then(async (resp) => {
        if (!resp.ok || !resp.body) throw new Error("sse unavailable")
        reader = resp.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ""
        while (!cancelled) {
          const { value } = await reader.read()
          if (value) buffer += decoder.decode(value, { stream: true })
          const { events, rest } = parseSseBuffer(buffer)
          buffer = rest
          for (const event of events) {
            const dataLine = event
              .split("\n")
              .find((line) => line.startsWith("data:"))
            if (!dataLine) continue
            try {
              const snapshot = JSON.parse(
                dataLine.slice(5).trim(),
              ) as PkMatchView
              lastEventAtRef.current = Date.now()
              queryClient.setQueryData(matchKey, snapshot)
            } catch {
              // 事件块不完整：留待下次拼接
            }
          }
        }
      })
      .catch(() => {
        if (!cancelled) {
          sseAliveRef.current = false
          forceTick((n) => n + 1)
        }
      })

    return () => {
      cancelled = true
      sseAliveRef.current = false
      void reader?.cancel()
    }
  }, [code, matchId, matchKey, queryClient])

  const matchPrefixKey = useMemo(
    () => ["vocab", code, "pk-match"] as const,
    [code],
  )

  const joinMutation = useMutation({
    mutationFn: () =>
      VocabularyService.joinPkLobby({ code: code.toUpperCase() }),
    // 响应即最新大厅快照，直接回填缓存；失效键前缀与查询键对齐，避免漏失效。
    onSuccess: (data) => queryClient.setQueryData(lobbyKey, data),
    onError: () =>
      toast.error(
        t({
          zh: "加入 PK 失败，请稍后再试。",
          en: "Couldn't join PK. Try again later.",
        }),
      ),
  })

  const leaveMutation = useMutation({
    mutationFn: () =>
      VocabularyService.leavePkLobby({ code: code.toUpperCase() }),
    onSuccess: (data) => {
      queryClient.setQueryData(lobbyKey, data)
      void queryClient.invalidateQueries({ queryKey: matchPrefixKey })
    },
    onError: () =>
      toast.error(
        t({
          zh: "离开 PK 失败，请稍后再试。",
          en: "Couldn't leave PK. Try again later.",
        }),
      ),
  })

  const phase = pkPhase(lobby ?? {}, match)

  return (
    <div className="flex flex-col gap-6">
      <section className="rounded-3xl border border-primary/10 bg-secondary/40 p-6 sm:p-8">
        <p className="mb-2 flex items-center gap-2 text-[10px] font-semibold tracking-[0.2em] text-primary">
          <span className="h-px w-6 bg-primary/40" /> PK BATTLE
        </p>
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight sm:text-3xl">
          <Swords className="size-7" />
          {t({ zh: "课堂对战 PK", en: "Classroom PK" })}
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {t({
            zh: "本班自愿参与，两人配对 1v1；作答只记对战反馈，不影响老师任务成绩。",
            en: "Optional in-class 1v1 pairing. PK answers are battle feedback only — they never count toward teacher tasks.",
          })}
        </p>
        <div className="mt-3">
          <Link
            to="/vocab/$code/room"
            params={{ code }}
            className="text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            {t({
              zh: "老师开了大屏 PK？直接输入房间码加入 →",
              en: "Teacher running a big-screen PK? Enter the room code →",
            })}
          </Link>
        </div>
      </section>

      {phase !== "finished" && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <UsersRound className="size-5" />
              {t({ zh: "PK 大厅", en: "PK Lobby" })}
            </CardTitle>
            <CardDescription>
              {phase === "waiting"
                ? t({
                    zh: "已排队，等待对手配对…",
                    en: "Queued — waiting for an opponent…",
                  })
                : phase === "closed"
                  ? t({ zh: "当前大厅已关闭。", en: "The lobby is closed." })
                  : t({
                      zh: "加入后即进入排队，满 2 人自动配对。",
                      en: "Join to queue; two players are paired automatically.",
                    })}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-2">
            {lobby?.status !== "open" ? (
              <Badge variant="outline">
                {t({ zh: "未开放", en: "Not open" })}
              </Badge>
            ) : phase === "waiting" ? (
              <Button variant="outline" onClick={() => leaveMutation.mutate()}>
                <LogOut />
                {t({ zh: "离开排队", en: "Leave queue" })}
              </Button>
            ) : (
              <Button
                onClick={() => joinMutation.mutate()}
                disabled={joinMutation.isPending}
              >
                <Swords />
                {joinMutation.isPending
                  ? t({ zh: "加入中…", en: "Joining…" })
                  : t({ zh: "加入 PK", en: "Join PK" })}
              </Button>
            )}
            {typeof lobby?.queue_count === "number" && (
              <span className="text-xs text-muted-foreground">
                {t({
                  zh: `排队 ${lobby.queue_count} 人 · ${lobby.active_match_count ?? 0} 场进行中`,
                  en: `${lobby.queue_count} queued · ${lobby.active_match_count ?? 0} active`,
                })}
              </span>
            )}
          </CardContent>
        </Card>
      )}

      {matchId && !match && (
        <Card>
          <CardContent className="p-5 text-center text-sm text-muted-foreground">
            {t({ zh: "对局准备中…", en: "Starting match…" })}
          </CardContent>
        </Card>
      )}

      {match && (
        <MatchPanel
          code={code}
          match={match}
          myStudentId={student?.id ?? null}
        />
      )}
    </div>
  )
}

function MatchPanel({
  code,
  match,
  myStudentId,
}: {
  code: string
  match: PkMatchView
  myStudentId: string | null
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const lobbyKey = ["vocab", code, "pk-lobby"]
  const matchPrefixKey = ["vocab", code, "pk-match"]
  const items = match.items ?? []
  const nextIndex = pkNextItemIndex(items)
  const currentItem = items[nextIndex] ?? null
  const remaining = pkRemainingSeconds(match.remaining_seconds)
  const outcome = pkOutcome(match.result, myStudentId)
  const [draft, setDraft] = useState("")
  const attemptRef = useRef(0)

  const answerMutation = useMutation({
    mutationFn: (payload: {
      item_index: number
      prompt_type: string
      answer: string
    }) =>
      VocabularyService.submitPkAnswer({
        code: code.toUpperCase(),
        match_id: match.match_id,
        pkAnswerRequest: {
          ...payload,
          idempotency_key: pkAnswerKey(
            match.match_id,
            myStudentId,
            payload.item_index,
            attemptRef.current,
          ),
        },
      }),
    onSuccess: () => {
      attemptRef.current += 1
      setDraft("")
      void queryClient.invalidateQueries({ queryKey: lobbyKey })
      void queryClient.invalidateQueries({ queryKey: matchPrefixKey })
    },
    onError: () =>
      toast.error(
        t({
          zh: "作答提交失败，请重试。",
          en: "Answer didn't submit. Try again.",
        }),
      ),
  })

  const submitAnswer = (answer: string) => {
    if (!currentItem || answer.trim() === "" || answerMutation.isPending) return
    answerMutation.mutate({
      item_index: currentItem.item_index,
      prompt_type: currentItem.prompt_type,
      answer: answer.trim(),
    })
  }

  const isChoice =
    currentItem?.prompt_type === "en_zh" || currentItem?.prompt_type === "zh_en"

  const outcomeLabel = useMemo(() => {
    if (outcome === "win") return t({ zh: "你赢了！", en: "You win!" })
    if (outcome === "lose")
      return t({ zh: "惜败，再来一局", en: "Close one — rematch?" })
    if (outcome === "drew") return t({ zh: "平局", en: "Draw" })
    return null
  }, [outcome, t])

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Trophy className="size-5" />
            {t({ zh: "对战对局", en: "Match" })}
          </CardTitle>
          {match.status === "active" && (
            <Badge variant="outline" className="tabular-nums">
              <Clock className="size-3" />
              {t({ zh: `剩 ${remaining} 秒`, en: `${remaining}s left` })}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid grid-cols-2 gap-3">
          <ScoreCard
            name={match.me.display_name ?? t({ zh: "我", en: "Me" })}
            score={match.me.score ?? 0}
            answered={match.me.answered_count ?? 0}
            highlight
          />
          <ScoreCard
            name={
              match.opponent?.display_name ?? t({ zh: "对手", en: "Opponent" })
            }
            score={match.opponent?.score ?? 0}
            answered={match.opponent?.answered_count ?? 0}
          />
        </div>

        {match.status === "finished" ? (
          <div className="rounded-2xl bg-secondary/50 p-5 text-center">
            <p className="text-xl font-semibold">{outcomeLabel}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {t({
                zh: "本局结果仅本局可见。",
                en: "This result is visible to this match only.",
              })}
            </p>
          </div>
        ) : currentItem ? (
          <div className="space-y-4">
            <div>
              <p className="text-xs text-muted-foreground">
                {t({
                  zh: `第 ${nextIndex + 1} / ${match.question_count} 题`,
                  en: `Question ${nextIndex + 1} / ${match.question_count}`,
                })}
              </p>
              <p
                data-testid="pk-prompt"
                className="mt-1 text-lg leading-relaxed sm:text-xl"
              >
                {currentItem.prompt_type === "en_zh" && currentItem.headword
                  ? currentItem.headword
                  : currentItem.meaning_zh}
              </p>
              {currentItem.cloze_sentence && (
                <p className="mt-1 text-sm text-muted-foreground">
                  {currentItem.cloze_sentence}
                </p>
              )}
            </div>

            {isChoice ? (
              <ul className="grid gap-2 sm:grid-cols-2">
                {(currentItem.choices ?? []).map((choice, index) => (
                  <li key={choice.word_id}>
                    <button
                      type="button"
                      disabled={answerMutation.isPending}
                      onClick={() => submitAnswer(choice.word_id)}
                      className="min-h-14 w-full rounded-2xl border border-input bg-card px-4 py-3 text-left text-base transition-colors hover:border-primary/50 disabled:opacity-70"
                    >
                      <span className="mr-2 text-xs text-muted-foreground">
                        {String.fromCharCode(65 + index)}.
                      </span>
                      {currentItem.prompt_type === "en_zh"
                        ? choice.meaning_zh
                        : choice.headword}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="flex flex-wrap gap-2">
                <input
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") submitAnswer(draft)
                  }}
                  placeholder={t({ zh: "输入拼写…", en: "Type the spelling…" })}
                  className="min-h-11 flex-1 rounded-xl border bg-card px-3 text-base"
                  autoComplete="off"
                  autoCapitalize="off"
                  spellCheck={false}
                />
                <Button
                  onClick={() => submitAnswer(draft)}
                  disabled={answerMutation.isPending || draft.trim() === ""}
                >
                  {t({ zh: "提交", en: "Submit" })}
                </Button>
              </div>
            )}
          </div>
        ) : (
          <div className="rounded-2xl bg-secondary/50 p-5 text-center text-sm text-muted-foreground">
            {t({ zh: "对局加载中…", en: "Loading match…" })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function ScoreCard({
  name,
  score,
  answered,
  highlight = false,
}: {
  name: string
  score: number
  answered: number
  highlight?: boolean
}) {
  const { t } = useI18n()
  return (
    <div
      className={`rounded-2xl border p-4 ${highlight ? "border-primary/30 bg-primary/5" : "bg-secondary/40"}`}
    >
      <p className="truncate text-sm text-muted-foreground">{name}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{score}</p>
      <p className="text-xs text-muted-foreground">
        {t({ zh: `已答 ${answered} 题`, en: `${answered} answered` })}
      </p>
    </div>
  )
}
