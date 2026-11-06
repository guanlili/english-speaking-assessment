import { Flame, Sparkles, Star, Trophy } from "lucide-react"
import type { GamificationInfo } from "@/client"
import InfoHint from "@/components/Common/InfoHint"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useI18n } from "@/lib/i18n"
import { EXPLAIN } from "@/lib/terms"

export function SessionStarsCard({
  gamification,
  newBadges,
}: {
  gamification: GamificationInfo
  newBadges: { label: string }[]
}) {
  const { t } = useI18n()
  return (
    <section className="flex flex-wrap items-center gap-5 rounded-3xl bg-secondary p-6">
      <span className="-rotate-8 grid size-20 shrink-0 place-items-center rounded-[26px] bg-primary text-yellow-300">
        <Trophy className="size-9" />
      </span>
      <div className="min-w-40 flex-1">
        <p className="text-[10px] font-bold tracking-[0.2em] text-primary">
          EVERY WORD COUNTS
        </p>
        <h2 className="mt-1.5 text-xl font-bold">
          {t({
            zh: "比起完美，开口本身就很棒。",
            en: "Speaking up itself is wonderful — perfection can wait.",
          })}
        </h2>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
          <Tooltip>
            <TooltipTrigger asChild>
              <span
                role="img"
                aria-label={t({
                  zh: `本轮星级：${gamification.session_stars} / 3`,
                  en: `Stars this round: ${gamification.session_stars} / 3`,
                })}
                className="flex items-center gap-1"
              >
                {[1, 2, 3].map((n) => (
                  <Star
                    key={n}
                    className={
                      n <= (gamification.session_stars ?? 0)
                        ? "size-5 fill-yellow-400 text-yellow-400"
                        : "size-5 text-muted-foreground/30"
                    }
                    style={{
                      animation: `star-pop 0.4s ease-out ${n * 0.25}s both`,
                    }}
                  />
                ))}
              </span>
            </TooltipTrigger>
            <TooltipContent className="max-w-64 text-xs leading-relaxed">
              {t(EXPLAIN.stars)}
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="flex items-center gap-1 font-semibold">
                <Sparkles className="size-4 text-primary" />
                XP {gamification.xp}
                <span className="sr-only">{t(EXPLAIN.xp)}</span>
              </span>
            </TooltipTrigger>
            <TooltipContent className="max-w-64 text-xs leading-relaxed">
              {t(EXPLAIN.xp)}
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="flex items-center gap-1 text-muted-foreground">
                <Flame className="size-4 text-orange-500" />
                {t({
                  zh: `连胜 ${gamification.streak_days} 天`,
                  en: `Streak ${gamification.streak_days} days`,
                })}
                <span className="sr-only">{t(EXPLAIN.streak)}</span>
              </span>
            </TooltipTrigger>
            <TooltipContent className="max-w-64 text-xs leading-relaxed">
              {t(EXPLAIN.streak)}
            </TooltipContent>
          </Tooltip>
        </div>
        <p className="mt-1.5 text-xs text-muted-foreground">
          {t(EXPLAIN.stars)}
        </p>
        {newBadges.length > 0 && (
          <p className="mt-2 flex items-center gap-1 text-sm">
            <span className="font-semibold">
              {t({ zh: "本轮获得徽章：", en: "New badges this round:" })}
            </span>
            {newBadges.map((b) => b.label).join(t({ zh: "、", en: ", " }))}
            <InfoHint label={t(EXPLAIN.badges)} />
          </p>
        )}
      </div>
    </section>
  )
}
