import type { ReactNode } from "react"
import type { ExamStatus, PlanItem } from "@/client"
import CueCard from "@/components/Practice/CueCard"
import {
  ExamItemTimer,
  ExamPrepCountdown,
  PrepCountdownBlock,
} from "@/components/Practice/ExamCountdowns"
import LimitedListenButton from "@/components/Practice/LimitedListenButton"
import PromptTextBlock, {
  RepeatHint,
} from "@/components/Practice/PromptTextBlock"
import SentenceFrames from "@/components/Practice/SentenceFrames"
import SpeakButton from "@/components/Practice/SpeakButton"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { useI18n } from "@/lib/i18n"
import {
  EXAM_KIND_LABELS,
  EXAM_LEVEL_LABELS,
  ITEM_TYPE_LABELS,
} from "@/lib/terms"
import { formatSeconds } from "@/lib/time"

/**
 * 练习主卡（展示组件）：题型角标/作答限时、分级题型徽标、可替换句型、
 * IELTS Part 2 话题卡、准备倒计时、题面文本与听音/显示原文等控制。
 * 作答区（题目说明「继续」面板 / 录音区）的接线留在页面，经 footer
 * 注入——录音状态机与提交逻辑不动，只收敛题面展示。
 */
export default function PracticeItemCard({
  item,
  promptLabel,
  hint,
  isPassage,
  isInstruction,
  isQuestion,
  hideText,
  onToggleHideText,
  exam,
  syncedAt,
  examKind,
  examLevel,
  cueBullets,
  isIeltsPart2,
  prepDone,
  practicePrepLeft,
  onSkipPrep,
  code,
  sessionId,
  todayQueryKey,
  recordLimitSeconds,
  onNextQuestion,
  nextQuestionPending,
  footer,
}: {
  item: PlanItem
  /** 题面角标与作答提示（lib/practice-copy 解析结果） */
  promptLabel: string
  hint: string
  isPassage: boolean
  isInstruction: boolean
  isQuestion: boolean
  hideText: boolean
  onToggleHideText: () => void
  exam: ExamStatus | null
  syncedAt: number
  examKind: string | null
  examLevel: string | null
  cueBullets: string[]
  isIeltsPart2: boolean
  /** Part 2 准备是否结束（模考来自考试时钟，练习来自本地秒表） */
  prepDone: boolean
  practicePrepLeft: number
  onSkipPrep: () => void
  code: string
  sessionId: string | undefined
  todayQueryKey: readonly unknown[]
  recordLimitSeconds: number
  /** 问答题「再来一题」（换一题 US-06） */
  onNextQuestion: () => void
  nextQuestionPending: boolean
  /** 作答区：题目说明「继续」面板或录音区（含接线，由页面渲染） */
  footer: ReactNode
}) {
  const { t } = useI18n()
  return (
    <Card>
      <CardContent className="space-y-5 pt-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-semibold tracking-wide text-primary">
            {promptLabel}
          </span>
          <span className="rounded-md bg-background px-2 py-0.5 text-[11px] text-muted-foreground">
            {t(
              ITEM_TYPE_LABELS[item.type] ?? {
                zh: item.type,
                en: item.type,
              },
            )}
            {" · "}
            {t({ zh: "作答限时", en: "Answer limit" })}{" "}
            {formatSeconds(recordLimitSeconds)}
          </span>
        </div>

        {exam && <ExamItemTimer exam={exam} syncedAt={syncedAt} />}

        {/* 分级题型徽标：题型 × 级别（两维分别建模） */}
        {examKind && (
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="secondary">
              {t(
                EXAM_KIND_LABELS[examKind] ?? {
                  zh: examKind,
                  en: examKind,
                },
              )}
            </Badge>
            {examLevel && (
              <Badge variant="outline">
                {t(
                  EXAM_LEVEL_LABELS[examLevel] ?? {
                    zh: examLevel,
                    en: examLevel,
                  },
                )}
              </Badge>
            )}
          </div>
        )}

        {/* 可替换句型（PR B）：按表达用途分组，可收藏 */}
        {(item.frames?.length ?? 0) > 0 && (
          <SentenceFrames
            frames={item.frames ?? []}
            code={code}
            todayQueryKey={todayQueryKey}
          />
        )}

        {/* IELTS Part 2 话题卡 */}
        {isIeltsPart2 && cueBullets.length > 0 && (
          <CueCard bullets={cueBullets} />
        )}

        {/* Part 2 准备时间倒计时（结束或跳过后才能开始录音）：
            秒级展示下沉到 memo 组件——模考走考试时钟，练习走本地秒表 */}
        {isIeltsPart2 &&
          !prepDone &&
          (exam ? (
            <ExamPrepCountdown exam={exam} syncedAt={syncedAt} />
          ) : (
            <PrepCountdownBlock
              secondsLeft={practicePrepLeft}
              onSkip={onSkipPrep}
            />
          ))}

        <PromptTextBlock
          item={item}
          isInstruction={isInstruction}
          hideText={hideText}
          inExam={Boolean(exam)}
          hint={hint}
        />
        {item.type === "repeat" && <RepeatHint hint={hint} />}

        {!isInstruction &&
          (item.type === "repeat" ? (
            // 听音状态按 session_id + item_id 隔离：会话变化时重建计数状态，
            // 避免同一道题在新会话里沿用旧会话的已听次数。
            <LimitedListenButton
              key={`${sessionId ?? ""}:${item.id}`}
              code={code.toUpperCase()}
              sessionId={sessionId}
              itemId={item.id}
              text={item.text}
              audioUrl={item.audio_url}
              replayLimit={item.replay_limit ?? 3}
              initialUsed={item.listen_used ?? 0}
            />
          ) : (
            <SpeakButton
              key={item.id}
              text={item.text}
              audioUrl={item.audio_url}
            />
          ))}
        {isPassage && (
          <Button
            variant="ghost"
            size="sm"
            className="text-xs text-primary"
            onClick={onToggleHideText}
          >
            {hideText
              ? t({ zh: "显示原文", en: "Show text" })
              : t({
                  zh: "收起原文（练记忆）",
                  en: "Hide text (memory practice)",
                })}
          </Button>
        )}
        {isQuestion && !exam && (
          <Button
            variant="ghost"
            size="sm"
            className="text-xs text-primary"
            onClick={onNextQuestion}
            disabled={nextQuestionPending}
          >
            {t({
              zh: "再来一题（同主题，追加到本轮）",
              en: "One more question (same topic)",
            })}
          </Button>
        )}

        {footer}
      </CardContent>
    </Card>
  )
}
