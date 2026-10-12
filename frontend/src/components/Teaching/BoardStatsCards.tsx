import { AudioLines, MessageSquareText, UserRound, Users } from "lucide-react"
import { useI18n } from "@/lib/i18n"

/** Keep reference score and participation counts visibly distinct. */
export function BoardStatsCards({
  studentsCount,
  classSize,
  submittedCount,
  classAvg,
  inactiveCount,
}: {
  studentsCount: number
  classSize: number
  submittedCount: number
  classAvg: string
  inactiveCount: number
}) {
  const { t } = useI18n()
  const stats = [
    {
      label: t({ zh: "班级学生", en: "Students" }),
      value: studentsCount,
      detail: t({
        zh: `班级人数 ${classSize} 人`,
        en: `Class size: ${classSize}`,
      }),
      icon: Users,
      tone: "bg-secondary text-primary",
    },
    {
      label: t({ zh: "已有作答", en: "Students with answers" }),
      value: submittedCount,
      detail: t({ zh: "至少提交一道题", en: "At least one answer submitted" }),
      icon: AudioLines,
      tone: "bg-secondary text-primary",
    },
    {
      label: t({ zh: "问答参考均分", en: "Scenario Q&A Avg" }),
      value: classAvg,
      detail: t({
        zh: "已评分学生的问答均分",
        en: "Average across scored students",
      }),
      icon: MessageSquareText,
      tone: "bg-accent text-accent-foreground",
    },
    {
      label: t({ zh: "值得关注", en: "Needs Attention" }),
      value: inactiveCount,
      detail: t({ zh: "人 7 天未练", en: "inactive for 7 days" }),
      icon: UserRound,
      tone: "bg-accent text-accent-foreground",
    },
  ]
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {stats.map(({ label, value, detail, icon: Icon, tone }) => (
        <div
          key={label}
          className="flex min-w-0 flex-col rounded-2xl border border-border/80 bg-card p-4 sm:p-5"
        >
          <div className="flex items-start justify-between gap-2">
            <p className="text-xs font-medium leading-5 text-muted-foreground">
              {label}
            </p>
            <span
              className={`grid size-8 shrink-0 place-items-center rounded-xl ${tone}`}
            >
              <Icon aria-hidden="true" className="size-4" />
            </span>
          </div>
          <p className="mt-2 text-3xl font-semibold tracking-tight tabular-nums">
            {value}
          </p>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">
            {detail}
          </p>
        </div>
      ))}
    </div>
  )
}
