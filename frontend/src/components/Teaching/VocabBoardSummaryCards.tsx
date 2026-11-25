import { Link } from "@tanstack/react-router"
import { Leaf, Sprout, Swords, Trophy, UsersRound } from "lucide-react"

import type { FarmBoardSummary, PkBoardSummary } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { badgeText, sortFarmBadges, topFarmHarvesters } from "@/lib/farm"
import { useI18n } from "@/lib/i18n"
import { formatDateTime } from "@/lib/time"
import { formatNullableCount } from "@/lib/utils"
import { hasFarmSummary, hasPkSummary } from "@/lib/vocabBoardSummary"

const BOARD_BADGE_LIMIT = 3
const BOARD_HARVESTER_LIMIT = 3

/**
 * 课堂看板 PK / 农场只读摘要卡片。
 *
 * 数值口径与看板既有卡片一致，这里只做聚合展示；开厅、收获、改分等写操作
 * 仍走词汇页对应面板，本组件不触发任何写接口。
 */
export function VocabBoardSummaryCards({
  code,
  pk,
  farm,
}: {
  code: string
  pk: PkBoardSummary | null | undefined
  farm: FarmBoardSummary | null | undefined
}) {
  const showPk = hasPkSummary(pk)
  const showFarm = hasFarmSummary(farm)
  if (!showPk && !showFarm) return null

  return (
    <section
      className="grid items-start gap-4 sm:grid-cols-2"
      aria-label="Vocabulary PK and farm summary"
    >
      {showPk && pk && <PkBoardCard code={code} pk={pk} />}
      {showFarm && farm && <FarmBoardCard code={code} farm={farm} />}
    </section>
  )
}

function PkBoardCard({ code, pk }: { code: string; pk: PkBoardSummary }) {
  const { t, lang } = useI18n()
  const lastMatch = pk.last_match ?? null
  const lastMatchAt = lastMatch?.at ?? pk.last_match_at ?? null
  const winner = lastMatch?.winner_display_name?.trim() || null
  const openLabel =
    pk.open === true
      ? t({ zh: "开放中", en: "Open" })
      : pk.open === false
        ? t({ zh: "未开放", en: "Closed" })
        : "–"

  const stats = [
    {
      label: t({ zh: "本周对局", en: "Matches this week" }),
      value: formatNullableCount(pk.matches_this_week),
    },
    {
      label: t({ zh: "排队人数", en: "Queued" }),
      value: formatNullableCount(pk.queue_count),
    },
    {
      label: t({ zh: "进行中对局", en: "Active matches" }),
      value: formatNullableCount(pk.active_match_count),
    },
  ]

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <Swords className="size-5" />
          {t({ zh: "PK 对战", en: "PK Battle" })}
        </CardTitle>
        <Link
          to="/t/$code/vocab"
          params={{ code }}
          search={{ tab: "pk" }}
          className="shrink-0 text-sm font-medium text-primary"
        >
          {t({ zh: "进入词汇页", en: "Open vocabulary" })}
        </Link>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge
            variant={pk.open === true ? "secondary" : "outline"}
            className="tabular-nums"
          >
            {openLabel}
          </Badge>
        </div>
        <div className="grid grid-cols-3 gap-3">
          {stats.map((stat) => (
            <div
              key={stat.label}
              className="rounded-2xl border bg-secondary/30 p-3"
            >
              <p className="text-xs leading-5 text-muted-foreground">
                {stat.label}
              </p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">
                {stat.value}
              </p>
            </div>
          ))}
        </div>
        <p className="text-sm text-muted-foreground">
          {t({ zh: "最近一场", en: "Last match" })}
          {lastMatchAt ? ` · ${formatDateTime(lastMatchAt, lang)}` : " –"}
          {winner
            ? ` · ${t({ zh: "胜者", en: "Winner" })} ${winner}`
            : lastMatch
              ? ` · ${t({ zh: "平局", en: "Draw" })}`
              : ""}
        </p>
      </CardContent>
    </Card>
  )
}

function FarmBoardCard({
  code,
  farm,
}: {
  code: string
  farm: FarmBoardSummary
}) {
  const { t } = useI18n()
  const badges = sortFarmBadges(farm.badge_counts).slice(0, BOARD_BADGE_LIMIT)
  const harvesters = topFarmHarvesters(
    farm.top_harvesters,
    BOARD_HARVESTER_LIMIT,
  )

  const stats = [
    {
      label: t({ zh: "参与地块", en: "Participants" }),
      value: formatNullableCount(farm.participants),
      icon: UsersRound,
    },
    {
      label: t({ zh: "成熟地块", en: "Mature plots" }),
      value: formatNullableCount(farm.mature_plots),
      icon: Leaf,
    },
    {
      label: t({ zh: "累计收获", en: "Harvests" }),
      value: formatNullableCount(farm.harvested_total),
      icon: Sprout,
    },
  ]

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <Sprout className="size-5" />
          {t({ zh: "专注农场", en: "Focus Farm" })}
        </CardTitle>
        <Link
          to="/t/$code/vocab"
          params={{ code }}
          search={{ tab: "farm" }}
          className="shrink-0 text-sm font-medium text-primary"
        >
          {t({ zh: "进入词汇页", en: "Open vocabulary" })}
        </Link>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-3 gap-3">
          {stats.map((stat) => (
            <div
              key={stat.label}
              className="rounded-2xl border bg-secondary/30 p-3"
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-xs leading-5 text-muted-foreground">
                  {stat.label}
                </p>
                <stat.icon
                  aria-hidden="true"
                  className="size-4 shrink-0 text-muted-foreground"
                />
              </div>
              <p className="mt-1 text-2xl font-semibold tabular-nums">
                {stat.value}
              </p>
            </div>
          ))}
        </div>
        {badges.length > 0 && (
          <ul className="space-y-1.5">
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
        {harvesters.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-t border-border/60 pt-3">
            <Trophy className="size-4 text-muted-foreground" />
            {harvesters.map((harvester, index) => (
              <span
                key={`${harvester.display_name}-${index}`}
                className="inline-flex items-center gap-1 rounded-full bg-secondary/50 px-2.5 py-1 text-xs tabular-nums"
              >
                {harvester.display_name} ·{" "}
                {formatNullableCount(harvester.harvest_count)}
              </span>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
