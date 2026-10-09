import { ArrowRight, Mic, Square } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { useRecorder } from "@/hooks/useRecorder"
import { useI18n } from "@/lib/i18n"
import { EXAM_PRACTICE_NOTE } from "@/lib/terms"
import { formatSeconds } from "@/lib/time"

/**
 * 录音区（Charcoal：大圆钮 + 波形）：
 * 录音中（波形+停止）/ 上传失败待重传 / 待开始（大麦克风钮）三态。
 * 按钮 aria-label 双语；圆钮 72px 触控目标。
 */
export default function RecordArea({
  recorder,
  recordLimitSeconds,
  examKind,
  inExam,
  examActive,
  examEnded,
  itemExpired,
  currentItemDone,
  prepDone,
  scoring,
  attemptFailed,
  isLastQuestion,
  submitting,
  submitError,
  onStart,
  onStop,
  onRetry,
  onExpiredContinue,
}: {
  recorder: ReturnType<typeof useRecorder>
  recordLimitSeconds: number
  examKind: string | null
  inExam: boolean
  examActive: boolean
  examEnded: boolean
  itemExpired: boolean
  currentItemDone: boolean
  prepDone: boolean
  scoring: boolean
  attemptFailed: boolean
  isLastQuestion: boolean
  submitting: boolean
  submitError: boolean
  onStart: () => void
  onStop: () => void
  onRetry: () => void
  onExpiredContinue: () => void
}) {
  const { t } = useI18n()
  return (
    <div className="flex flex-col items-center gap-1 border-t pt-5 text-center">
      {examKind && (
        <p className="mb-2 text-[11px] text-muted-foreground">
          {t(EXAM_PRACTICE_NOTE)}
        </p>
      )}
      {recorder.status === "recording" ? (
        <>
          <div
            className="flex h-8 items-center justify-center gap-1"
            aria-hidden
          >
            {Array.from({ length: 25 }).map((_, i) => (
              <i
                key={i}
                className="wave-bar block w-[3px] rounded bg-primary"
                style={{
                  height: `${[7, 20, 29, 13, 18, 24, 10, 16, 28, 12][i % 10]}px`,
                  animationDelay: `${(i % 5) * -0.2}s`,
                }}
              />
            ))}
          </div>
          <button
            type="button"
            onClick={onStop}
            aria-label={t({ zh: "结束录音", en: "Stop recording" })}
            className="record-pulse mt-3 grid size-[72px] place-items-center rounded-full bg-destructive text-white shadow-[0_0_0_7px_var(--accent)] transition hover:scale-105"
          >
            <Square className="size-7" />
          </button>
          <p className="mt-4 text-sm">
            <span className="font-mono tabular-nums">
              {formatSeconds(recorder.elapsed)}
            </span>{" "}
            {t({
              zh: "· 说完后点一下结束",
              en: "· Tap stop when you're done",
            })}
          </p>
          <p className="text-xs text-muted-foreground">
            {t({
              zh: `本题限时 ${formatSeconds(recordLimitSeconds)} · 到时自动结束录音${inExam ? "并进入下一题" : ""}`,
              en: `This item's limit is ${formatSeconds(recordLimitSeconds)} · recording stops automatically${inExam ? " and the next item opens" : ""}`,
            })}
          </p>
        </>
      ) : submitError && recorder.recording ? (
        <>
          <button
            type="button"
            onClick={onRetry}
            disabled={submitting}
            aria-label={t({
              zh: "重传录音",
              en: "Retry uploading recording",
            })}
            className="mt-1 grid size-[72px] place-items-center rounded-full bg-primary text-white shadow-[0_0_0_7px_var(--secondary)] transition hover:scale-105 disabled:opacity-50"
          >
            <ArrowRight className="size-7" />
          </button>
          <p className="mt-4 text-sm text-destructive">
            {t({
              zh: "上传失败，录音已保留",
              en: "Upload failed — your recording is saved",
            })}
          </p>
          <p className="text-xs text-muted-foreground">
            {t({
              zh: inExam ? "仅可重传原录音，不能重新作答" : "点这里重传 · 或",
              en: inExam
                ? "Retry the original upload; this item cannot be answered again"
                : "Tap to retry · or",
            })}
            {!inExam && (
              <button
                type="button"
                onClick={onStart}
                className="ml-1 underline text-primary"
              >
                {t({ zh: "重新录", en: "record again" })}
              </button>
            )}
          </p>
          {inExam && itemExpired && (
            <Button
              variant="outline"
              className="min-h-11"
              onClick={onExpiredContinue}
            >
              {t({
                zh: "本题已到时，继续考试",
                en: "Time is up — continue the exam",
              })}
            </Button>
          )}
        </>
      ) : (
        <>
          <button
            type="button"
            onClick={onStart}
            disabled={
              scoring ||
              (examActive && currentItemDone) ||
              examEnded ||
              itemExpired ||
              !prepDone
            }
            aria-label={t({ zh: "开始录音", en: "Start recording" })}
            className="mt-1 grid size-[72px] place-items-center rounded-full bg-primary text-white shadow-[0_0_0_7px_var(--secondary)] transition hover:scale-105 disabled:opacity-50"
          >
            <Mic className="size-7" />
          </button>
          <p className="mt-4 text-sm">
            {examEnded
              ? t({ zh: "考试已结束", en: "The exam has ended" })
              : examActive && currentItemDone
                ? t({
                    zh: "本题已作答，考试中不能重录",
                    en: "Already answered — one attempt per item",
                  })
                : scoring
                  ? t({
                      zh: "已提交，正在出反馈…",
                      en: "Submitted — feedback is on its way…",
                    })
                  : recorder.status === "ready"
                    ? t({
                        zh: "这一次开口，已记录",
                        en: "This speaking attempt is recorded",
                      })
                    : !prepDone
                      ? t({
                          zh: "先利用准备时间组织思路",
                          en: "Use the prep time to organise your ideas",
                        })
                      : t({
                          zh: "准备好了，就点一下麦克风",
                          en: "When you're ready, tap the microphone",
                        })}
          </p>
          {scoring ? (
            <p className="text-xs text-muted-foreground">
              {inExam
                ? t({
                    zh: "正在上传录音，上传后自动继续；反馈将在考试结束后汇总",
                    en: "Uploading your recording, then continuing automatically. Feedback appears after the exam.",
                  })
                : isLastQuestion
                  ? t({
                      zh: "先显示本题分数和转写",
                      en: "Showing this item's score and transcript first",
                    })
                  : t({
                      zh: "先显示本题分数和转写，详细评价最后看",
                      en: "Score and transcript first — full feedback at the end",
                    })}
            </p>
          ) : attemptFailed && !inExam ? (
            <p className="text-xs text-destructive">
              {t({
                zh: "这次没有评出来，再录一次就好",
                en: "No score this time — just record again",
              })}
            </p>
          ) : (
            <p className="text-xs text-muted-foreground">
              {t({
                zh: "需要麦克风权限 · 每一次练习都有意义",
                en: "Microphone permission needed · Every practice counts",
              })}
            </p>
          )}
        </>
      )}
      {recorder.error && (
        <p className="mt-1 text-sm text-destructive">{recorder.error}</p>
      )}
    </div>
  )
}
