import { Bookmark, Loader2, RefreshCw, TriangleAlert } from "lucide-react"
import type { ReactNode } from "react"
import type { AttemptPublic } from "@/client"
import VocabBlock from "@/components/Practice/VocabBlock"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"

// PRD §4：三种分的来源必须在界面上写清
const ENGINE_LABELS: Record<string, string> = {
  mock: "演示模式 · 本地模拟引擎",
  ark: "转写来源 · 火山方舟（参考分）",
}

function ScoreItem({
  label,
  value,
}: {
  label: string
  value: number | null | undefined
}) {
  return (
    <div className="flex flex-col items-center gap-1">
      <span className="text-3xl font-bold tabular-nums">
        {value === null || value === undefined ? "–" : value}
      </span>
      <span className="text-sm text-muted-foreground">{label}</span>
    </div>
  )
}

interface RubricPayload {
  fluency?: number
  vocabulary?: number
  grammar?: number
  task?: number
  mock_score?: number
  upgrades?: string[]
}

function parseRubric(raw: unknown): RubricPayload | null {
  if (raw === null || raw === undefined || typeof raw !== "object") return null
  return raw as RubricPayload
}

/** 模拟分块（PRD US-08）：四维 + 0-9 模拟分 + 升级表达；无数据不出假分。 */
function RubricBlock({ rubric, engine }: { rubric: unknown; engine: string }) {
  const data = parseRubric(rubric)

  if (data === null) {
    // ark 引擎下模型没出分 → 如实显示暂缺，绝不出 0 分
    if (engine === "ark") {
      return (
        <div className="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">
          模拟分：本次建议暂缺（模型未返回）
        </div>
      )
    }
    return null
  }

  const dims: Array<[string, number | undefined]> = [
    ["流利", data.fluency],
    ["词汇", data.vocabulary],
    ["语法", data.grammar],
    ["任务", data.task],
  ]

  return (
    <div className="space-y-2 rounded-md border px-3 py-2">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="text-muted-foreground">模拟参考分（0–9）</span>
        <span className="text-2xl font-bold tabular-nums">
          {data.mock_score ?? "–"}
        </span>
        <span className="text-xs text-muted-foreground">
          非官方成绩，仅供练习参考
        </span>
      </div>
      <div className="flex flex-wrap gap-3 text-sm">
        {dims.map(([label, value]) => (
          <span key={label}>
            <span className="text-muted-foreground">{label} </span>
            {value ?? "–"}/4
          </span>
        ))}
      </div>
      {data.upgrades && data.upgrades.length > 0 && (
        <div className="space-y-1 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">更高级的说法</span>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs"
              onClick={() => {
                const key = "esa:saved-expressions"
                const saved = JSON.parse(
                  localStorage.getItem(key) ?? "[]",
                ) as string[]
                const merged = Array.from(
                  new Set([...saved, ...data.upgrades!]),
                )
                localStorage.setItem(key, JSON.stringify(merged))
              }}
            >
              <Bookmark />
              收藏表达
            </Button>
          </div>
          <ul className="list-disc space-y-1 pl-5">
            {data.upgrades.map((u) => (
              <li key={u}>{u}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function FeedbackCard({
  attempt,
  itemType = "passage",
  onRepractice,
  extraActions,
}: {
  attempt: AttemptPublic
  itemType?: "passage" | "repeat" | "question"
  onRepractice: () => void
  extraActions?: ReactNode
}) {
  if (attempt.status === "queued" || attempt.status === "scoring") {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-6">
          <Loader2 className="size-5 animate-spin text-muted-foreground" />
          <span className="text-muted-foreground">已提交，正在出反馈…</span>
        </CardContent>
      </Card>
    )
  }

  if (attempt.status === "failed") {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <TriangleAlert className="size-4 text-destructive" />
            这次没有评出来，可以再录
          </CardTitle>
        </CardHeader>
        <CardFooter className="gap-3">
          <Button onClick={onRepractice}>
            <RefreshCw />
            再录一次
          </Button>
          {extraActions}
        </CardFooter>
      </Card>
    )
  }

  // 开放问答无参考文本：只展示总评 + 一句建议（PRD §4：2 周形态）
  const isQuestion = itemType === "question"

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">反馈</CardTitle>
        <Badge variant="secondary">
          {ENGINE_LABELS[attempt.engine] ?? attempt.engine}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1">
          <span className="text-sm text-muted-foreground">
            你说了什么（转写）
          </span>
          <p className="leading-relaxed">
            {attempt.transcript || "（无转写内容）"}
          </p>
        </div>
        <Separator />
        {isQuestion ? (
          <div className="space-y-3 py-2">
            <ScoreItem label="总评（参考）" value={attempt.overall} />
            {/* 模拟分与升级表达（PRD US-08）：mock 引擎无数据不显示 */}
            <RubricBlock rubric={attempt.rubric} engine={attempt.engine} />
            {/* 词汇参考等级（PRD US-07）：未配置词表时如实提示 */}
            <VocabBlock vocab={attempt.vocab} />
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-2 py-2">
            <ScoreItem label="完整度" value={attempt.completeness} />
            <ScoreItem label="流利度" value={attempt.fluency} />
            <ScoreItem label="总评" value={attempt.overall} />
          </div>
        )}
        <Separator />
        {attempt.advice && attempt.advice.length > 0 && (
          <div className="space-y-1">
            <span className="text-sm text-muted-foreground">建议</span>
            <ul className="list-disc space-y-1 pl-5">
              {attempt.advice.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
      <CardFooter className="flex-col items-start gap-3">
        <p className="text-xs text-muted-foreground">
          参考反馈，不是考试成绩。
        </p>
        <div className="flex flex-wrap gap-3">
          <Button onClick={onRepractice} variant="outline">
            <RefreshCw />
            {isQuestion ? "重答这题" : "再练一次"}
          </Button>
          {extraActions}
        </div>
      </CardFooter>
    </Card>
  )
}

export default FeedbackCard
