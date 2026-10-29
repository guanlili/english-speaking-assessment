import { useMutation } from "@tanstack/react-query"
import { Loader2, Sparkles } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import { AdminService } from "@/client"
import AudioSetter from "@/components/Practice/AudioSetter"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useI18n } from "@/lib/i18n"
import { extractErrorMessage } from "@/utils"

/** 批量配音进度：done 含成功与失败，failed 只计失败。 */
type BatchState = {
  running: boolean
  done: number
  total: number
  failed: number
}

/** 文章拆句的子内容：组卷按句出题，学生逐句朗读；不能单独勾选或作为听句复述发布。 */
export function ReadingSentences({
  segments,
  seconds,
  audio,
  passageId,
  onMutated,
  readOnly = false,
}: {
  segments: string[]
  seconds?: (number | null)[] | null
  /** 按句子原文寻址的配音表：教师单句生成，学生端未配音句子走设备合成兜底 */
  audio?: Record<string, string> | null
  passageId?: string
  onMutated?: () => void
  readOnly?: boolean
}) {
  const { t } = useI18n()
  const [batch, setBatch] = useState<BatchState>({
    running: false,
    done: 0,
    total: 0,
    failed: 0,
  })
  const audioMap = audio ?? {}
  const voicedCount = segments.filter((text) => audioMap[text]).length
  const unvoicedCount = segments.length - voicedCount

  const save = useMutation({
    mutationFn: ({ index, value }: { index: number; value: number | null }) =>
      AdminService.updatePassage({
        passageId: passageId!,
        requestBody: {
          reading_sentence_texts: segments,
          reading_sentence_seconds: segments.map((_, i) =>
            i === index ? value : (seconds?.[i] ?? null),
          ),
        },
      }),
    onSuccess: async () => {
      toast.success(t({ zh: "时长已保存", en: "Duration saved" }))
      await onMutated?.()
    },
    onError: (err) => toast.error(extractErrorMessage(err)),
  })
  const saveAudio = useMutation({
    mutationFn: ({ text, url }: { text: string; url: string | null }) => {
      // 按原文寻址：清音删键；后端按当前分句修剪失配旧键
      const next: Record<string, string> = { ...(audio ?? {}) }
      if (url === null) delete next[text]
      else next[text] = url
      return AdminService.updatePassage({
        passageId: passageId!,
        requestBody: {
          reading_sentence_texts: segments,
          reading_sentence_audio: next,
        },
      })
    },
    // 成功提示由 AudioSetter 统一给出（生成/上传/清除各有文案）
    onSuccess: async () => {
      await onMutated?.()
    },
    onError: (err) => toast.error(extractErrorMessage(err)),
  })

  /** 一键配音：只为未配音句子逐句生成（顺序执行），每句独立落库，
   * 中断/失败均可再次点击续跑（自动跳过已配音句子）。 */
  async function runBatch() {
    const targets = segments.filter((text) => !audioMap[text])
    if (targets.length === 0 || !passageId) return
    setBatch({ running: true, done: 0, total: targets.length, failed: 0 })
    let dict: Record<string, string> = { ...audioMap }
    let failed = 0
    for (const text of targets) {
      try {
        const res = await AdminService.generateStandardAudio({
          requestBody: { text },
        })
        if (!res.audio_url) throw new Error("tts empty audio_url")
        dict = { ...dict, [text]: res.audio_url }
        await AdminService.updatePassage({
          passageId,
          requestBody: {
            reading_sentence_texts: segments,
            reading_sentence_audio: dict,
          },
        })
        await onMutated?.()
      } catch {
        failed += 1
      }
      setBatch((b) => ({ ...b, done: b.done + 1, failed }))
    }
    setBatch((b) => ({ ...b, running: false }))
    if (failed === 0) {
      toast.success(
        t({
          zh: `批量配音完成（${targets.length} 句）`,
          en: `Batch voiceover done (${targets.length} sentences)`,
        }),
      )
    } else {
      toast.error(
        t({
          zh: `${failed} 句配音失败（TTS 可能未配置或网络异常）；已成功的句子已保存，可点击重试续跑`,
          en: `${failed} sentence(s) failed (TTS unavailable or network error); successes are saved — click again to retry the rest`,
        }),
      )
    }
  }

  if (segments.length === 0) return null
  return (
    <div className="space-y-2" data-testid="reading-sentences">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-medium">
          {t({
            zh: `朗读分句 · ${segments.length} 句 · 已配音 ${voicedCount}`,
            en: `Reading sentences · ${segments.length} · ${voicedCount} voiced`,
          })}
        </p>
        {passageId && !readOnly && batch.running && (
          <span
            className="flex items-center gap-1 text-xs text-muted-foreground"
            data-testid="reading-batch-progress"
          >
            <Loader2 className="size-3.5 animate-spin" />
            {t({
              zh: `配音中 ${batch.done}/${batch.total}`,
              en: `Voicing ${batch.done}/${batch.total}`,
            })}
          </span>
        )}
        {passageId && !readOnly && !batch.running && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="min-h-11"
            disabled={unvoicedCount === 0}
            title={t({
              zh: "按句计费；只为未配音的句子生成，已配音句子不会重复计费",
              en: "Charged per sentence; only unvoiced sentences are generated",
            })}
            onClick={() => {
              void runBatch()
            }}
          >
            <Sparkles className="size-3.5" />
            {unvoicedCount === 0
              ? t({ zh: "已全部配音", en: "All voiced" })
              : t({
                  zh: `一键配音（未配音 ${unvoicedCount} 句）`,
                  en: `Voice all (${unvoicedCount} left)`,
                })}
          </Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        {t({
          zh: "选这篇文章即按句出题，学生逐句朗读。每句可设置 1–180 秒（留空使用自动时长）并单独生成配音；修改正文拆句内容后需重新设置时长，改动过的句子需重新配音。",
          en: "Selecting this article creates one question per sentence. Set 1–180 seconds per sentence (or leave blank for automatic timing) and generate audio for each. Changing sentence text resets durations, and edited sentences need new audio.",
        })}
      </p>
      <ol className="ml-2 space-y-2 border-l-2 pl-3 sm:ml-4 sm:pl-4">
        {segments.map((text, index) => (
          <li
            key={`${index}-${text}`}
            className="flex min-w-0 flex-wrap items-center gap-3 rounded-lg border bg-card p-3 text-sm"
          >
            <span className="shrink-0 text-muted-foreground">{index + 1}.</span>
            <p className="min-w-0 flex-1 basis-64 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
              {text}
            </p>
            {!audioMap[text] && (
              <span
                className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                data-testid="reading-sentence-unvoiced"
              >
                {t({ zh: "未配音", en: "Unvoiced" })}
              </span>
            )}
            {passageId && !readOnly ? (
              <>
                <SentenceDuration
                  key={`${index}-${seconds?.[index]}`}
                  index={index}
                  seconds={seconds?.[index] ?? null}
                  pending={save.isPending}
                  onSave={(value) => save.mutate({ index, value })}
                />
                {!batch.running && (
                  <AudioSetter
                    audioUrl={audioMap[text]}
                    text={text}
                    onSet={(url) => saveAudio.mutateAsync({ text, url })}
                  />
                )}
              </>
            ) : seconds?.[index] != null ? (
              <span>
                {t({ zh: `${seconds[index]} 秒`, en: `${seconds[index]}s` })}
              </span>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  )
}

function SentenceDuration({
  index,
  seconds,
  pending,
  onSave,
}: {
  index: number
  seconds: number | null
  pending: boolean
  onSave: (value: number | null) => void
}) {
  const { t } = useI18n()
  const [value, setValue] = useState(seconds?.toString() ?? "")
  return (
    <form
      className="flex items-center gap-2"
      onSubmit={(event) => {
        event.preventDefault()
        onSave(value === "" ? null : Number(value))
      }}
    >
      <Input
        type="number"
        min={1}
        max={180}
        step={1}
        value={value}
        disabled={pending}
        onChange={(event) => setValue(event.target.value)}
        placeholder={t({ zh: "自动", en: "Auto" })}
        aria-label={t({
          zh: `第 ${index + 1} 句作答时长（秒）`,
          en: `Sentence ${index + 1} answer duration (seconds)`,
        })}
        className="min-h-11 w-24 text-base"
      />
      <span>{t({ zh: "秒", en: "sec" })}</span>
      <Button
        type="submit"
        variant="outline"
        className="min-h-11"
        disabled={pending || value === (seconds?.toString() ?? "")}
      >
        {t({ zh: "保存", en: "Save" })}
      </Button>
    </form>
  )
}
