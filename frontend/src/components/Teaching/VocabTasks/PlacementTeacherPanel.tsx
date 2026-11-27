import { useQuery } from "@tanstack/react-query"
import { Compass, ShieldCheck } from "lucide-react"

import { ApiError, VocabularyService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { useI18n } from "@/lib/i18n"
import { placementBandLabel, placementLimitationLabel } from "@/lib/placement"
import { formatDateTime } from "@/lib/time"

/**
 * 教师端「学生测结果」只读面板（挂在 `/t/$code/vocab`）。
 *
 * 口径：粗分档小测是探针式建议，**不是定级、不是考试分数**；这里只展示每位
 * 学生最近一次测分的建议档位 / 级别 / 推荐词库与素材限制，供教学参考，不可编辑。
 */
export function PlacementTeacherPanel({ code }: { code: string }) {
  const { t, lang } = useI18n()

  const resultsQuery = useQuery({
    queryKey: ["vocab-teacher", code, "placement-results"],
    queryFn: () =>
      VocabularyService.placementResults({ code: code.toUpperCase() }),
    staleTime: 15_000,
  })

  const denied =
    resultsQuery.error instanceof ApiError && resultsQuery.error.status === 403

  const rows = resultsQuery.data ?? []

  return (
    <section
      aria-label={t({ zh: "学生测结果", en: "Placement results" })}
      className="space-y-3"
    >
      <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-primary/10 bg-secondary/40 p-4">
        <ShieldCheck className="size-5 text-primary" />
        <div>
          <p className="text-sm font-semibold">
            {t({
              zh: "学生测结果（教学参考）",
              en: "Student placement results",
            })}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {t({
              zh: "粗分档建议，不是定级或考试分数；每位学生展示最近一次测分。",
              en: "Rough placement guide, not a level or exam score. Latest attempt per student.",
            })}
          </p>
        </div>
      </div>

      {resultsQuery.isPending ? (
        <div className="space-y-2">
          <Skeleton className="h-12 rounded-xl" />
          <Skeleton className="h-12 rounded-xl" />
        </div>
      ) : denied ? (
        <p className="rounded-2xl border p-4 text-sm text-muted-foreground">
          {t({
            zh: "你还不是这个课堂的授权教师，无法查看学生测结果。",
            en: "You're not an authorized teacher of this class.",
          })}
        </p>
      ) : rows.length === 0 ? (
        <p className="rounded-2xl border p-4 text-sm text-muted-foreground">
          {t({
            zh: "还没有学生完成测一测。",
            en: "No student has completed the placement quiz yet.",
          })}
        </p>
      ) : (
        <ul className="grid gap-2">
          {rows.map((row) => (
            <li
              key={row.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-2xl border bg-card px-4 py-3"
            >
              <span className="min-w-0 flex-1">
                <span className="font-medium">{row.display_name}</span>
                <span className="ml-2 text-sm">
                  {t(placementBandLabel(row.recommended_band))}
                </span>
                {row.recommended_level && (
                  <span className="ml-2 text-xs text-muted-foreground">
                    {row.recommended_level}
                  </span>
                )}
                {row.recommended_book_title && (
                  <span className="ml-2 inline-flex items-center gap-1 text-xs text-muted-foreground">
                    <Compass className="size-3" />
                    {row.recommended_book_title}
                  </span>
                )}
              </span>
              <span className="text-xs text-muted-foreground tabular-nums">
                {t({
                  zh: `${row.question_count} 题 · 答对 ${row.correct_count}`,
                  en: `${row.question_count} items · ${row.correct_count} correct`,
                })}
              </span>
              {placementLimitationLabel(row.limitation) && (
                <Badge variant="outline" className="font-normal">
                  {t({ zh: "素材有限", en: "Limited" })}
                </Badge>
              )}
              <span className="text-xs text-muted-foreground tabular-nums">
                {row.submitted_at
                  ? formatDateTime(row.submitted_at, lang)
                  : "–"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
