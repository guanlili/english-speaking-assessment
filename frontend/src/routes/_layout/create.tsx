import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowLeft } from "lucide-react"
import { useState } from "react"
import { SentenceLibrary } from "@/components/Teaching/SentenceLibrary"
import { TeachingPageHeader } from "@/components/Teaching/TeachingPageHeader"
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
    <div className="space-y-6">
      {classroom && (
        <Link
          to="/t/$code"
          params={{ code: classroom }}
          className="inline-flex min-h-11 items-center gap-2 text-sm font-medium text-primary"
        >
          <ArrowLeft className="size-4" />
          {t({
            zh: `返回课堂 ${classroom}，安排练习`,
            en: `Back to classroom ${classroom} to assign practice`,
          })}
        </Link>
      )}
      <TeachingPageHeader
        eyebrow={t({ zh: "准备教学内容", en: "Prepare teaching content" })}
        title={t({ zh: "题目库", en: "Question Bank" })}
        description={t({
          zh: "按题型准备教学材料，用主题和单元组织内容，再进入课堂选题发布。",
          en: "Prepare materials by question type, organize them into topics and units, then select and publish in your classroom.",
        })}
        actions={
          !classroom && (
            <Button asChild variant="secondary">
              <Link to="/classrooms">
                {t({
                  zh: "去课堂安排练习",
                  en: "Assign practice in classrooms",
                })}
              </Link>
            </Button>
          )
        }
      />
      <nav
        aria-label={t({ zh: "题目库分区", en: "Question bank sections" })}
        className="flex flex-wrap gap-2 rounded-xl border bg-card p-3"
      >
        {[
          { id: "bank-topics", zh: "主题 · 单元", en: "Topics · Units" },
          { id: "bank-passages", zh: "文章朗读", en: "Read Aloud" },
          { id: "bank-repeat", zh: "听句复述", en: "Listen & Repeat" },
          { id: "bank-qa", zh: "情景问答", en: "Scenario Q&A" },
        ].map((section, index) => (
          <a
            key={section.id}
            href={`#${section.id}`}
            className="inline-flex min-h-11 items-center gap-2 rounded-lg px-4 text-sm font-medium text-primary transition-colors hover:bg-primary/10 focus-visible:outline-2 focus-visible:outline-primary"
          >
            <span className="text-xs text-muted-foreground">0{index + 1}</span>
            {t(section)}
          </a>
        ))}
      </nav>

      {/* 第 1 层：主题（单元） */}
      <section
        aria-labelledby="bank-topics"
        className="scroll-mt-6 space-y-4 rounded-2xl border border-primary/10 bg-card p-4 shadow-sm sm:p-6"
      >
        <h2
          id="bank-topics"
          className="scroll-mt-6 text-lg font-semibold text-primary"
        >
          {t({ zh: "主题 · 单元", en: "Topics · Units" })}
        </h2>
        <p className="text-xs text-muted-foreground lg:hidden">
          {t({
            zh: "横向滑动单元表格，可查看状态与编辑操作。",
            en: "Swipe the units table sideways to see status and editing actions.",
          })}
        </p>
        <UnitsAdmin embedded />
      </section>

      {/* 第 2 层：篇目（展开后内联管理第 3 层：句子） */}
      <section
        aria-labelledby="bank-passages"
        className="scroll-mt-6 space-y-4 rounded-2xl border border-primary/10 bg-card p-4 shadow-sm sm:p-6"
      >
        <h2
          id="bank-passages"
          className="scroll-mt-6 text-lg font-semibold text-primary"
        >
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
      <section
        id="bank-repeat"
        aria-label={t({ zh: "听句复述", en: "Listen & Repeat" })}
        className="scroll-mt-6 rounded-2xl border border-primary/10 bg-card p-4 shadow-sm sm:p-6"
      >
        <SentenceLibrary standaloneOnly />
      </section>

      {/* 情景问答：主题 → 问法，独立配套 */}
      <section
        aria-labelledby="bank-qa"
        className="scroll-mt-6 space-y-4 rounded-2xl border border-primary/10 bg-card p-4 shadow-sm sm:p-6"
      >
        <h2
          id="bank-qa"
          className="scroll-mt-6 text-lg font-semibold text-primary"
        >
          {t({ zh: "情景问答", en: "Scenario Q&A" })}
        </h2>
        <div className="flex flex-wrap gap-2 rounded-xl bg-muted/50 p-2 [&_button]:min-h-11">
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
