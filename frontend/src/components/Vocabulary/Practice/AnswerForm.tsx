import type { RefObject } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useI18n } from "@/lib/i18n"

/**
 * 作答区（未答）：输入 + 提交表单。练习与测验共用，按钮文案随模式。
 * 禁用条件由页面汇总传入（会话缺失/只读/判分中/空输入）。
 */
export default function AnswerForm({
  input,
  onInputChange,
  onSubmit,
  inputRef,
  submitPending,
  isQuiz,
  inputDisabled,
  submitDisabled,
}: {
  input: string
  onInputChange: (value: string) => void
  onSubmit: (event: React.FormEvent) => void
  inputRef: RefObject<HTMLInputElement | null>
  submitPending: boolean
  isQuiz: boolean
  inputDisabled: boolean
  submitDisabled: boolean
}) {
  const { t } = useI18n()
  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3 sm:flex-row">
      <label className="sr-only" htmlFor="vocab-answer">
        {t({ zh: "输入英文单词", en: "Type the English word" })}
      </label>
      <Input
        id="vocab-answer"
        ref={inputRef}
        value={input}
        onChange={(event) => onInputChange(event.target.value)}
        placeholder={t({
          zh: "在这里输入英文单词…",
          en: "Type the English word here…",
        })}
        autoComplete="off"
        autoCapitalize="off"
        spellCheck={false}
        className="h-12 flex-1 text-base"
        disabled={inputDisabled}
      />
      <Button type="submit" className="h-12 px-6" disabled={submitDisabled}>
        {submitPending
          ? t({ zh: "判分中…", en: "Checking…" })
          : t(
              isQuiz
                ? { zh: "提交答案", en: "Submit answer" }
                : { zh: "提交", en: "Submit" },
            )}
      </Button>
    </form>
  )
}
