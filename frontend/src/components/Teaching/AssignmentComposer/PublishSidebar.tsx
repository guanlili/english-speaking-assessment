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
        <div className="space-y-1 font-medium">
          {planCounts.reading > 0 && (
            <p>
              {t({
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
              })}
            </p>
          )}
          {planCounts.repeat > 0 && (
            <p>
              {t({
                zh: `复述 ${planCounts.repeat} 句`,
                en: `${planCounts.repeat} Listen & Repeat`,
              })}
            </p>
          )}
          {planCounts.qa > 0 && (
            <p>
              {t({
                zh: `问答 ${planCounts.qa} 道`,
                en: `${planCounts.qa} Scenario Q&A`,
              })}
            </p>
          )}
          {planCounts.instruction > 0 && (
            <p>
              {t({
                zh: `说明 ${planCounts.instruction} 条`,
                en: `${planCounts.instruction} Instructions`,
              })}
            </p>
          )}
          {planCounts.reading + planCounts.repeat + planCounts.qa === 0 &&
            t({
              zh: "尚未选择可作答题目",
              en: "No answerable questions selected",
            })}
        </div>
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
          zh: "学生题单以最近一次确认发布为准；修改选择后，需再次确认发布才会更新。",
          en: "Students use the latest confirmed publish. After changing selections, confirm a new publish to update their practice.",
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
