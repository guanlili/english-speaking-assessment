import { Link } from "@tanstack/react-router"
import { Flame, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { StoredStudent } from "@/lib/classroom-student"
import { displayName } from "@/lib/classroom-student"
import { useI18n } from "@/lib/i18n"

/** 练习页顶部 HUD：题号/单元徽标 + 学生/课堂/游戏化 + 结果页入口（展示组件） */
export function PracticeHeader({
  currentIndex,
  total,
  unitTitle,
  classroomCode,
  student,
  streakDays,
  xp,
  resultsTo,
  resultsSearch,
}: {
  currentIndex: number
  total: number
  unitTitle?: string | null
  classroomCode: string
  student: StoredStudent
  streakDays?: number
  xp?: number
  resultsTo: string
  resultsSearch?: Record<string, string>
}) {
  const { t } = useI18n()
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 className="text-xl font-bold tracking-tight">
          {t({
            zh: `第 ${currentIndex + 1}/${total} 题`,
            en: `Item ${currentIndex + 1}/${total}`,
          })}
          {unitTitle && (
            <span className="ml-2 text-sm font-medium text-primary">
              📌 {unitTitle}
            </span>
          )}
        </h1>
        <p className="mt-1 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
          {displayName(student)} ·{" "}
          {t({
            zh: `课堂 ${classroomCode}`,
            en: `Classroom ${classroomCode}`,
          })}
          {streakDays !== undefined && (
            <span className="flex items-center gap-1">
              <Flame className="size-4 text-orange-500" />
              {t({ zh: `${streakDays} 天`, en: `${streakDays} days` })}
            </span>
          )}
          {xp !== undefined && (
            <span className="flex items-center gap-1 font-medium text-foreground">
              <Sparkles className="size-4 text-primary" />
              {xp} XP
            </span>
          )}
        </p>
      </div>
      <div className="flex gap-1">
        <Button variant="ghost" size="sm" asChild>
          <Link to={resultsTo} search={resultsSearch}>
            {t({ zh: "结果页", en: "Results" })}
          </Link>
        </Button>
      </div>
    </div>
  )
}

export default PracticeHeader
