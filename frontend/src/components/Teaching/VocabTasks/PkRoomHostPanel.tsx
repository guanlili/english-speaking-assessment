import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  CheckCircle2,
  Crown,
  MonitorPlay,
  Play,
  Square,
  Trophy,
  UsersRound,
} from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { type PkRoomHostView, VocabularyService } from "@/client"
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

const POLL_INTERVAL_MS = 1500
const DEFAULT_QUESTION_COUNT = 10
const DEFAULT_PER_QUESTION_SECONDS = 20
const MIN_QUESTION_COUNT = 1
const MAX_QUESTION_COUNT = 20
const MIN_PER_QUESTION_SECONDS = 1
const MAX_PER_QUESTION_SECONDS = 60
const DEFAULT_TEAM_COUNT = 4
const MIN_TEAM_COUNT = 2
const MAX_TEAM_COUNT = 6

function clampInt(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min
  return Math.min(max, Math.max(min, Math.round(value)))
}

function RoomCountdown({
  seconds,
  status,
}: {
  seconds: number
  status: string
}) {
  const { t } = useI18n()
  const [left, setLeft] = useState(seconds)

  useEffect(() => {
    setLeft(seconds)
  }, [seconds])

  useEffect(() => {
    if (status !== "live") return
    const timer = window.setInterval(() => {
      setLeft((current) => (current > 0 ? current - 1 : 0))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [status])

  return (
    <div className="flex items-baseline gap-2">
      <span className="text-5xl font-semibold tabular-nums">{left}</span>
      <span className="text-sm text-muted-foreground">
        {t({ zh: "秒", en: "sec" })}
      </span>
    </div>
  )
}

type NormalizedHostView = PkRoomHostView & {
  questions: NonNullable<PkRoomHostView["questions"]>
  players: NonNullable<PkRoomHostView["players"]>
  teams: NonNullable<PkRoomHostView["teams"]>
  current_item_index: number
  question_count: number
  per_question_seconds: number
  remaining_seconds: number
  participant_count: number
  current_correct_count: number
  current_answered_count: number
  current_accuracy: number | null
  current_item: NonNullable<PkRoomHostView["current_item"]> | null
  result:
    | (NonNullable<PkRoomHostView["result"]> & {
        teams: NonNullable<NonNullable<PkRoomHostView["result"]>["teams"]>
        players: NonNullable<NonNullable<PkRoomHostView["result"]>["players"]>
        questions: NonNullable<
          NonNullable<PkRoomHostView["result"]>["questions"]
        >
        wrong_words: NonNullable<
          NonNullable<PkRoomHostView["result"]>["wrong_words"]
        >
      })
    | null
}

/** 后端字段多数带默认值，生成类型为可选；这里一次补齐，渲染层按确定值用。 */
function normalizeHostView(raw: PkRoomHostView): NormalizedHostView {
  return {
    ...raw,
    questions: raw.questions ?? [],
    players: raw.players ?? [],
    teams: raw.teams ?? [],
    current_item_index: raw.current_item_index ?? 0,
    question_count: raw.question_count ?? 0,
    per_question_seconds: raw.per_question_seconds ?? 0,
    remaining_seconds: raw.remaining_seconds ?? 0,
    participant_count: raw.participant_count ?? 0,
    current_correct_count: raw.current_correct_count ?? 0,
    current_answered_count: raw.current_answered_count ?? 0,
    current_accuracy: raw.current_accuracy ?? null,
    current_item: raw.current_item ?? null,
    result: raw.result
      ? {
          ...raw.result,
          teams: raw.result.teams ?? [],
          players: raw.result.players ?? [],
          questions: raw.result.questions ?? [],
          wrong_words: raw.result.wrong_words ?? [],
        }
      : null,
  }
}

function accuracyText(value: number | null | undefined): string {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "—"
}

/**
 * 教师端「课堂大屏 PK」面板：开房（6 位码）/ 开赛 / 大屏实时看板 / 结算。
 *
 * 只轮询主持端 board 快照（1.5 秒），不做 SSE：当前题、倒计时、正确率与
 * 队伍积分都由服务端时钟推导，断线重连刷新即恢复。作答不回流任务统计。
 */
export function PkRoomHostPanel({ code }: { code: string }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const roomQuery = useQuery({
    queryKey: ["vocab", code, "pk-room"],
    queryFn: () =>
      VocabularyService.readCurrentPkRoom({ code: code.toUpperCase() }),
    refetchInterval: (query) =>
      query.state.data?.status === "live" ? POLL_INTERVAL_MS : 3000,
  })
  const room: NormalizedHostView | null = roomQuery.data
    ? normalizeHostView(roomQuery.data)
    : null

  const booksQuery = useQuery({
    queryKey: ["vocab", code, "pk-books"],
    queryFn: () => VocabularyService.listBooks(),
    staleTime: 30_000,
  })
  const books = (booksQuery.data ?? []).filter(
    (book) => book.status === "active",
  )

  const [bookId, setBookId] = useState("")
  const [mode, setMode] = useState<"solo" | "team">("solo")
  const [teamCount, setTeamCount] = useState(DEFAULT_TEAM_COUNT)
  const [questionCount, setQuestionCount] = useState(DEFAULT_QUESTION_COUNT)
  const [perQuestionSeconds, setPerQuestionSeconds] = useState(
    DEFAULT_PER_QUESTION_SECONDS,
  )

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: ["vocab", code, "pk-room"] })

  const createMutation = useMutation({
    mutationFn: () =>
      VocabularyService.createPkRoom({
        code: code.toUpperCase(),
        pkRoomCreate: {
          book_id: bookId,
          mode,
          team_count:
            mode === "team"
              ? clampInt(teamCount, MIN_TEAM_COUNT, MAX_TEAM_COUNT)
              : null,
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
    onSuccess: invalidate,
    onError: () =>
      toast.error(
        t({
          zh: "开房失败，检查词库与题量后重试。",
          en: "Couldn't open the room. Check the book and question count.",
        }),
      ),
  })

  const startMutation = useMutation({
    mutationFn: (roomId: string) =>
      VocabularyService.startPkRoom({
        code: code.toUpperCase(),
        room_id: roomId,
      }),
    onSuccess: invalidate,
    onError: () =>
      toast.error(
        t({ zh: "开始失败，请稍后再试。", en: "Couldn't start the round." }),
      ),
  })

  const endMutation = useMutation({
    mutationFn: (roomId: string) =>
      VocabularyService.endPkRoom({
        code: code.toUpperCase(),
        room_id: roomId,
      }),
    onSuccess: invalidate,
    onError: () =>
      toast.error(
        t({ zh: "结束失败，请稍后再试。", en: "Couldn't end the round." }),
      ),
  })

  if (roomQuery.isLoading) {
    return (
      <div className="text-sm text-muted-foreground">
        {t({ zh: "加载中…", en: "Loading…" })}
      </div>
    )
  }

  // ── 未开房：开房表单 ──────────────────────────────────────────────
  if (!room) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <MonitorPlay className="size-5" />
            {t({ zh: "课堂大屏 PK：开房", en: "Class PK: open a room" })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: "开房后生成 6 位房间码，学生凭码入场，全班同题序同倒计时。",
              en: "Opening a room generates a 6-digit code. Students join with it and answer the same questions on one clock.",
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <label className="flex min-w-0 flex-col gap-1.5 text-sm sm:col-span-2">
            <span className="text-xs text-muted-foreground">
              {t({ zh: "词库", en: "Word book" })}
            </span>
            <select
              value={bookId}
              onChange={(event) => setBookId(event.target.value)}
              className="min-h-11 w-full rounded-xl border bg-card px-3 text-base"
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
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="text-xs text-muted-foreground">
              {t({ zh: "赛制", en: "Mode" })}
            </span>
            <select
              value={mode}
              onChange={(event) =>
                setMode(event.target.value === "team" ? "team" : "solo")
              }
              className="min-h-11 w-full rounded-xl border bg-card px-3 text-base"
            >
              <option value="solo">
                {t({ zh: "全班个人计分", en: "Whole class, individual" })}
              </option>
              <option value="team">
                {t({ zh: "小组阵营计分", en: "Team battle" })}
              </option>
            </select>
          </label>
          {mode === "team" ? (
            <div className="flex flex-col gap-1.5 text-sm">
              <span className="text-xs text-muted-foreground">
                {t({
                  zh: `小组数（${MIN_TEAM_COUNT}–${MAX_TEAM_COUNT}）`,
                  en: `Teams (${MIN_TEAM_COUNT}–${MAX_TEAM_COUNT})`,
                })}
              </span>
              <NumberInput
                value={teamCount}
                min={MIN_TEAM_COUNT}
                max={MAX_TEAM_COUNT}
                onValueChange={setTeamCount}
              />
            </div>
          ) : null}
          <div className="flex flex-col gap-1.5 text-sm">
            <span className="text-xs text-muted-foreground">
              {t({
                zh: `题量（1–${MAX_QUESTION_COUNT}）`,
                en: `Questions (1–${MAX_QUESTION_COUNT})`,
              })}
            </span>
            <NumberInput
              value={questionCount}
              min={1}
              max={MAX_QUESTION_COUNT}
              onValueChange={setQuestionCount}
            />
          </div>
          <div className="flex flex-col gap-1.5 text-sm">
            <span className="text-xs text-muted-foreground">
              {t({
                zh: `单题限时（${MIN_PER_QUESTION_SECONDS}–${MAX_PER_QUESTION_SECONDS}s）`,
                en: `Seconds per question (${MIN_PER_QUESTION_SECONDS}–${MAX_PER_QUESTION_SECONDS})`,
              })}
            </span>
            <NumberInput
              value={perQuestionSeconds}
              min={MIN_PER_QUESTION_SECONDS}
              max={MAX_PER_QUESTION_SECONDS}
              onValueChange={setPerQuestionSeconds}
            />
          </div>
          <div className="flex items-end sm:col-span-2 lg:col-span-1">
            <Button
              className="min-h-11 w-full"
              disabled={!bookId || createMutation.isPending}
              onClick={() => createMutation.mutate()}
            >
              {t({ zh: "生成房间码", en: "Create room code" })}
            </Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  const modeLabel =
    room.mode === "team"
      ? t({
          zh: `小组赛（${room.team_count} 组）`,
          en: `Teams (${room.team_count})`,
        })
      : t({ zh: "全班个人", en: "Individual" })

  // ── 等待：房间码 + 名单 ──────────────────────────────────────────
  if (room.status === "waiting") {
    return (
      <Card>
        <CardHeader className="text-center">
          <CardTitle className="text-base">
            {t({
              zh: "学生输入房间码入场",
              en: "Students join with this code",
            })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: `${modeLabel} · ${room.question_count} 题 · 每题 ${room.per_question_seconds} 秒`,
              en: `${modeLabel} · ${room.question_count} questions · ${room.per_question_seconds}s each`,
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="text-center">
            <div className="text-6xl font-semibold tracking-[0.3em] tabular-nums">
              {room.room_code}
            </div>
            <div className="mt-2 text-sm text-muted-foreground">
              {t({
                zh: `已入场 ${room.participant_count} 人`,
                en: `${room.participant_count} joined`,
              })}
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-center gap-2">
            <Badge variant="secondary">
              <UsersRound className="mr-1 size-3.5" />
              {room.participant_count}
            </Badge>
            {room.teams.map((team) => (
              <Badge key={team.team_index} variant="outline">
                {team.label} · {team.member_count}
              </Badge>
            ))}
          </div>
          <div className="flex justify-center gap-2">
            <Button
              className="min-h-11 px-6"
              disabled={startMutation.isPending || room.participant_count === 0}
              onClick={() => startMutation.mutate(room.room_id)}
            >
              <Play className="mr-1 size-4" />
              {t({ zh: "开始", en: "Start" })}
            </Button>
            <Button
              variant="outline"
              className="min-h-11"
              disabled={endMutation.isPending}
              onClick={() => endMutation.mutate(room.room_id)}
            >
              <Square className="mr-1 size-4" />
              {t({ zh: "取消", en: "Cancel" })}
            </Button>
          </div>
          {room.players.length ? (
            <div className="flex flex-wrap justify-center gap-1.5">
              {room.players.map((player) => (
                <span
                  key={player.student_id}
                  className="rounded-full border bg-card px-3 py-1 text-sm"
                >
                  {player.display_name ?? "—"}
                  {player.team_index
                    ? ` · ${t({ zh: "第", en: "T" })}${player.team_index}`
                    : ""}
                </span>
              ))}
            </div>
          ) : (
            <p className="text-center text-sm text-muted-foreground">
              {t({ zh: "还没有学生入场。", en: "No one has joined yet." })}
            </p>
          )}
        </CardContent>
      </Card>
    )
  }

  // ── 进行中 / 已结束：大屏看板 ───────────────────────────────────
  const questions = room.questions.slice(
    Math.max(0, room.current_item_index - 2),
    room.current_item_index + 1,
  )

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <MonitorPlay className="size-5" />
              {t({ zh: "大屏看板", en: "Big-screen board" })}
            </CardTitle>
            <CardDescription>
              {t({
                zh: `房间码 ${room.room_code} · ${modeLabel} · ${room.participant_count} 人`,
                en: `Code ${room.room_code} · ${modeLabel} · ${room.participant_count} players`,
              })}
            </CardDescription>
          </div>
          {room.status === "live" ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => endMutation.mutate(room.room_id)}
            >
              <Square className="mr-1 size-4" />
              {t({ zh: "结束", en: "End" })}
            </Button>
          ) : (
            <Badge variant="secondary">
              {t({ zh: "已结束", en: "Ended" })}
            </Badge>
          )}
        </CardHeader>
        <CardContent className="grid gap-6 lg:grid-cols-[280px_1fr]">
          <div className="space-y-3 text-center lg:text-left">
            {room.status === "live" ? (
              <div className="text-xs uppercase tracking-wide text-muted-foreground">
                {t({
                  zh: `第 ${room.current_item_index + 1} / ${room.question_count} 题`,
                  en: `Question ${room.current_item_index + 1} / ${room.question_count}`,
                })}
              </div>
            ) : (
              <div className="text-xs uppercase tracking-wide text-muted-foreground">
                {t({ zh: "全部作答完毕", en: "All questions done" })}
              </div>
            )}
            <RoomCountdown
              seconds={room.remaining_seconds}
              status={room.status}
            />
            {room.current_item ? (
              <div className="space-y-2">
                <div className="text-sm text-muted-foreground">
                  {t({ zh: "释义", en: "Meaning" })}：
                  {room.current_item.meaning_zh ?? "—"}
                </div>
                {room.current_item.headword ? (
                  <div className="text-2xl font-semibold">
                    {room.current_item.headword}
                  </div>
                ) : null}
                <div className="text-sm">
                  {t({
                    zh: `本题答对 ${room.current_correct_count} / ${room.current_answered_count} 人（${accuracyText(room.current_accuracy)}）`,
                    en: `${room.current_correct_count}/${room.current_answered_count} correct (${accuracyText(room.current_accuracy)})`,
                  })}
                </div>
              </div>
            ) : null}
            {room.status === "live" ? (
              <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-emerald-500 transition-all"
                  style={{
                    width: `${Math.round((room.current_accuracy ?? 0) * 100)}%`,
                  }}
                />
              </div>
            ) : null}

            {room.status === "ended" && room.result ? (
              <div className="space-y-2 text-left">
                <div className="flex items-center gap-1.5 text-sm font-medium">
                  <Trophy className="size-4" />
                  {t({ zh: "结算", en: "Result" })}
                </div>
                {room.result.teams.length ? (
                  room.result.teams.map((team) => (
                    <div
                      key={team.team_index}
                      className="flex justify-between text-sm"
                    >
                      <span>
                        #{team.rank} {team.label}
                      </span>
                      <span className="tabular-nums">{team.score}</span>
                    </div>
                  ))
                ) : (
                  <div className="text-xs text-muted-foreground">
                    {t({
                      zh: "个人计分，见右侧排名",
                      en: "Individual scores on the right",
                    })}
                  </div>
                )}
                {room.result.wrong_words.length ? (
                  <div className="text-xs text-muted-foreground">
                    {t({ zh: "易错词：", en: "Tricky words: " })}
                    {room.result.wrong_words.join("、")}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="space-y-3">
            <div className="flex items-center justify-between text-sm text-muted-foreground">
              <span>
                {t({
                  zh: "排名（同分比总用时）",
                  en: "Ranking (tie: shorter time wins)",
                })}
              </span>
              <span>{t({ zh: "已答", en: "Answered" })} ✓</span>
            </div>
            <div className="space-y-1">
              {(room.result?.players ?? room.players)
                .slice(0, 10)
                .map((player) => (
                  <div
                    key={player.student_id}
                    className="flex items-center justify-between rounded-lg border bg-card px-3 py-2 text-sm"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="w-5 text-right text-xs text-muted-foreground tabular-nums">
                        {player.rank}
                      </span>
                      {player.rank === 1 ? (
                        <Crown className="size-3.5 text-amber-500" />
                      ) : null}
                      <span className="truncate">
                        {player.display_name ?? "—"}
                      </span>
                      {player.team_index ? (
                        <Badge variant="outline" className="text-[10px]">
                          {t({ zh: "第", en: "T" })}
                          {player.team_index}
                        </Badge>
                      ) : null}
                    </span>
                    <span className="flex items-center gap-2">
                      {player.answered_current ? (
                        <CheckCircle2 className="size-3.5 text-emerald-500" />
                      ) : null}
                      <span className="tabular-nums">{player.score}</span>
                    </span>
                  </div>
                ))}
            </div>

            {room.teams.length ? (
              <div className="grid gap-2 sm:grid-cols-2">
                {room.teams.map((team) => (
                  <div
                    key={team.team_index}
                    className="rounded-lg border bg-card p-3 text-sm"
                  >
                    <div className="flex justify-between">
                      <span className="font-medium">{team.label}</span>
                      <span className="tabular-nums font-semibold">
                        {team.score}
                      </span>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {t({
                        zh: `${team.member_count} 人 · 答对 ${team.correct_count}`,
                        en: `${team.member_count} members · ${team.correct_count} correct`,
                      })}
                    </div>
                  </div>
                ))}
              </div>
            ) : null}

            <div className="space-y-1">
              {questions.map((question) => (
                <div
                  key={question.item_index}
                  className="flex justify-between text-xs text-muted-foreground"
                >
                  <span>
                    {t({ zh: "第", en: "Q" })}
                    {question.item_index + 1}
                    {question.headword ? ` · ${question.headword}` : ""}
                  </span>
                  <span className="tabular-nums">
                    {question.answered_count
                      ? `${question.correct_count}/${question.answered_count} (${accuracyText(question.accuracy)})`
                      : "—"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
