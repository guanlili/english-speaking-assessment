import { useQuery } from "@tanstack/react-query"
import { ChevronLeft, ChevronRight, RotateCcw, Trophy } from "lucide-react"
import { useEffect, useState } from "react"

import { VocabularyService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { EntryName } from "@/components/Vocabulary/Leaderboard/EntryName"
import { useParticipation } from "@/components/Vocabulary/Leaderboard/useParticipation"
import { useI18n } from "@/lib/i18n"
import {
  canGoNextWeek,
  isLeaderboardUnavailable,
  nextWeekStart,
  previousWeekStart,
} from "@/lib/leaderboard"
import { formatDate } from "@/lib/time"

const STUDENT_TOP_N = 10

/**
 * 学生班内学习榜详情页（`/vocab/$code/leaderboard`）。
 *
 * - 默认本周；上一周 / 下一周切换，下一周不超过首次响应拿到的本周
 *   （上界用后端回传的 `week_start` 锁定，不用浏览器时区自行推断）。
 * - 未参加：只显示加入说明与按钮，不显示任何人与人数。
 * - 已参加：前 10 + 自己的名次；自己已在前 10 不重复，榜外单独突出。
 * - 整班关闭 / 仅教师可见（`leaderboard_unavailable`）与空榜都给双语空状态。
 */
export function LeaderboardStudentPanel({ code }: { code: string }) {
  const { t, lang } = useI18n()
  const participation = useParticipation(code)

  // null = 本周（不带 week_start 参数）；boundary 锁定首次响应的本周一
  const [weekStart, setWeekStart] = useState<string | null>(null)
  const [boundaryWeek, setBoundaryWeek] = useState<string | null>(null)

  const boardQuery = useQuery({
    queryKey: ["vocab", code, "leaderboard", "student", weekStart],
    queryFn: () =>
      VocabularyService.readLeaderboard({
        code: code.toUpperCase(),
        week_start: weekStart,
      }),
    retry: false,
  })

  const view = boardQuery.data ?? null
  useEffect(() => {
    if (!view) return
    setBoundaryWeek((prev) => prev ?? view.week_start)
  }, [view])

  if (boardQuery.isPending) {
    return (
      <div role="status" className="space-y-4">
        <span className="sr-only">
          {t({ zh: "正在加载学习榜…", en: "Loading the class board…" })}
        </span>
        <div className="h-40 rounded-2xl border bg-card" />
      </div>
    )
  }

  if (boardQuery.isError) {
    const unavailable = isLeaderboardUnavailable(boardQuery.error)
    return (
      <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3 rounded-3xl border bg-card px-6 py-12 text-center">
        <Trophy className="size-10 text-muted-foreground" />
        <p className="text-lg font-semibold">
          {unavailable
            ? t({ zh: "榜单暂未开放", en: "The board is not available" })
            : t({
                zh: "学习榜暂时没有加载成功",
                en: "Couldn't load the board",
              })}
        </p>
        <p className="max-w-md text-sm text-muted-foreground">
          {unavailable
            ? t({
                zh: "老师关闭了榜单，或当前仅教师可见。开放后这里会自动出现。",
                en: "Your teacher turned the board off, or it is teacher-only right now. It will appear here once opened.",
              })
            : t({
                zh: "请检查网络连接，再试一次。",
                en: "Check your connection and try again.",
              })}
        </p>
        {!unavailable && (
          <Button
            variant="outline"
            onClick={() => void boardQuery.refetch()}
            disabled={boardQuery.isFetching}
          >
            <RotateCcw />
            {t({ zh: "重新加载", en: "Reload" })}
          </Button>
        )}
      </div>
    )
  }

  if (!view) return null

  const joined = view.joined === true
  const anonymous = view.settings.anonymous
  const entries = (view.entries ?? []).slice(0, STUDENT_TOP_N)
  const myEntry = view.my_entry ?? null
  const myRank = view.my_rank ?? null
  const myScore = view.my_score ?? 0
  const selfInEntries =
    myEntry !== null &&
    entries.some((entry) => entry.alias_no === myEntry.alias_no)
  const currentWeek = weekStart ?? view.week_start

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
            {t({ zh: "班内学习榜", en: "Class Learning Board" })}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t({
              zh: "本周掌握词数 = 该词首次作答正确且本周通过一次复习；不含 XP / 农场 / PK。",
              en: "Words mastered this week = first-try correct and reviewed once this week. XP, farm and PK are excluded.",
            })}
          </p>
        </div>
        {joined && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => participation.mutate(false)}
            disabled={participation.isPending}
          >
            {participation.isPending
              ? t({ zh: "退出中…", en: "Leaving…" })
              : t({ zh: "退出榜单", en: "Leave the board" })}
          </Button>
        )}
      </header>

      {!joined ? (
        <div className="flex flex-col items-center gap-3 rounded-3xl border bg-card px-6 py-12 text-center">
          <Trophy className="size-10 text-muted-foreground" />
          <p className="text-lg font-semibold">
            {t({
              zh: "你还没有加入学习榜",
              en: "You haven't joined the board yet",
            })}
          </p>
          <p className="max-w-md text-sm text-muted-foreground">
            {t({
              zh: "自愿参加；未参加不显示任何人，也看不到人数。加入后按本周掌握词数排行。",
              en: "Optional to join. Until you join, nobody is shown to you and you can't see the headcount. After joining, you rank by words mastered this week.",
            })}
          </p>
          <Button
            onClick={() => participation.mutate(true)}
            disabled={participation.isPending}
          >
            {participation.isPending
              ? t({ zh: "加入中…", en: "Joining…" })
              : t({ zh: "加入榜单", en: "Join the board" })}
          </Button>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                aria-label={t({ zh: "上一周", en: "Previous week" })}
                onClick={() => setWeekStart(previousWeekStart(currentWeek))}
                disabled={boardQuery.isFetching}
              >
                <ChevronLeft />
              </Button>
              <span className="min-w-32 text-center text-sm tabular-nums text-muted-foreground">
                {formatDate(view.week_start, lang)}
                {boundaryWeek !== null && view.week_start === boundaryWeek && (
                  <span className="ml-2">
                    {t({ zh: "本周", en: "This week" })}
                  </span>
                )}
              </span>
              <Button
                variant="outline"
                size="sm"
                aria-label={t({ zh: "下一周", en: "Next week" })}
                onClick={() => setWeekStart(nextWeekStart(currentWeek))}
                disabled={
                  !canGoNextWeek(currentWeek, boundaryWeek) ||
                  boardQuery.isFetching
                }
              >
                <ChevronRight />
              </Button>
            </div>
          </div>

          {entries.length === 0 ? (
            <div className="space-y-3">
              <div className="rounded-3xl border bg-card px-6 py-12 text-center text-sm text-muted-foreground">
                {t({
                  zh: "本周还没有人完成复习。",
                  en: "Nobody has completed a review this week yet.",
                })}
              </div>
              {!selfInEntries && (
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-2xl bg-primary/5 px-4 py-3 text-sm">
                  <span className="font-semibold">
                    {t({ zh: "我", en: "Me" })}
                  </span>
                  <span className="tabular-nums text-muted-foreground">
                    {myRank !== null
                      ? t({ zh: `第 ${myRank} 名`, en: `#${myRank}` })
                      : t({ zh: "榜外", en: "Off the board" })}
                  </span>
                  <span className="text-muted-foreground">
                    {t({
                      zh: `本周掌握 ${myScore} 词`,
                      en: `${myScore} words mastered this week`,
                    })}
                  </span>
                </div>
              )}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-20">
                    {t({ zh: "名次", en: "Rank" })}
                  </TableHead>
                  <TableHead>{t({ zh: "同学", en: "Student" })}</TableHead>
                  <TableHead className="text-right">
                    {t({ zh: "本周掌握词数", en: "Words mastered" })}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {entries.map((entry) => (
                  <TableRow key={entry.alias_no}>
                    <TableCell className="tabular-nums text-muted-foreground">
                      {t({ zh: `第 ${entry.rank} 名`, en: `#${entry.rank}` })}
                    </TableCell>
                    <TableCell>
                      <EntryName entry={entry} anonymous={anonymous} />
                    </TableCell>
                    <TableCell className="text-right font-semibold tabular-nums">
                      {entry.score}
                    </TableCell>
                  </TableRow>
                ))}
                {!selfInEntries && (
                  <TableRow className="border-primary/30 bg-primary/5">
                    <TableCell className="tabular-nums text-muted-foreground">
                      {myRank !== null
                        ? t({ zh: `第 ${myRank} 名`, en: `#${myRank}` })
                        : t({ zh: "榜外", en: "Off the board" })}
                    </TableCell>
                    <TableCell className="font-semibold">
                      {t({ zh: "我", en: "Me" })}
                    </TableCell>
                    <TableCell className="text-right font-semibold tabular-nums">
                      {myScore}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          )}
        </>
      )}
    </div>
  )
}

export default LeaderboardStudentPanel
