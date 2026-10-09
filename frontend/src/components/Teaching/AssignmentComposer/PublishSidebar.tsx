import { Link } from "@tanstack/react-router"
import { Check, Eye } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { BiString } from "@/lib/i18n"
import { useI18n } from "@/lib/i18n"

/** 右侧「检查并发布」栏：数量摘要、就绪检查、预览入口。 */
export default function PublishSidebar({
  code,
  planCounts,
  problems,
  publishPending,
  onPreview,
}: {
  code: string
  planCounts: {
    reading: number
    readingSentences: number
    repeat: number
    qa: number
    instruction: number
  }
  problems: BiString[]
  publishPending: boolean
  onPreview: () => void
}) {
  const { t } = useI18n()
  return (
    <aside className="min-w-0 self-start rounded-2xl border bg-card p-4 sm:p-6">
      <h2 className="font-semibold">
        {t({ zh: "检查并发布", en: "Review & Publish" })}
      </h2>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">
        {t({
          zh: "选好内容和题型后，先预览学生将看到的内容，再确认发布。",
          en: "After choosing content and types, preview what students will see, then confirm the publish.",
        })}
      </p>
      <div className="my-5 space-y-1 border-y py-4 text-sm">
        <p className="font-medium">
          {planCounts.reading > 0
            ? t({
                zh: `朗读 ${planCounts.reading} 篇${
                  planCounts.readingSentences > 0
                    ? ` · 逐句 ${planCounts.readingSentences} 题`
                    : ""
                }`,
                en: `${planCounts.reading} Read Aloud${
                  planCounts.readingSentences > 0
                    ? ` · ${planCounts.readingSentences} sentence questions`
                    : ""
                }`,
              })
            : null}
          {planCounts.repeat > 0
            ? t({
                zh: `复述 ${planCounts.repeat} 句`,
                en: `${planCounts.repeat} Listen & Repeat`,
              })
            : null}
          {planCounts.qa > 0
            ? t({
                zh: `问答 ${planCounts.qa} 道`,
                en: `${planCounts.qa} Scenario Q&A`,
              })
            : null}
          {planCounts.instruction > 0
            ? t({
                zh: `说明 ${planCounts.instruction} 条`,
                en: `${planCounts.instruction} Instructions`,
              })
            : null}
          {planCounts.reading + planCounts.repeat + planCounts.qa === 0 &&
            t({ zh: "尚未选择题型", en: "No question types selected" })}
        </p>
      </div>
      {problems.length ? (
        <ul className="space-y-3 text-sm leading-6 text-muted-foreground">
          {problems.map((problem) => (
            <li key={problem.zh}>{t(problem)}</li>
          ))}
        </ul>
      ) : (
        <p className="flex items-center gap-2 text-sm text-primary">
          <Check className="size-4" />
          {t({
            zh: "内容已齐备，可以预览",
            en: "Everything is ready — you can preview",
          })}
        </p>
      )}
      <Button
        className="mt-5 w-full"
        disabled={problems.length > 0 || publishPending}
        onClick={onPreview}
      >
        <Eye className="size-4" />
        {t({ zh: "预览练习", en: "Preview Practice" })}
      </Button>
      <p className="mt-3 text-xs leading-5 text-muted-foreground">
        {t({
          zh: "当前选择尚未发布。只有确认发布后，才会更新学生练习。",
          en: "Your current selections aren't published yet. Student practice updates only after you confirm the publish.",
        })}
      </p>
      <Button variant="link" className="mt-2 h-auto px-0" asChild>
        <Link to="/create" search={{ kind: "reading", classroom: code }}>
          {t({
            zh: "到题目库补充内容 →",
            en: "Add content in the Question Bank →",
          })}
        </Link>
      </Button>
    </aside>
  )
}
