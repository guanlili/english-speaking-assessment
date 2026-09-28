import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowLeft, BookOpenText, Ear, MessagesSquare } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { APP_NAME } from "@/config"
import { PassagesAdmin } from "./admin.passages"
import { QuestionsAdmin } from "./admin.questions"
import { ScenariosAdmin } from "./admin.scenarios"
import { UnitsAdmin } from "./admin.units"

const types = [
  {
    id: "reading",
    icon: BookOpenText,
    title: "文章朗读",
    description: "读文章或段落 · 录音批改",
  },
  {
    id: "repeat",
    icon: Ear,
    title: "听句复述",
    description: "听一句再复述 · 设置可听次数",
  },
  {
    id: "qa",
    icon: MessagesSquare,
    title: "情景问答",
    description: "情景问答 · 一问一答",
  },
] as const

export const Route = createFileRoute("/_layout/create")({
  validateSearch: (
    search: Record<string, unknown>,
  ): { kind: "reading" | "repeat" | "qa"; classroom?: string } => ({
    kind:
      search.kind === "repeat" || search.kind === "qa"
        ? search.kind
        : "reading",
    classroom:
      typeof search.classroom === "string" &&
      /^[a-zA-Z0-9_-]{1,16}$/.test(search.classroom)
        ? search.classroom
        : undefined,
  }),
  component: QuestionLibrary,
  head: () => ({ meta: [{ title: `题目库 - ${APP_NAME}` }] }),
})

function QuestionLibrary() {
  const { kind, classroom } = Route.useSearch()
  const navigate = Route.useNavigate()
  const [qaMode, setQaMode] = useState<"topics" | "questions">("topics")
  return (
    <div className="space-y-7">
      {classroom && (
        <Link
          to="/t/$code"
          params={{ code: classroom }}
          className="inline-flex items-center gap-2 text-sm font-medium text-primary"
        >
          <ArrowLeft className="size-4" />
          返回课堂 {classroom}，安排练习
        </Link>
      )}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="mb-2 text-xs font-semibold tracking-widest text-primary">
            准备教学内容
          </p>
          <h1 className="text-3xl font-bold">题目库</h1>
          <p className="mt-3 text-sm text-muted-foreground">
            选择一种题型开始出题。内容保存后，可在课堂中组合使用。
          </p>
        </div>
        {!classroom && (
          <Button asChild variant="outline">
            <Link to="/classrooms">去课堂安排练习</Link>
          </Button>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        {types.map((type) => (
          <button
            key={type.id}
            type="button"
            id={`type-${type.id}`}
            aria-pressed={kind === type.id}
            aria-controls="question-library-panel"
            onClick={() =>
              void navigate({
                search: { kind: type.id, classroom },
                replace: true,
              })
            }
            className={`flex items-start gap-4 rounded-2xl border p-5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-primary ${kind === type.id ? "border-primary bg-primary/5 ring-1 ring-primary" : "bg-card hover:border-primary/40"}`}
          >
            <type.icon className="mt-1 size-6 shrink-0 text-primary" />
            <div>
              <p className="font-semibold">{type.title}</p>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                {type.description}
              </p>
            </div>
          </button>
        ))}
      </div>
      <section
        id="question-library-panel"
        aria-labelledby={`type-${kind}`}
        className="rounded-2xl border bg-card p-4 md:p-6"
      >
        {kind === "qa" ? (
          <div className="space-y-5">
            <div className="flex flex-wrap gap-2">
              <Button
                variant={qaMode === "topics" ? "secondary" : "ghost"}
                onClick={() => setQaMode("topics")}
              >
                按主题出题 / AI 起草
              </Button>
              <Button
                variant={qaMode === "questions" ? "secondary" : "ghost"}
                onClick={() => setQaMode("questions")}
              >
                搜索、编辑与批量录入
              </Button>
            </div>
            {qaMode === "topics" ? (
              <ScenariosAdmin embedded />
            ) : (
              <QuestionsAdmin embedded />
            )}
          </div>
        ) : (
          <PassagesAdmin key={kind} embedded mode={kind} />
        )}
      </section>
      <details className="rounded-xl border p-5">
        <summary className="cursor-pointer text-sm font-medium">
          整理配套内容 · 单元
        </summary>
        <p className="my-4 text-sm leading-6 text-muted-foreground">
          需要把篇目用于课堂时，在这里建一个单元，再将篇目放入该单元。问答按篇目主题自动配套；题型在课堂发布时选择。
        </p>
        <UnitsAdmin />
      </details>
      <p className="text-xs leading-6 text-muted-foreground">
        题目库由全校共享，编辑已使用的内容会影响后续练习。平台评分为教学参考，不代表官方考试成绩。
      </p>
    </div>
  )
}
