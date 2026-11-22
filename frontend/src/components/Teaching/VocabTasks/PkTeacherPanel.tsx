import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Swords, Trophy, UsersRound } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { VocabularyService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { NumberInput } from "@/components/ui/number-input"
import { useI18n } from "@/lib/i18n"
import { pkActiveMatches, pkWaitingPlayers } from "@/lib/pk"

const POLL_INTERVAL_MS = 1500
const DEFAULT_QUESTION_COUNT = 8
const DEFAULT_PER_QUESTION_SECONDS = 20
const MIN_QUESTION_COUNT = 1
const MAX_QUESTION_COUNT = 20
const MIN_PER_QUESTION_SECONDS = 1
const MAX_PER_QUESTION_SECONDS = 60

function clampInt(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min
  return Math.min(max, Math.max(min, Math.round(value)))
}

/**
 * 教师端 PK 大厅面板（挂在 `/t/$code/vocab` 词汇 Tab）。
 *
 * 教师不在对局名单内、订阅对局 SSE 会 403，因此本面板只走大厅快照轮询；
 * 等待名单与进行中对局/比分均由 `readPkLobby` 的 players 摘要派生。
 * 教师不经过学生路由 `/vocab/$code/pk`。
 */
export function PkTeacherPanel({ code }: { code: string }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const lobbyQuery = useQuery({
    queryKey: ["vocab", code, "pk-lobby"],
    queryFn: () => VocabularyService.readPkLobby({ code: code.toUpperCase() }),
    refetchInterval: (query) =>
      query.state.data?.status === "open" ? POLL_INTERVAL_MS : false,
  })
  const lobby = lobbyQuery.data ?? null
  const open = lobby?.status === "open"

  const booksQuery = useQuery({
    queryKey: ["vocab", code, "pk-books"],
    queryFn: () => VocabularyService.listBooks(),
    staleTime: 30_000,
  })
  const books = (booksQuery.data ?? []).filter(
    (book) => book.status === "active",
  )

  const [bookId, setBookId] = useState("")
  const [questionCount, setQuestionCount] = useState(DEFAULT_QUESTION_COUNT)
  const [perQuestionSeconds, setPerQuestionSeconds] = useState(
    DEFAULT_PER_QUESTION_SECONDS,
  )

  // 大厅开启后用快照回填配置（展示用；开启期间表单锁定，不能改参数）
  useEffect(() => {
    if (!open) return
    if (lobby?.book_id) setBookId(lobby.book_id)
    if (typeof lobby.question_count === "number") {
      setQuestionCount(lobby.question_count)
    }
    if (typeof lobby.per_question_seconds === "number") {
      setPerQuestionSeconds(lobby.per_question_seconds)
    }
  }, [open, lobby?.book_id, lobby?.question_count, lobby?.per_question_seconds])

  const openMutation = useMutation({
    mutationFn: () =>
      VocabularyService.openPkLobby({
        code: code.toUpperCase(),
        pkLobbyCreate: {
          book_id: bookId,
          question_count: clampInt(
            questionCount,
            MIN_QUESTION_COUNT,
            MAX_QUESTION_COUNT,
          ),
          per_question_seconds: clampInt(
            perQuestionSeconds,
            MIN_PER_QUESTION_SECONDS,
            MAX_PER_QUESTION_SECONDS,
          ),
        },
      }),
    onSuccess: () =>
      void queryClient.invalidateQueries({
        queryKey: ["vocab", code, "pk-lobby"],
      }),
    onError: () =>
      toast.error(
        t({
          zh: "开启大厅失败，检查词库与题量后重试。",
          en: "Couldn't open the lobby. Check the book and question count.",
        }),
      ),
  })

  const closeMutation = useMutation({
    mutationFn: () =>
      VocabularyService.closePkLobby({ code: code.toUpperCase() }),
    onSuccess: () =>
      void queryClient.invalidateQueries({
        queryKey: ["vocab", code, "pk-lobby"],
      }),
    onError: () =>
      toast.error(
        t({
          zh: "关闭大厅失败，请稍后再试。",
          en: "Couldn't close the lobby. Try again later.",
        }),
      ),
  })

  const waiting = pkWaitingPlayers(lobby?.players)
  const matches = pkActiveMatches(lobby?.players)
  const queueCount = lobby?.queue_count ?? waiting.length
  const activeMatchCount = lobby?.active_match_count ?? matches.length

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Swords className="size-5" />
            {t({ zh: "教师：PK 大厅", en: "Teacher: PK lobby" })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: "选词库、题量与单题限时；大厅仅本班学生可见，教师不进入对局。",
              en: "Pick a book, question count and per-question time. Visible to this class only; teachers do not join matches.",
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-3">
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="text-xs text-muted-foreground">
              {t({ zh: "词库", en: "Word book" })}
            </span>
            <select
              value={bookId}
              disabled={open}
              onChange={(event) => setBookId(event.target.value)}
              className="min-h-11 rounded-xl border bg-card px-3 text-base disabled:opacity-50"
            >
              <option value="">
                {t({ zh: "请选择词库", en: "Select a book" })}
              </option>
              {books.map((book) => (
                <option key={book.id} value={book.id}>
                  {book.title}
                </option>
              ))}
            </select>
          </label>
          <label
            htmlFor="pk-question-count"
            className="flex flex-col gap-1.5 text-sm"
          >
            <span className="text-xs text-muted-foreground">
              {t({
                zh: `题量（${MIN_QUESTION_COUNT}–${MAX_QUESTION_COUNT}）`,
                en: `Questions (${MIN_QUESTION_COUNT}–${MAX_QUESTION_COUNT})`,
              })}
            </span>
            <NumberInput
              id="pk-question-count"
              value={questionCount}
              min={MIN_QUESTION_COUNT}
              max={MAX_QUESTION_COUNT}
              disabled={open}
              onValueChange={setQuestionCount}
            />
          </label>
          <label
            htmlFor="pk-per-question-seconds"
            className="flex flex-col gap-1.5 text-sm"
          >
            <span className="text-xs text-muted-foreground">
              {t({
                zh: `单题限时（秒，${MIN_PER_QUESTION_SECONDS}–${MAX_PER_QUESTION_SECONDS}）`,
                en: `Seconds per question (${MIN_PER_QUESTION_SECONDS}–${MAX_PER_QUESTION_SECONDS})`,
              })}
            </span>
            <NumberInput
              id="pk-per-question-seconds"
              value={perQuestionSeconds}
              min={MIN_PER_QUESTION_SECONDS}
              max={MAX_PER_QUESTION_SECONDS}
              disabled={open}
              onValueChange={setPerQuestionSeconds}
            />
          </label>
          <div className="flex flex-wrap items-center gap-2 sm:col-span-3">
            {open ? (
              <Button
                variant="outline"
                onClick={() => closeMutation.mutate()}
                disabled={closeMutation.isPending}
              >
                {t({ zh: "关闭大厅", en: "Close lobby" })}
              </Button>
            ) : (
              <Button
                onClick={() => openMutation.mutate()}
                disabled={openMutation.isPending || !bookId}
              >
                {openMutation.isPending
                  ? t({ zh: "开启中…", en: "Opening…" })
                  : t({ zh: "开启大厅", en: "Open lobby" })}
              </Button>
            )}
            <Badge variant={open ? "secondary" : "outline"}>
              {open
                ? t({ zh: "开放中", en: "Open" })
                : t({ zh: "未开放", en: "Not open" })}
            </Badge>
            <span className="text-xs text-muted-foreground">
              {t({
                zh: `排队 ${queueCount} 人 · ${activeMatchCount} 场进行中`,
                en: `${queueCount} queued · ${activeMatchCount} active`,
              })}
            </span>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <UsersRound className="size-5" />
              {t({ zh: "等待玩家", en: "Waiting players" })}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {waiting.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {open
                  ? t({
                      zh: "暂无学生排队，等待学生从词汇页加入。",
                      en: "No students queued yet. Students join from the vocabulary page.",
                    })
                  : t({ zh: "大厅未开放。", en: "The lobby is closed." })}
              </p>
            ) : (
              <ul className="flex flex-wrap gap-2">
                {waiting.map((player) => (
                  <li
                    key={player.student_id}
                    className="rounded-full border bg-secondary/40 px-3 py-1.5 text-sm"
                  >
                    {player.display_name ?? player.student_id}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Trophy className="size-5" />
              {t({ zh: "进行中对局", en: "Active matches" })}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {matches.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t({
                  zh: "暂无进行中的对局。",
                  en: "No active matches yet.",
                })}
              </p>
            ) : (
              matches.map((match, index) => (
                <div key={match.matchId} className="space-y-2">
                  <p className="text-xs text-muted-foreground">
                    {t({
                      zh: `对局 ${index + 1}`,
                      en: `Match ${index + 1}`,
                    })}
                  </p>
                  <div className="grid grid-cols-2 gap-3">
                    {match.players.map((player) => (
                      <ScoreCard
                        key={player.student_id}
                        name={player.display_name ?? player.student_id}
                        score={player.score ?? 0}
                        answered={player.answered_count ?? 0}
                        correct={player.correct_count ?? 0}
                      />
                    ))}
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function ScoreCard({
  name,
  score,
  answered,
  correct,
}: {
  name: string
  score: number
  answered: number
  correct: number
}) {
  const { t } = useI18n()
  return (
    <div className="rounded-2xl border bg-secondary/40 p-4">
      <p className="truncate text-sm text-muted-foreground">{name}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{score}</p>
      <p className="text-xs text-muted-foreground">
        {t({
          zh: `已答 ${answered} 题 · 对 ${correct}`,
          en: `${answered} answered · ${correct} correct`,
        })}
      </p>
    </div>
  )
}
