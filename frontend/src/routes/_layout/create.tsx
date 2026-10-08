import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowLeft } from "lucide-react"
import { useState } from "react"
import { SentenceLibrary } from "@/components/Teaching/SentenceLibrary"
import { Button } from "@/components/ui/button"
import { APP_NAME } from "@/config"
import { useI18n } from "@/lib/i18n"
import { PassagesAdmin } from "./admin.passages"
import { QuestionsAdmin } from "./admin.questions"
import { ScenariosAdmin } from "./admin.scenarios"
import { UnitsAdmin } from "./admin.units"

export const Route = createFileRoute("/_layout/create")({
  // kind 参数仅为兼容旧链接（指派页/返回链接仍带 ?kind=），新版题库单页展示全部题型
  validateSearch: (
    search: Record<string, unknown>,
  ): { kind?: string; classroom?: string } => ({
    kind: typeof search.kind === "string" ? search.kind : undefined,
    classroom:
      typeof search.classroom === "string" &&
      /^[a-zA-Z0-9_-]{1,16}$/.test(search.classroom)
        ? search.classroom
        : undefined,
  }),
  component: QuestionLibrary,
  head: () => ({
    meta: [{ title: `题目库 / Question Bank - ${APP_NAME}` }],
  }),
})

function QuestionLibrary() {
  const { t } = useI18n()
  const { classroom } = Route.useSearch()
  const [qaMode, setQaMode] = useState<"topics" | "questions">("topics")
  return (
    <div className="space-y-9">
      {classroom && (
        <Link
          to="/t/$code"
          params={{ code: classroom }}
          className="inline-flex items-center gap-2 text-sm font-medium text-primary"
        >
          <ArrowLeft className="size-4" />
          {t({
            zh: `返回课堂 ${classroom}，安排练习`,
            en: `Back to classroom ${classroom} to assign practice`,
          })}
        </Link>
      )}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="mb-2 text-xs font-semibold tracking-widest text-primary">
            {t({ zh: "准备教学内容", en: "Prepare teaching content" })}
          </p>
          <h1 className="text-3xl font-bold">
            {t({ zh: "题目库", en: "Question Bank" })}
          </h1>
          <p className="mt-3 text-sm text-muted-foreground">
            {t({
              zh: "按「主题 → 篇目 → 句子」三层组织：主题（单元）归组篇目，篇目下管理听句复述；情景问答按主题独立配套。",
              en: "Organized in three layers — topic → passage → sentence: units group passages, passages hold their repeat sentences, and Scenario Q&A pairs by topic.",
            })}
          </p>
        </div>
        {!classroom && (
          <Button asChild variant="outline">
            <Link to="/classrooms">
              {t({
                zh: "去课堂安排练习",
                en: "Assign practice in classrooms",
              })}
            </Link>
          </Button>
        )}
      </div>

      {/* 第 1 层：主题（单元） */}
      <section aria-labelledby="bank-topics" className="space-y-4">
        <h2 id="bank-topics" className="text-lg font-semibold">
          {t({ zh: "主题 · 单元", en: "Topics · Units" })}
        </h2>
        <UnitsAdmin embedded />
      </section>

      {/* 第 2 层：篇目（展开后内联管理第 3 层：句子） */}
      <section aria-labelledby="bank-passages" className="space-y-4">
        <h2 id="bank-passages" className="text-lg font-semibold">
          {t({ zh: "文章朗读 · 篇目", en: "Read Aloud · Passages" })}
        </h2>
        <p className="text-sm text-muted-foreground">
          {t({
            zh: "未拆分的文章整篇一道题；拆分过的文章组卷时按句出题，学生逐句朗读。听句复述作为配套题单独管理。",
            en: "An unsplit article is one question; a split article becomes one question per sentence when composing practice, so students read aloud sentence by sentence. Paired Listen & Repeat items are managed separately.",
          })}
        </p>
        <PassagesAdmin key="bank" embedded />
      </section>

      {/* 不挂篇目的分级考试复述句 */}
      <SentenceLibrary standaloneOnly />

      {/* 情景问答：主题 → 问法，独立配套 */}
      <section aria-labelledby="bank-qa" className="space-y-4">
        <h2 id="bank-qa" className="text-lg font-semibold">
          {t({ zh: "情景问答", en: "Scenario Q&A" })}
        </h2>
        <div className="flex flex-wrap gap-2">
          <Button
            variant={qaMode === "topics" ? "secondary" : "ghost"}
            onClick={() => setQaMode("topics")}
          >
            {t({
              zh: "按主题出题 / AI 起草",
              en: "By topic / AI draft",
            })}
          </Button>
          <Button
            variant={qaMode === "questions" ? "secondary" : "ghost"}
            onClick={() => setQaMode("questions")}
          >
            {t({
              zh: "搜索、编辑与批量录入",
              en: "Search, edit & bulk entry",
            })}
          </Button>
        </div>
        {qaMode === "topics" ? (
          <ScenariosAdmin embedded />
        ) : (
          <QuestionsAdmin embedded />
        )}
      </section>

      <p className="text-xs leading-6 text-muted-foreground">
        {t({
          zh: "题目库由全校共享，编辑已使用的内容会影响后续练习。平台评分为教学参考，不代表官方考试成绩。",
          en: "The question bank is shared school-wide; editing content already in use affects later practice. Platform scores are teaching references, not official exam results.",
        })}
      </p>
    </div>
  )
}
