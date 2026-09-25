import { useMutation, useQuery } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  useNavigate,
  useParams,
} from "@tanstack/react-router"
import { ArrowRight, Repeat, Shuffle } from "lucide-react"
import { useMemo } from "react"
import type { PlanAttempt, PlanItem } from "@/client"
import { ClassesService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { APP_NAME } from "@/config"
import { displayName, loadStudent } from "@/lib/classroom-student"

export const Route = createFileRoute("/p/$code/result")({
  component: RoundResultPage,
  head: () => ({
    meta: [{ title: `本轮结果 - ${APP_NAME}` }],
  }),
})

const ITEM_TYPE_LABELS: Record<string, string> = {
  repeat: "听后复述",
  question: "情景问答",
}

function RoundResultPage() {
  const { code } = useParams({ from: "/p/$code/result" })
  const navigate = useNavigate({ from: "/p/$code/result" })
  const student = loadStudent(code)

  const todayQuery = useQuery({
    queryKey: ["classroom", code, "today", student?.id],
    queryFn: () =>
      ClassesService.readTodayPlan({
        code: code.toUpperCase(),
        studentId: student?.id as string,
      }),
    enabled: student !== null,
  })

  const nextQuestionMutation = useMutation({
    mutationFn: () =>
      // 换题逻辑统一在练习页执行（?next=1），这里仅做跳转
      Promise.resolve(null),
    onSuccess: () => {
      void navigate({
        to: "/p/$code",
        params: { code },
        search: { next: true },
      })
    },
  })

  const plan = todayQuery.data
  const { doneItems, weakest } = useMemo(() => {
    const empty: { item: PlanItem; attempt: PlanAttempt }[] = []
    if (!plan) return { doneItems: empty, weakest: null as string | null }
    const map = new Map<string, PlanAttempt>(
      plan.attempts.map((a) => [a.item_id, a]),
    )
    const scored = plan.items.flatMap((item) => {
      const attempt = map.get(item.id)
      if (attempt === undefined || attempt.status !== "done") return []
      return [{ item, attempt }]
    })
    let weakestId: string | null = null
    let minOverall = Number.POSITIVE_INFINITY
    for (const row of scored) {
      const overall = row.attempt.overall
      if (overall !== null && overall !== undefined && overall < minOverall) {
        minOverall = overall
        weakestId = row.item.id
      }
    }
    return { doneItems: scored, weakest: weakestId }
  }, [plan])

  if (student === null) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        <Button variant="outline" asChild>
          <Link to="/j/$code" params={{ code }}>
            先进入课堂
          </Link>
        </Button>
      </div>
    )
  }

  if (todayQuery.isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        正在加载结果…
      </div>
    )
  }
  if (todayQuery.isError || !plan) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        结果加载失败，请刷新重试。
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 p-6">
        <div>
          <h1 className="text-xl font-bold tracking-tight">本轮结果</h1>
          <p className="text-sm text-muted-foreground">
            {displayName(student)} · 课堂 {plan.classroom_code} · 每题转写和总评
          </p>
        </div>

        {doneItems.length === 0 && (
          <Card>
            <CardContent className="py-6 text-muted-foreground">
              还没有完成的作答。回到练习页开始第一题。
            </CardContent>
          </Card>
        )}

        {doneItems.map(({ item, attempt }, index) => (
          <Card key={item.id}>
            <CardHeader>
              <CardDescription>
                {index + 1}. {ITEM_TYPE_LABELS[item.type] ?? item.type}
                {item.band ? ` · ${item.band}` : ""}
              </CardDescription>
              <CardTitle className="text-sm leading-relaxed font-medium">
                {item.text}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm leading-relaxed">
                <span className="text-muted-foreground">转写：</span>
                {attempt.transcript || "（无）"}
              </p>
              <Separator />
              <div className="flex items-center gap-4 text-sm">
                <span className="text-2xl font-bold tabular-nums">
                  总评 {attempt.overall ?? "–"}
                </span>
                {item.type !== "question" && (
                  <span className="text-muted-foreground">
                    完整度 {attempt.completeness ?? "–"} · 流利度{" "}
                    {attempt.fluency ?? "–"}
                  </span>
                )}
              </div>
              {attempt.advice && attempt.advice.length > 0 && (
                <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                  {attempt.advice.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        ))}

        <div className="flex flex-wrap gap-3">
          {weakest && (
            <Button
              variant="outline"
              onClick={() =>
                void navigate({
                  to: "/p/$code",
                  params: { code },
                  search: { focus: weakest },
                })
              }
            >
              <Repeat />
              重练最弱的一题
            </Button>
          )}
          <Button
            onClick={() => nextQuestionMutation.mutate()}
            disabled={
              nextQuestionMutation.isPending ||
              plan.questions_exhausted === true
            }
          >
            <Shuffle />
            {plan.questions_exhausted === true
              ? "这个主题的题已练完"
              : "换同主题下一问"}
          </Button>
          <Button variant="ghost" asChild>
            <Link to="/p/$code" params={{ code }}>
              回练习页
              <ArrowRight />
            </Link>
          </Button>
        </div>

        <p className="pb-6 text-center text-xs text-muted-foreground">
          参考反馈，不是考试成绩。
        </p>
      </div>
    </div>
  )
}
