import { useMutation } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"
import { AdminService } from "@/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useI18n } from "@/lib/i18n"
import { extractErrorMessage } from "@/utils"

/** 文章拆句的子内容：组卷按句出题，学生逐句朗读；不能单独勾选或作为听句复述发布。 */
export function ReadingSentences({
  segments,
  seconds,
  passageId,
  onMutated,
}: {
  segments: string[]
  seconds?: (number | null)[] | null
  passageId?: string
  onMutated?: () => void
}) {
  const { t } = useI18n()
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
  if (segments.length === 0) return null
  return (
    <div className="space-y-2" data-testid="reading-sentences">
      <p className="text-sm font-medium">
        {t({
          zh: `朗读分句 · ${segments.length} 句`,
          en: `Reading sentences · ${segments.length}`,
        })}
      </p>
      <p className="text-xs text-muted-foreground">
        {t({
          zh: "选这篇文章即按句出题，学生逐句朗读。每句可设置 1–180 秒，留空使用自动时长；修改正文拆句内容后需重新设置。",
          en: "Selecting this article creates one question per sentence. Set 1–180 seconds per sentence, or leave blank for automatic timing. Changing sentence text resets these settings.",
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
            {passageId ? (
              <SentenceDuration
                key={`${index}-${seconds?.[index]}`}
                index={index}
                seconds={seconds?.[index] ?? null}
                pending={save.isPending}
                onSave={(value) => save.mutate({ index, value })}
              />
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
