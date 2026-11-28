import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { ArrowRight, BookA } from "lucide-react"

import { VocabularyService } from "@/client"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useModules } from "@/hooks/useModules"
import { COURSES } from "@/lib/courses"
import { useI18n } from "@/lib/i18n"

/**
 * 学生「我的成长」里的单词课快照：跨课程能力并列展示。
 *
 * 口径：
 * - 只在已开通单词课时出现；未开通整块不渲染（不置灰占位）；
 * - 取数失败整块静默隐藏，不影响口语成长区（两门课服务相互独立）；
 * - 只展示后端真实计数（档案 / 到期 / 今日已复习 / 认读与拼写分布），
 *   不估算记忆留存率或掌握度等级——那是教师端 mastery 的口径。
 */
export function StudentVocabSnapshot({ code }: { code: string }) {
  const { t } = useI18n()
  const { hasModule } = useModules()
  const vocabEnabled = hasModule("vocabulary")

  const statsQuery = useQuery({
    queryKey: ["vocab-review-stats", code],
    queryFn: () =>
      VocabularyService.readReviewStats({ code: code.toUpperCase() }),
    enabled: vocabEnabled,
    retry: 1,
  })

  if (!vocabEnabled) return null
  if (statsQuery.isPending) {
    return <Skeleton className="h-28 rounded-2xl" />
  }
  if (statsQuery.isError || !statsQuery.data) return null

  const stats = statsQuery.data

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-1.5 text-base">
          <BookA className="size-4 text-primary" aria-hidden="true" />
          {t(COURSES.vocabulary.name)}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-3 gap-3 text-center">
          <Metric
            label={t({ zh: "已建档", en: "Tracked" })}
            value={`${stats.tracked_count ?? 0}`}
          />
          <Metric
            label={t({ zh: "待复习", en: "Due review" })}
            value={`${stats.due_count ?? 0}`}
          />
          <Metric
            label={t({ zh: "今日已复习", en: "Reviewed today" })}
            value={`${stats.reviewed_today_count ?? 0}`}
          />
        </div>
        {(stats.recognition_count ?? 0) + (stats.spelling_count ?? 0) > 0 && (
          <p className="text-xs text-muted-foreground">
            {t({
              zh: `认读 ${stats.recognition_count ?? 0} 条 · 拼写 ${stats.spelling_count ?? 0} 条`,
              en: `Recognition ${stats.recognition_count ?? 0} · Spelling ${stats.spelling_count ?? 0}`,
            })}
          </p>
        )}
        <Link
          to="/vocab/$code"
          params={{ code }}
          className="inline-flex items-center gap-1 text-xs text-primary"
        >
          {t({ zh: "去单词课", en: "Open vocabulary" })}
          <ArrowRight className="size-3" aria-hidden="true" />
        </Link>
      </CardContent>
    </Card>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-secondary/40 px-2 py-3">
      <p className="text-lg font-semibold leading-none">{value}</p>
      <p className="mt-1.5 text-[11px] text-muted-foreground">{label}</p>
    </div>
  )
}
