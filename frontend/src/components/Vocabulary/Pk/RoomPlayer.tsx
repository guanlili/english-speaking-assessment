import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Clock, LogIn, Trophy, UsersRound } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"

import { ApiError, type PkRoomStudentView, VocabularyService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useI18n } from "@/lib/i18n"

const POLL_LIVE_MS = 1000
const POLL_IDLE_MS = 3000

function storageKey(code: string) {
  return `pk-room:${code.toUpperCase()}`
}

function readStoredRoom(code: string): string {
  try {
    return window.localStorage.getItem(storageKey(code)) ?? ""
  } catch {
    return ""
  }
}

function storeRoom(code: string, roomId: string) {
  try {
    if (roomId) window.localStorage.setItem(storageKey(code), roomId)
    else window.localStorage.removeItem(storageKey(code))
  } catch {
    // 本地存储不可用时只影响刷新后找回房间，不影响作答
  }
}

type NormalizedStudentView = PkRoomStudentView & {
  current_item_index: number
  question_count: number
  remaining_seconds: number
  participants: number
  teams: NonNullable<PkRoomStudentView["teams"]>
  item: NonNullable<PkRoomStudentView["item"]> | null
  me: NonNullable<PkRoomStudentView["me"]> | null
  result:
    | (NonNullable<PkRoomStudentView["result"]> & {
        teams: NonNullable<NonNullable<PkRoomStudentView["result"]>["teams"]>
        players: NonNullable<
          NonNullable<PkRoomStudentView["result"]>["players"]
        >
        questions: NonNullable<
          NonNullable<PkRoomStudentView["result"]>["questions"]
        >
        wrong_words: NonNullable<
          NonNullable<PkRoomStudentView["result"]>["wrong_words"]
        >
      })
    | null
}

function normalizeStudentView(raw: PkRoomStudentView): NormalizedStudentView {
  const item = raw.item ?? null
  return {
    ...raw,
    current_item_index: raw.current_item_index ?? 0,
    question_count: raw.question_count ?? 0,
    remaining_seconds: raw.remaining_seconds ?? 0,
    participants: raw.participants ?? 0,
    teams: raw.teams ?? [],
    item: item
      ? {
          ...item,
          item_index: item.item_index ?? 0,
          prompt_type: item.prompt_type ?? "meaning",
          meaning_zh: item.meaning_zh ?? "",
          choices: item.choices ?? [],
          morph_segments: item.morph_segments ?? [],
        }
      : null,
    me: raw.me ?? null,
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

function useCountdown(seconds: number, active: boolean) {
  const [left, setLeft] = useState(seconds)
  useEffect(() => setLeft(seconds), [seconds])
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(
      () => setLeft((current) => (current > 0 ? current - 1 : 0)),
      1000,
    )
    return () => window.clearInterval(timer)
  }, [active])
  return left
}

/**
 * 学生端「凭房间码入场」：输入 6 位码 → 等待开赛 → 当前题作答 → 结算。
 *
 * 1 秒轮询 me 快照，服务端时钟为准；房间状态与剩余秒数不靠本地推算。
 * 房间作答只用于课堂互动，不进任务完成率。
 */
export default function RoomPlayer({ code }: { code: string }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const [roomId, setRoomId] = useState(() => readStoredRoom(code))
  const [codeInput, setCodeInput] = useState("")
  const [draft, setDraft] = useState("")

  const meQuery = useQuery({
    queryKey: ["vocab", code, "pk-room-me", roomId],
    queryFn: () =>
      VocabularyService.readPkRoomAsStudent({
        code: code.toUpperCase(),
        room_id: roomId,
      }),
    enabled: roomId !== "",
    retry: false,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === "live") return POLL_LIVE_MS
      if (status === "waiting") return POLL_IDLE_MS
      return false
    },
  })
  const view: NormalizedStudentView | null = meQuery.data
    ? normalizeStudentView(meQuery.data)
    : null

  // 房间被老师结束/失效（404）时清掉本地记忆，回到输码页
  useEffect(() => {
    if (meQuery.error instanceof ApiError && meQuery.error.status === 404) {
      storeRoom(code, "")
      setRoomId("")
    }
  }, [meQuery.error, code])

  const joinMutation = useMutation({
    mutationFn: (roomCode: string) =>
      VocabularyService.joinPkRoom({
        code: code.toUpperCase(),
        pkRoomJoin: { code: roomCode },
      }),
    onSuccess: (data) => {
      storeRoom(code, data.room_id)
      setRoomId(data.room_id)
      setCodeInput("")
      void queryClient.invalidateQueries({
        queryKey: ["vocab", code, "pk-room-me", data.room_id],
      })
    },
    onError: (error) => {
      const status = error instanceof ApiError ? error.status : 0
      toast.error(
        status === 404
          ? t({
              zh: "房间码不正确，或不是本班房间。",
              en: "Wrong code, or not this class's room.",
            })
          : status === 409
            ? t({
                zh: "这轮已经结束或已满员。",
                en: "This round has ended or is full.",
              })
            : t({
                zh: "入场失败，请稍后重试。",
                en: "Couldn't join. Try again.",
              }),
      )
    },
  })

  const answerMutation = useMutation({
    mutationFn: (payload: {
      itemIndex: number
      promptType: string
      answer: string
    }) =>
      VocabularyService.answerPkRoom({
        code: code.toUpperCase(),
        room_id: roomId,
        pkRoomAnswerRequest: {
          item_index: payload.itemIndex,
          prompt_type: payload.promptType,
          answer: payload.answer,
        },
      }),
    onSuccess: (result) => {
      setDraft("")
      toast.success(
        result.is_correct
          ? t({
              zh: `答对了 +${result.score} 分`,
              en: `Correct +${result.score}`,
            })
          : t({
              zh: "这题没答对，等下一题。",
              en: "Not this one — next question.",
            }),
      )
      void queryClient.invalidateQueries({
        queryKey: ["vocab", code, "pk-room-me", roomId],
      })
    },
    onError: (error) => {
      const status = error instanceof ApiError ? error.status : 0
      if (status === 409) {
        toast.error(
          t({
            zh: "这题已翻页，等下一题。",
            en: "Question moved on. Wait for the next one.",
          }),
        )
        void queryClient.invalidateQueries({
          queryKey: ["vocab", code, "pk-room-me", roomId],
        })
      } else {
        toast.error(
          t({ zh: "提交失败，请重试。", en: "Submit failed. Try again." }),
        )
      }
    },
  })

  const item = view?.item ?? null
  const remaining = useCountdown(
    view?.remaining_seconds ?? 0,
    view?.status === "live",
  )
  const isChoice = useMemo(
    () => (item?.choices?.length ?? 0) > 0,
    [item?.choices],
  )

  if (!roomId) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <LogIn className="size-5" />
            {t({ zh: "输入房间码加入课堂 PK", en: "Join with your room code" })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: "老师会在教室大屏上给出 6 位房间码。",
              en: "Your teacher shows a 6-digit code on the classroom screen.",
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <input
            value={codeInput}
            onChange={(event) =>
              setCodeInput(event.target.value.replace(/\D/g, "").slice(0, 6))
            }
            onKeyDown={(event) => {
              if (event.key === "Enter" && codeInput.length === 6) {
                joinMutation.mutate(codeInput)
              }
            }}
            inputMode="numeric"
            placeholder="000000"
            className="min-h-12 w-40 rounded-xl border bg-card px-3 text-center text-lg tracking-[0.3em] tabular-nums"
            autoComplete="off"
          />
          <Button
            className="min-h-12"
            disabled={codeInput.length !== 6 || joinMutation.isPending}
            onClick={() => joinMutation.mutate(codeInput)}
          >
            {t({ zh: "加入", en: "Join" })}
          </Button>
        </CardContent>
      </Card>
    )
  }

  if (!view) {
    return (
      <Card>
        <CardContent className="p-6 text-sm text-muted-foreground">
          {t({ zh: "正在找回房间…", en: "Restoring your room…" })}
        </CardContent>
      </Card>
    )
  }

  if (view.status === "waiting") {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <UsersRound className="size-5" />
            {t({
              zh: "已入场，等老师开始",
              en: "You're in — waiting for the start",
            })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: `房间 ${view.room_code} · 已有 ${view.participants} 人`,
              en: `Room ${view.room_code} · ${view.participants} joined`,
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          {view.mode === "team" && view.me?.team_index
            ? t({
                zh: `你的队伍：第 ${view.me.team_index} 组`,
                en: `Your team: ${view.me.team_index}`,
              })
            : t({
                zh: "全班同场，按个人计分。",
                en: "Whole class, individual scoring.",
              })}
        </CardContent>
      </Card>
    )
  }

  if (view.status === "ended") {
    const players = view.result?.players ?? []
    const mine = players.find(
      (player) => player.student_id === view.me?.student_id,
    )
    return (
      <Card>
        <CardHeader className="text-center">
          <CardTitle className="flex items-center justify-center gap-2 text-base">
            <Trophy className="size-5" />
            {t({ zh: "本轮结束", en: "Round over" })}
          </CardTitle>
          <CardDescription>
            {mine?.rank
              ? t({
                  zh: `你排第 ${mine.rank} 名，${mine.score} 分`,
                  en: `You ranked #${mine.rank} with ${mine.score} points`,
                })
              : t({ zh: "本轮到这就结束了。", en: "That's the round." })}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {view.result?.teams?.length
            ? view.result.teams.map((team) => (
                <div
                  key={team.team_index}
                  className="flex justify-between rounded-lg border bg-card px-3 py-2 text-sm"
                >
                  <span>
                    #{team.rank} {team.label}
                  </span>
                  <span className="tabular-nums font-semibold">
                    {team.score}
                  </span>
                </div>
              ))
            : players.slice(0, 5).map((player) => (
                <div
                  key={player.student_id}
                  className="flex justify-between rounded-lg border bg-card px-3 py-2 text-sm"
                >
                  <span>
                    {player.rank}. {player.display_name ?? "—"}
                  </span>
                  <span className="tabular-nums">{player.score}</span>
                </div>
              ))}
          <Button
            variant="outline"
            className="min-h-11 w-full"
            onClick={() => {
              storeRoom(code, "")
              setRoomId("")
            }}
          >
            {t({ zh: "换房间码", en: "Enter another code" })}
          </Button>
        </CardContent>
      </Card>
    )
  }

  const answered = item?.answered ?? false

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-base">
              {t({
                zh: `第 ${view.current_item_index + 1} / ${view.question_count} 题`,
                en: `Question ${view.current_item_index + 1} / ${view.question_count}`,
              })}
            </CardTitle>
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="tabular-nums">
                <Clock className="size-3" />
                {remaining}s
              </Badge>
              <Badge variant="secondary" className="tabular-nums">
                {view.me?.score ?? 0} {t({ zh: "分", en: "pts" })}
              </Badge>
              {view.me?.rank ? (
                <Badge variant="outline" className="tabular-nums">
                  #{view.me.rank}
                </Badge>
              ) : null}
            </div>
          </div>
          {view.mode === "team" && view.teams.length ? (
            <CardDescription className="flex flex-wrap gap-2">
              {view.teams.map((team) => (
                <span key={team.team_index} className="tabular-nums">
                  {team.label} {team.score}
                </span>
              ))}
            </CardDescription>
          ) : null}
        </CardHeader>
        <CardContent className="space-y-4">
          {item ? (
            <>
              <div className="rounded-2xl bg-secondary/50 p-5">
                {item.prompt_type === "en_zh" && item.headword ? (
                  <p className="font-serif text-2xl font-semibold tracking-wide">
                    {item.headword}
                  </p>
                ) : (
                  <p className="text-lg">{item.meaning_zh}</p>
                )}
                {item.cloze_sentence ? (
                  <p className="mt-2 text-sm text-muted-foreground">
                    {item.cloze_sentence}
                  </p>
                ) : null}
                {item.prompt_type === "letters" && item.headword ? (
                  <p className="mt-2 text-sm text-muted-foreground">
                    {t({
                      zh: "按字母拼回这个单词。",
                      en: "Spell the word from its letters.",
                    })}
                  </p>
                ) : null}
              </div>

              {answered ? (
                <div className="rounded-2xl border bg-card p-4 text-sm">
                  {item.is_correct
                    ? t({
                        zh: `答对了，+${item.score} 分`,
                        en: `Correct, +${item.score}`,
                      })
                    : t({ zh: "这题没答对。", en: "Not this one." })}
                  {item.headword ? (
                    <span className="ml-2 font-semibold">{item.headword}</span>
                  ) : null}
                </div>
              ) : isChoice ? (
                <ul className="grid gap-2 sm:grid-cols-2">
                  {(item.choices ?? []).map((choice, index) => (
                    <li key={String(choice.word_id)}>
                      <button
                        type="button"
                        disabled={answerMutation.isPending}
                        onClick={() =>
                          answerMutation.mutate({
                            itemIndex: item.item_index,
                            promptType: item.prompt_type,
                            answer: String(choice.word_id),
                          })
                        }
                        className="min-h-14 w-full rounded-2xl border border-input bg-card px-4 py-3 text-left text-base transition-colors hover:border-primary/50 disabled:opacity-70"
                      >
                        <span className="mr-2 text-xs text-muted-foreground">
                          {String.fromCharCode(65 + index)}.
                        </span>
                        {item.prompt_type === "en_zh"
                          ? String(choice.meaning_zh ?? "")
                          : String(choice.headword ?? "")}
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
                      if (event.key === "Enter" && draft.trim()) {
                        answerMutation.mutate({
                          itemIndex: item.item_index,
                          promptType: item.prompt_type,
                          answer: draft.trim(),
                        })
                      }
                    }}
                    placeholder={t({
                      zh: "输入拼写…",
                      en: "Type the spelling…",
                    })}
                    className="min-h-11 flex-1 rounded-xl border bg-card px-3 text-base"
                    autoComplete="off"
                    autoCapitalize="off"
                    spellCheck={false}
                  />
                  <Button
                    className="min-h-11"
                    disabled={answerMutation.isPending || draft.trim() === ""}
                    onClick={() =>
                      answerMutation.mutate({
                        itemIndex: item.item_index,
                        promptType: item.prompt_type,
                        answer: draft.trim(),
                      })
                    }
                  >
                    {t({ zh: "提交", en: "Submit" })}
                  </Button>
                </div>
              )}
            </>
          ) : (
            <div className="text-sm text-muted-foreground">
              {t({ zh: "正在同步题目…", en: "Syncing the question…" })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
