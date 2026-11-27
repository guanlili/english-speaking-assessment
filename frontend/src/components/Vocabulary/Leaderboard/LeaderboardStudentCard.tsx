import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { ArrowRight, Trophy } from "lucide-react"

import { VocabularyService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { EntryName } from "@/components/Vocabulary/Leaderboard/EntryName"
import { useParticipation } from "@/components/Vocabulary/Leaderboard/useParticipation"
import { useI18n } from "@/lib/i18n"
import { studentBoardVisible } from "@/lib/leaderboard"

/**
 * 学生词汇首页的班内学习榜卡。
 *
 * 展示条件（后端口径 + 前端兜底）：readLeaderboard 200 且 `settings.enabled`
 * 且 `audience="students"`。403 `leaderboard_unavailable`（整班关闭 / 仅教师可见）
 * 或其他错误一律静默隐藏：不弹错、不显示空卡。
 *
 * 未参加：只给加入入口，不显示参与人数；已参加：本周前 3 + 自己的名次/分数，
 * 榜外也显示自己；完整榜单走详情页。
 */
export function LeaderboardStudentCard({ code }: { code: string }) {
  const { t } = useI18n()
  const participation = useParticipation(code)

  const boardQuery = useQuery({
    queryKey: ["vocab", code, "leaderboard"],
    queryFn: () =>
      VocabularyService.readLeaderboard({ code: code.toUpperCase() }),
    retry: false,
    staleTime: 30_000,
  })

  // 加载中 / 出错（含不可见 403）都不渲染卡片，避免首页出现空卡或报错 toast
  if (boardQuery.isPending || boardQuery.isError) return null
  const view = boardQuery.data
  if (!studentBoardVisible(view)) return null

  const joined = view.joined === true
  const anonymous = view.settings.anonymous
  const entries = view.entries ?? []
  const topEntries = entries.slice(0, 3)
  const myRank = view.my_rank ?? null
  const myScore = view.my_score ?? 0

  return (
    <section
      aria-label={t({ zh: "班内学习榜", en: "Class Learning Board" })}
      className="rounded-3xl border bg-card p-5 sm:p-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
            <Trophy className="size-5" />
          </span>
          <div className="min-w-0">
            <p className="flex flex-wrap items-center gap-2 text-base font-semibold">
              {t({ zh: "班内学习榜", en: "Class Learning Board" })}
              <Badge variant="outline" className="text-[10px] font-normal">
                {t({ zh: "自愿参加", en: "Optional" })}
              </Badge>
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {t({
                zh: "按本周掌握词数排行，不含 XP、农场与 PK。",
                en: "Ranked by words mastered this week; XP, farm and PK are excluded.",
              })}
            </p>
          </div>
        </div>
      </div>

      {!joined ? (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-secondary/50 p-4">
          <p className="min-w-0 flex-1 text-sm text-muted-foreground">
            {t({
              zh: "自愿参加；未参加不显示任何人，也看不到人数。",
              en: "Optional to join. Until you join, nobody is shown to you and you can't see the headcount.",
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
        <div className="mt-4 space-y-3">
          {topEntries.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t({
                zh: "本周还没有人完成复习。",
                en: "Nobody has completed a review this week yet.",
              })}
            </p>
          ) : (
            <ul className="grid gap-2">
              {topEntries.map((entry) => (
                <li
                  key={entry.alias_no}
                  className="flex items-center gap-3 rounded-2xl border px-4 py-2.5"
                >
                  <span className="w-8 shrink-0 text-sm font-semibold tabular-nums text-muted-foreground">
                    {t({ zh: `第 ${entry.rank} 名`, en: `#${entry.rank}` })}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-sm">
                    <EntryName entry={entry} anonymous={anonymous} />
                  </span>
                  <span className="shrink-0 text-sm font-semibold tabular-nums">
                    {t({
                      zh: `${entry.score} 词`,
                      en: `${entry.score} words`,
                    })}
                  </span>
                </li>
              ))}
            </ul>
          )}

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-2xl bg-secondary/50 px-4 py-3 text-sm">
            <span className="font-semibold">
              {t({ zh: "我的名次", en: "My rank" })}
            </span>
            <span className="tabular-nums">
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

          <Button asChild variant="outline" size="sm" className="ml-auto">
            <Link to="/vocab/$code/leaderboard" params={{ code }}>
              {t({ zh: "查看完整榜单", en: "Full board" })}
              <ArrowRight />
            </Link>
          </Button>
        </div>
      )}
    </section>
  )
}
