import { Link } from "@tanstack/react-router"
import type { MySessionSummary } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

/**
 * 「我的成长」单轮记录行。
 *
 * 进行中轮次只给「继续考试 / 继续练习」入口（明确进入作答态）；
 * 已完成轮次一律进只读结果页（review=1），不得把人带回录音/输入界面。
 */
export function HistorySessionRow({
  row,
  code,
}: {
  row: MySessionSummary
  code: string
}) {
  const { t } = useI18n()
  const title =
    row.title ??
    t(
      row.mode === "explore"
        ? { zh: "主题探索", en: "Topic explore" }
        : { zh: "自主练习", en: "Self practice" },
    )

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl border px-3 py-2.5">
      <span className="w-24 shrink-0 text-xs text-muted-foreground">
        {/* 练习日按服务端时区落库（YYYY-MM-DD）：直接展示原串，
        不经本地时区解析（与轨迹表同口径，避免西半球差一天） */}
        {row.session_date}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2">
          <span className="truncate text-sm font-medium">{title}</span>
          <Badge variant="outline">
            {t(
              row.is_exam
                ? { zh: "考试", en: "Exam" }
                : { zh: "练习", en: "Practice" },
            )}
          </Badge>
          {row.mode === "explore" && (
            <Badge variant="outline" className="shrink-0 text-muted-foreground">
              {t({ zh: "探索", en: "Explore" })}
            </Badge>
          )}
          {row.in_progress && (
            <Badge variant="secondary" className="shrink-0">
              {t({ zh: "进行中", en: "In progress" })}
            </Badge>
          )}
        </span>
        <span className="mt-0.5 block text-xs text-muted-foreground">
          {t({
            zh: `完成 ${row.done_count}/${row.total_count} 题 · 参考分 ${row.overall_avg ?? "–"}`,
            en: `${row.done_count}/${row.total_count} done · ref score ${row.overall_avg ?? "–"}`,
          })}
        </span>
      </span>
      <Button variant="outline" size="sm" className="min-h-11 shrink-0" asChild>
        {row.in_progress ? (
          <Link
            to={row.is_exam ? "/exam/$code" : "/p/$code"}
            params={{ code }}
            search={{ session: row.session_id }}
          >
            {t(
              row.is_exam
                ? { zh: "继续考试", en: "Resume exam" }
                : { zh: "继续练习", en: "Resume practice" },
            )}
          </Link>
        ) : (
          <Link
            to={row.is_exam ? "/exam/$code/result" : "/p/$code/result"}
            params={{ code }}
            search={{ session: row.session_id, review: "1" }}
          >
            {t({ zh: "查看反馈", en: "View Feedback" })}
          </Link>
        )}
      </Button>
    </li>
  )
}
