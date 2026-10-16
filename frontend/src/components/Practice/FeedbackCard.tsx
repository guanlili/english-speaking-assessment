import { Bookmark, Loader2, RefreshCw, TriangleAlert } from "lucide-react"
import { type ReactNode, useState } from "react"
import type { AttemptPublic } from "@/client"
import InfoHint from "@/components/Common/InfoHint"
import { TeacherFeedbackBlock } from "@/components/Practice/TeacherFeedbackBlock"
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
import type { BiString } from "@/lib/bi"
import { adviceText, type BilingualAdvice } from "@/lib/bilingual"
import { useI18n } from "@/lib/i18n"
import { EXPLAIN } from "@/lib/terms"

// PRD §4：三种分的来源必须在界面上写清（作答级来源徽标，教师逐题反馈弹窗复用）
export const ENGINE_LABELS: Record<string, BiString> = {
  mock: {
    zh: "演示模式 · 本地模拟引擎",
    en: "Demo mode · local simulated engine",
  },
  volc_flash: {
    zh: "转写来源 · 豆包语音极速版（参考分）",
    en: "Transcript source · Doubao Speech Flash (reference score)",
  },
  ark: {
    zh: "转写来源 · 火山方舟（参考分）",
    en: "Transcript source · Volcengine Ark (reference score)",
  },
}

function ScoreItem({
  label,
  value,
  hint,
}: {
  label: string
  value: number | null | undefined
  hint?: string
}) {
  return (
    <div className="flex flex-col items-center gap-1">
      <span className="text-3xl font-bold tabular-nums">
        {value === null || value === undefined ? "–" : value}
      </span>
      <span className="flex items-center gap-1 text-sm text-muted-foreground">
        {label}
        {hint ? <InfoHint label={hint} /> : null}
      </span>
    </div>
  )
}

interface RubricPayload {
  fluency?: number
  vocabulary?: number
  grammar?: number
  task?: number
  mock_score?: number
  /** 批次10：新结构为 {zh,en} 双语；旧模型输出是纯字符串，原样展示 */
  advice?: Array<string | BilingualAdvice>
  status?: string
  upgrades?: string[]
  /** 评分来源元数据（批次10）；历史行缺省按 legacy 展示 */
  model?: string
  prompt_version?: number
  asr?: string
}

function parseRubric(raw: unknown): RubricPayload | null {
  if (raw === null || raw === undefined || typeof raw !== "object") return null
  return raw as RubricPayload
}

/** 模拟分块（PRD US-08）：四维 + 0-9 模拟分 + 升级表达；无数据不出假分。 */
export function RubricBlock({
  rubric,
  engine,
  onSaveUpgrades,
}: {
  rubric: unknown
  engine: string
  /** 保存成功返回 true。失败返回 false，按钮保持可重试。 */
  onSaveUpgrades?: (texts: string[]) => Promise<boolean>
}) {
  const { t, lang } = useI18n()
  const data = parseRubric(rubric)
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)

  if (data?.status === "pending" || data?.status === "unavailable") {
    return (
      <p className="text-sm text-muted-foreground">
        {data.status === "pending"
          ? t({
              zh: "详细评价正在生成…",
              en: "Detailed feedback is being generated…",
            })
          : t({
              zh: "详细评价暂缺，请稍后再试。",
              en: "Detailed feedback is unavailable — please try again later.",
            })}
      </p>
    )
  }

  if (data === null) {
    // ark 引擎下模型没出分 → 如实显示暂缺，绝不出 0 分
    if (engine === "ark") {
      return (
        <div className="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">
          {t({
            zh: "模拟分：本次建议暂缺（模型未返回）",
            en: "Mock score: unavailable this time (model returned none)",
          })}
        </div>
      )
    }
    return null
  }

  const dims: Array<[string, number | undefined]> = [
    [t({ zh: "流利", en: "Fluency" }), data.fluency],
    [t({ zh: "词汇", en: "Vocabulary" }), data.vocabulary],
    [t({ zh: "语法", en: "Grammar" }), data.grammar],
    [t({ zh: "任务", en: "Task" }), data.task],
  ]

  return (
    <div className="space-y-2 rounded-md border px-3 py-2">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="text-muted-foreground">
          {t({ zh: "模拟分（0–9）", en: "Mock score (0–9)" })}
          <InfoHint label={t(EXPLAIN.mock_caliber)} />
        </span>
        <span className="text-2xl font-bold tabular-nums">
          {data.mock_score ?? "–"}
        </span>
        <span className="text-xs text-muted-foreground">
          {t({
            zh: "非官方成绩，仅供练习参考",
            en: "Unofficial — for practice reference only",
          })}
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
      {data.advice?.length ? (
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {data.advice.map((item) => {
            const line = adviceText(item, lang)
            return line ? <li key={line}>{line}</li> : null
          })}
        </ul>
      ) : null}
      {data.upgrades && data.upgrades.length > 0 && (
        <div className="space-y-1 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">
              {t({ zh: "更高级的说法", en: "More advanced ways to say it" })}
            </span>
            {onSaveUpgrades ? (
              <Button
                variant="ghost"
                size="sm"
                className="text-xs"
                disabled={saving || saved || !data.upgrades?.length}
                onClick={() => {
                  const upgrades = data.upgrades
                  if (!upgrades?.length) return
                  setSaving(true)
                  void onSaveUpgrades(upgrades)
                    .then((savedNow) => {
                      if (savedNow) setSaved(true)
                    })
                    .catch(() => {
                      // 调用方负责提示；这里只保证失败后仍可再点
                    })
                    .finally(() => setSaving(false))
                }}
              >
                <Bookmark />
                {saved
                  ? t({ zh: "已收藏", en: "Saved" })
                  : t({ zh: "收藏表达", en: "Save expression" })}
              </Button>
            ) : null}
          </div>
          <ul className="list-disc space-y-1 pl-5">
            {data.upgrades.map((u) => (
              <li key={u}>{u}</li>
            ))}
          </ul>
        </div>
      )}
      {/* 评分来源（批次10）：模拟分由哪个模型评出；历史行无元数据标 legacy */}
      <p className="text-xs text-muted-foreground">
        {data.model
          ? t({
              zh: `模拟分来源：${data.model}（提示词 v${data.prompt_version ?? "?"}，转写 ${data.asr ?? "?"}）`,
              en: `Mock score by ${data.model} (prompt v${data.prompt_version ?? "?"}, ASR ${data.asr ?? "?"})`,
            })
          : t({
              zh: "模拟分来源：历史记录（未记录模型版本）",
              en: "Mock score: legacy record (model not recorded)",
            })}
      </p>
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
  const { t } = useI18n()
  if (attempt.status === "queued" || attempt.status === "scoring") {
    return (
      <Card>
        <TeacherFeedbackBlock attempt={attempt} />
        <CardContent className="flex items-center gap-3 py-6">
          <Loader2 className="size-5 animate-spin text-muted-foreground" />
          <span className="text-muted-foreground">
            {t({
              zh: "已提交，正在出反馈…",
              en: "Submitted — feedback is on its way…",
            })}
          </span>
        </CardContent>
      </Card>
    )
  }

  if (attempt.status === "failed") {
    return (
      <Card>
        <TeacherFeedbackBlock attempt={attempt} />
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <TriangleAlert className="size-4 text-destructive" />
            {t({
              zh: "这次没有评出来，可以再录",
              en: "No score this time — you can record again",
            })}
          </CardTitle>
        </CardHeader>
        <CardFooter className="gap-3">
          <Button onClick={onRepractice}>
            <RefreshCw />
            {t({ zh: "再录一次", en: "Record again" })}
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
      <TeacherFeedbackBlock attempt={attempt} />
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">
          {t({ zh: "反馈", en: "Feedback" })}
        </CardTitle>
        <Badge variant="secondary">
          {t(
            ENGINE_LABELS[attempt.engine] ?? {
              zh: attempt.engine,
              en: attempt.engine,
            },
          )}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1">
          <span className="text-sm text-muted-foreground">
            {t({
              zh: "你说了什么（转写）",
              en: "What you said (transcript)",
            })}
          </span>
          <p className="leading-relaxed">
            {attempt.transcript ||
              t({ zh: "（无转写内容）", en: "(no transcript)" })}
          </p>
        </div>
        <Separator />
        <ScoreItem
          label={t({ zh: "本次参考分 / 100", en: "Reference score / 100" })}
          value={attempt.overall}
          hint={t(EXPLAIN.reference_caliber)}
        />
      </CardContent>
      <CardFooter className="flex-col items-start gap-3">
        <p className="text-xs text-muted-foreground">
          {t({
            zh: "参考反馈，不是考试成绩。",
            en: "Reference feedback, not exam results.",
          })}
        </p>
        <div className="flex flex-wrap gap-3">
          <Button onClick={onRepractice} variant="outline">
            <RefreshCw />
            {isQuestion
              ? t({ zh: "重答这题", en: "Answer again" })
              : t({ zh: "再练一次", en: "Practice again" })}
          </Button>
          {extraActions}
        </div>
      </CardFooter>
    </Card>
  )
}

export default FeedbackCard
