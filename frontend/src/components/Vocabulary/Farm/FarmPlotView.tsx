import { Coins, Flame, Sprout, Trophy } from "lucide-react"

import type { FarmView } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  badgeSourceLabel,
  badgeText,
  FARM_HARVEST_XP,
  FARM_MATURE_POINTS,
  FARM_STAGE_HINTS,
  FARM_STAGE_LABELS,
  type HarvestState,
  harvestState,
  pointsToMature,
} from "@/lib/farm"
import { useI18n } from "@/lib/i18n"

const STAGE_ICONS = [Sprout, Sprout, Sprout, Trophy]

/**
 * 专注农场展示层：地块四阶段、今日有效练习、XP / streak / 徽章来源与收获按钮。
 *
 * 只读口径：XP、连胜、徽章都来自既有课堂账本；本组件不本地累加积分，
 * 也不做商家式排行榜或停留时长推断。
 */
export default function FarmPlotView({
  view,
  harvesting,
  onHarvest,
}: {
  view: FarmView
  harvesting: boolean
  onHarvest: () => void
}) {
  const { t } = useI18n()
  const stage = view.stage as 0 | 1 | 2 | 3
  const state: HarvestState = harvestState(view)
  const StageIcon = STAGE_ICONS[stage] ?? Sprout
  const progress = Math.min(
    100,
    (view.growth_points / FARM_MATURE_POINTS) * 100,
  )
  const remaining = pointsToMature(view.growth_points)

  const harvestLabel =
    state === "ready"
      ? {
          zh: `收获 · +${FARM_HARVEST_XP} XP`,
          en: `Harvest · +${FARM_HARVEST_XP} XP`,
        }
      : state === "xp-capped"
        ? {
            zh: "今日农场 XP 已达上限",
            en: "Daily farm XP limit reached",
          }
        : {
            zh: `还差 ${remaining} 点成熟`,
            en: `${remaining} more points to mature`,
          }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader className="flex flex-wrap items-center justify-between gap-3 space-y-0">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
              <StageIcon className="size-5" />
            </span>
            <div className="min-w-0">
              <CardTitle className="text-base">
                {t(FARM_STAGE_LABELS[stage])}
              </CardTitle>
              <CardDescription>{t(FARM_STAGE_HINTS[stage])}</CardDescription>
            </div>
          </div>
          <Badge variant="secondary">
            {view.growth_points} / {FARM_MATURE_POINTS}
          </Badge>
        </CardHeader>
        <CardContent className="space-y-4">
          <div
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={FARM_MATURE_POINTS}
            aria-valuenow={view.growth_points}
            className="h-2.5 w-full overflow-hidden rounded-full bg-secondary"
          >
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <p className="text-muted-foreground">
              {t({
                zh: "今日有效练习",
                en: "Valid practices today",
              })}
              <span className="ml-2 font-semibold text-foreground">
                {view.today_points} / {view.daily_growth_cap}
              </span>
            </p>
            {state === "locked" && remaining > 0 && (
              <p className="text-xs text-muted-foreground">
                {t({
                  zh: `再完成 ${remaining} 条首答即可成熟`,
                  en: `${remaining} more first answers to mature`,
                })}
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <Coins className="size-5 text-primary" />
            <div>
              <p className="text-xs text-muted-foreground">
                {t({ zh: "XP 余额", en: "XP balance" })}
              </p>
              <p className="text-base font-semibold">{view.xp ?? 0}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <Flame className="size-5 text-primary" />
            <div>
              <p className="text-xs text-muted-foreground">
                {t({ zh: "连续练习", en: "Streak" })}
              </p>
              <p className="text-base font-semibold">
                {t({
                  zh: `${view.streak_days ?? 0} 天`,
                  en: `${view.streak_days ?? 0} days`,
                })}
              </p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <Trophy className="size-5 text-primary" />
            <div>
              <p className="text-xs text-muted-foreground">
                {t({ zh: "累计收获", en: "Total harvests" })}
              </p>
              <p className="text-base font-semibold">{view.harvest_count}</p>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="flex flex-col gap-3 pt-5">
          <Button
            onClick={onHarvest}
            disabled={state !== "ready" || harvesting}
            size="lg"
          >
            <Trophy />
            {harvesting
              ? t({ zh: "收获中…", en: "Harvesting…" })
              : t(harvestLabel)}
          </Button>
          {state === "xp-capped" && (
            <p className="text-xs text-muted-foreground">
              {t({
                zh: "今日农场 XP 已达上限，明天再来收获。",
                en: "Daily farm XP limit reached — come back tomorrow.",
              })}
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            {t({
              zh: "农场成长只计任务练习、自主练习与复习的首答；测验与重试不计入。",
              en: "Growth counts only first answers in assigned practice, self practice and review; quizzes and retries don't count.",
            })}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="space-y-1">
          <CardTitle className="text-base">
            {t({ zh: "徽章", en: "Badges" })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: "徽章与 XP 都记在既有课堂账本上。",
              en: "Badges and XP stay in the existing classroom ledger.",
            })}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {view.badges && view.badges.length > 0 ? (
            <ul className="grid gap-3">
              {view.badges.map((badge) => {
                const text = badgeText(badge)
                return (
                  <li
                    key={badge.key}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border p-3"
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-semibold">{t(text.label)}</p>
                      {text.description && (
                        <p className="text-xs text-muted-foreground">
                          {t(text.description)}
                        </p>
                      )}
                    </div>
                    <Badge variant="outline">
                      {t(badgeSourceLabel(badge))}
                    </Badge>
                  </li>
                )
              })}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">
              {t({
                zh: "完成练习后，徽章会出现在这里。",
                en: "Badges will appear here as you practice.",
              })}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
