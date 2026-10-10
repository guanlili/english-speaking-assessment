import { Link } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

/**
 * 练习页收尾（展示组件）：反馈节奏说明 + 全部完成后的结果页入口 +
 * 分数性质说明。结果页目标由页面给定（绑定实际完成的会话）。
 */
export default function PracticeFooter({
  allDone,
  resultsTo,
  resultsParams,
  resultsSearch,
}: {
  allDone: boolean
  resultsTo: string
  resultsParams: Record<string, string>
  resultsSearch?: Record<string, string>
}) {
  const { t } = useI18n()
  return (
    <>
      <p className="text-center text-sm text-muted-foreground">
        {t({
          zh: "每题先看分数和转写，完成后查看全面评价与改进建议。",
          en: "See each item's score and transcript first, then view full feedback and tips once you finish.",
        })}
      </p>

      {allDone && (
        <Button size="lg" asChild>
          <Link to={resultsTo} params={resultsParams} search={resultsSearch}>
            {t({ zh: "查看本轮结果", en: "View this round's results" })}
          </Link>
        </Button>
      )}

      <p className="pb-6 text-center text-xs text-muted-foreground">
        {t({
          zh: "分数是参考反馈，不是考试成绩。",
          en: "Scores are reference feedback, not exam results.",
        })}
      </p>
    </>
  )
}
