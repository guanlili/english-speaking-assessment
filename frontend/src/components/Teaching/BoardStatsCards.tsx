import { Card, CardContent } from "@/components/ui/card"
import { useI18n } from "@/lib/i18n"

/** 学生结果 tab 的四张统计卡（展示组件）：班级学生 / 已有作答 / 问答均分 / 值得关注。 */
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
  /** 问答参考均分；无有效分时页面传入 "-" */
  classAvg: string
  inactiveCount: number
}) {
  const { t } = useI18n()
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Card>
        <CardContent className="py-4">
          <p className="text-xs text-muted-foreground">
            {t({ zh: "班级学生", en: "Students" })}
          </p>
          <p className="mt-1 text-2xl font-bold">
            {studentsCount}
            <span className="ml-1 text-xs font-normal text-muted-foreground">
              {t({
                zh: `/ ${classSize} 人`,
                en: `/ ${classSize}`,
              })}
            </span>
          </p>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="py-4">
          <p className="text-xs text-muted-foreground">
            {t({ zh: "已有作答", en: "Students with answers" })}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {t({
              zh: "至少提交一道题",
              en: "At least one answer submitted",
            })}
          </p>
          <p className="mt-1 text-2xl font-bold">
            {submittedCount}
            <span className="ml-1 text-xs font-normal text-muted-foreground">
              {t({
                zh: `/ ${classSize} 人`,
                en: `/ ${classSize}`,
              })}
            </span>
          </p>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="py-4">
          <p className="text-xs text-muted-foreground">
            {t({ zh: "问答参考均分", en: "Scenario Q&A Avg" })}
          </p>
          <p className="mt-1 text-2xl font-bold">{classAvg}</p>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="py-4">
          <p className="text-xs text-muted-foreground">
            {t({ zh: "值得关注", en: "Needs Attention" })}
          </p>
          <p className="mt-1 text-2xl font-bold">
            {inactiveCount}
            <span className="ml-1 text-xs font-normal text-muted-foreground">
              {t({
                zh: "人 7 天未练",
                en: "inactive for 7 days",
              })}
            </span>
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
