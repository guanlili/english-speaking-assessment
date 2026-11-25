import { useQuery } from "@tanstack/react-query"
import { Leaf, RotateCcw, Sprout, Trophy, UsersRound } from "lucide-react"

import { ApiError, VocabularyService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  badgeText,
  farmBadgeTotal,
  sortFarmBadges,
  topFarmHarvesters,
} from "@/lib/farm"
import { useI18n } from "@/lib/i18n"
import { formatNullableCount } from "@/lib/utils"

const TOP_HARVESTER_LIMIT = 5

/**
 * 教师端「专注农场」只读概览（挂在 `/t/$code/vocab` 词汇 Tab）。
 *
 * 只读取班级聚合：参与地块、成熟地块、累计收获、徽章分布与收获榜；
 * 不提供种植、收获、改分等写操作，也不自行聚合学生端地块数据。
 */
export function FarmTeacherPanel({ code }: { code: string }) {
  const { t } = useI18n()

  const summaryQuery = useQuery({
    queryKey: ["vocab", code, "teacher-farm-summary"],
    queryFn: () =>
      VocabularyService.readTeacherFarmSummary({
        code: code.toUpperCase(),
      }),
    retry: false,
  })
  const errorStatus =
    summaryQuery.error instanceof ApiError ? summaryQuery.error.status : 0
  const summary = summaryQuery.data ?? null

  const badges = sortFarmBadges(summary?.badge_counts)
  const harvesters = topFarmHarvesters(
    summary?.top_harvesters,
    TOP_HARVESTER_LIMIT,
  )
  const badgeTotal = farmBadgeTotal(summary?.badge_counts)
  const isEmpty =
    summary === null ||
    (summary.participants == null &&
      summary.mature_plots == null &&
      summary.harvested_total == null &&
      badges.length === 0 &&
      harvesters.length === 0)

  const metrics = [
    {
      label: t({ zh: "参与地块", en: "Participants" }),
      value: formatNullableCount(summary?.participants),
      icon: UsersRound,
    },
    {
      label: t({ zh: "成熟地块", en: "Mature plots" }),
      value: formatNullableCount(summary?.mature_plots),
      icon: Leaf,
    },
    {
      label: t({ zh: "累计收获", en: "Harvests" }),
      value: formatNullableCount(summary?.harvested_total),
      icon: Sprout,
    },
    {
      label: t({ zh: "徽章总数", en: "Badges" }),
      value: formatNullableCount(badgeTotal),
      icon: Trophy,
    },
  ]

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2 text-base">
            <Sprout className="size-5" />
            {t({ zh: "专注农场概览", en: "Focus Farm overview" })}
            <Badge variant="secondary">
              {t({ zh: "只读概览", en: "Read-only overview" })}
            </Badge>
          </CardTitle>
          <CardDescription>
            {t({
              zh: "按在册学生汇总地块参与、成熟与收获，以及徽章分布；不改动 XP、徽章与地块。",
              en: "Aggregated from enrolled students' plots, harvests and badges. XP, badges and plots are never changed here.",
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className="min-h-11"
              onClick={() => void summaryQuery.refetch()}
              disabled={summaryQuery.isFetching}
            >
              <RotateCcw />
              {t({ zh: "刷新", en: "Refresh" })}
            </Button>
          </div>

          {summaryQuery.isPending ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Skeleton className="h-24 rounded-2xl" />
              <Skeleton className="h-24 rounded-2xl" />
              <Skeleton className="h-24 rounded-2xl" />
              <Skeleton className="h-24 rounded-2xl" />
            </div>
          ) : errorStatus === 403 ? (
            <FarmError
              title={t({
                zh: "你还不是这个课堂的授权教师，请让管理员在后台把你绑到这间课堂。",
                en: "You are not an owner teacher of this classroom yet. Ask an admin to link you to it in the admin console.",
              })}
              onRetry={() => void summaryQuery.refetch()}
              retrying={summaryQuery.isFetching}
            />
          ) : summaryQuery.isError ? (
            <FarmError
              title={
                errorStatus === 404
                  ? t({
                      zh: "课堂不存在或已被移除。",
                      en: "The classroom does not exist or has been removed.",
                    })
                  : t({
                      zh: "农场概览暂时没有加载成功，请检查网络后重试。",
                      en: "The farm overview failed to load. Check your network and retry.",
                    })
              }
              onRetry={() => void summaryQuery.refetch()}
              retrying={summaryQuery.isFetching}
            />
          ) : isEmpty ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              {t({
                zh: "暂无农场数据，学生完成练习后会在这里汇总。",
                en: "No farm data yet. It appears once students finish practice.",
              })}
            </p>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {metrics.map(({ label, value, icon: Icon }) => (
                  <div
                    key={label}
                    className="flex min-w-0 flex-col rounded-2xl border border-border/80 bg-card p-4 sm:p-5"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-xs font-medium leading-5 text-muted-foreground">
                        {label}
                      </p>
                      <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-secondary text-primary">
                        <Icon aria-hidden="true" className="size-4" />
                      </span>
                    </div>
                    <p className="mt-2 text-3xl font-semibold tracking-tight tabular-nums">
                      {value}
                    </p>
                  </div>
                ))}
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <div className="rounded-2xl border bg-secondary/30 p-4 sm:p-5">
                  <p className="mb-3 text-sm font-semibold">
                    {t({ zh: "徽章分布", en: "Badge distribution" })}
                  </p>
                  {badges.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      {t({
                        zh: "暂无徽章记录。",
                        en: "No badges recorded yet.",
                      })}
                    </p>
                  ) : (
                    <ul className="space-y-2">
                      {badges.map((badge) => (
                        <li
                          key={badge.key}
                          className="flex items-center justify-between gap-3 text-sm"
                        >
                          <span className="min-w-0 truncate">
                            {t(badgeText(badge).label)}
                          </span>
                          <span className="shrink-0 tabular-nums text-muted-foreground">
                            {formatNullableCount(badge.count)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="rounded-2xl border bg-secondary/30 p-4 sm:p-5">
                  <p className="mb-3 text-sm font-semibold">
                    {t({ zh: "收获榜", en: "Top harvesters" })}
                  </p>
                  {harvesters.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      {t({
                        zh: "还没有学生收获过作物。",
                        en: "Nobody has harvested crops yet.",
                      })}
                    </p>
                  ) : (
                    <ol className="space-y-2">
                      {harvesters.map((harvester, index) => (
                        <li
                          key={`${harvester.display_name}-${index}`}
                          className="flex items-center justify-between gap-3 text-sm"
                        >
                          <span className="flex min-w-0 items-center gap-2">
                            <span className="w-6 shrink-0 tabular-nums text-muted-foreground">
                              {index + 1}
                            </span>
                            <span className="min-w-0 truncate">
                              {harvester.display_name}
                            </span>
                          </span>
                          <span className="shrink-0 tabular-nums text-muted-foreground">
                            {t({
                              zh: `收获 ${formatNullableCount(harvester.harvest_count)} 次`,
                              en: `${formatNullableCount(harvester.harvest_count)} harvests`,
                            })}
                          </span>
                        </li>
                      ))}
                    </ol>
                  )}
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function FarmError({
  title,
  onRetry,
  retrying,
}: {
  title: string
  onRetry: () => void
  retrying: boolean
}) {
  const { t } = useI18n()
  return (
    <div className="flex min-h-[32vh] flex-col items-center justify-center gap-3 text-muted-foreground">
      <p className="text-center">{title}</p>
      <Button variant="outline" onClick={onRetry} disabled={retrying}>
        <RotateCcw />
        {t({ zh: "重新加载", en: "Reload" })}
      </Button>
    </div>
  )
}
