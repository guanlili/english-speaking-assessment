import type { VocabularyLeaderboardEntry } from "@/client/types.gen"
import { useI18n } from "@/lib/i18n"
import { padAliasNo, resolveEntryName } from "@/lib/leaderboard"

/**
 * 榜单条目展示名：
 * - 匿名：「同学 07 / Student 07」两位编号；
 * - 实名：显示姓名，`suffix`（同名消歧后缀）小字补充。
 */
export function EntryName({
  entry,
  anonymous,
}: {
  entry: VocabularyLeaderboardEntry
  anonymous: boolean
}) {
  const { t } = useI18n()
  const name = resolveEntryName(entry, anonymous)

  if (name.kind === "anonymous") {
    return (
      <span className="inline-flex items-center gap-1.5">
        <span>{t({ zh: "同学", en: "Student" })}</span>
        <span className="tabular-nums">{padAliasNo(name.aliasNo)}</span>
      </span>
    )
  }

  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="truncate">{name.name}</span>
      {name.suffix && (
        <span className="text-xs text-muted-foreground">{name.suffix}</span>
      )}
    </span>
  )
}
