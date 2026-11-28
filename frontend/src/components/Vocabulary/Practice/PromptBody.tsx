import type { VocabularyTodayItem } from "@/client"
import { Badge } from "@/components/ui/badge"
import { CefrBandBadge } from "@/components/Vocabulary/WordTagBadges"
import { useI18n } from "@/lib/i18n"
import { VOCAB_PROMPT_META, vocabPromptMeta } from "@/lib/terms"

/** 词块类型 → 双语小标签（词根拼装题面用） */
const SEGMENT_KIND: Record<string, { zh: string; en: string }> = {
  prefix: { zh: "前缀", en: "prefix" },
  root: { zh: "词根", en: "root" },
  suffix: { zh: "后缀", en: "suffix" },
}

/**
 * 四类新玩法的题面（英译中/中译英/语境填空/词根拼装）。
 *
 * 只渲染题面本身，作答控件（选项按钮 / 拼写输入）由页面决定；
 * 释义与拼写在答前是否出现由服务端下发决定，这里不自行判断。
 */
export default function PromptBody({ item }: { item: VocabularyTodayItem }) {
  const { t } = useI18n()
  const promptType = item.prompt_type

  if (promptType === "en_zh") {
    return (
      <div className="rounded-2xl bg-secondary/50 p-5 sm:p-6">
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          {item.part_of_speech && (
            <Badge variant="outline">{item.part_of_speech}</Badge>
          )}
          <CefrBandBadge band={item.cefr_band} compact />
        </div>
        <p className="break-words font-serif text-2xl font-semibold leading-snug tracking-wide sm:text-3xl">
          {item.headword}
        </p>
        <p className="mt-2 text-xs text-muted-foreground">
          {t({
            zh: "选出这个单词正确的中文释义。",
            en: "Pick the correct Chinese meaning of this word.",
          })}
        </p>
      </div>
    )
  }

  if (promptType === "zh_en") {
    return (
      <div className="rounded-2xl bg-secondary/50 p-5 sm:p-6">
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          {item.part_of_speech && (
            <Badge variant="outline">{item.part_of_speech}</Badge>
          )}
          <CefrBandBadge band={item.cefr_band} compact />
        </div>
        <p className="text-xl font-semibold leading-snug sm:text-2xl">
          {item.meaning_zh}
        </p>
        {item.meaning_en && (
          <p className="mt-1.5 text-sm text-muted-foreground">
            {item.meaning_en}
          </p>
        )}
        <p className="mt-2 text-xs text-muted-foreground">
          {t({
            zh: "选出对应的英文单词。",
            en: "Pick the English word that matches.",
          })}
        </p>
      </div>
    )
  }

  if (promptType === "cloze") {
    const parts = (item.cloze_sentence ?? "").split("____")
    return (
      <div className="rounded-2xl bg-secondary/50 p-5 sm:p-6">
        <p className="text-lg leading-relaxed sm:text-xl">
          {parts.map((part, index) => (
            <span key={`${index}-${part.slice(0, 6)}`}>
              {part}
              {index < parts.length - 1 && (
                <span className="mx-1 inline-block min-w-20 border-b-2 border-primary/50 align-baseline text-center font-mono text-primary">
                  {" "}
                </span>
              )}
            </span>
          ))}
        </p>
        <p className="mt-3 text-xs text-muted-foreground">
          {t({
            zh: "读句子，填出横线上缺的那个单词。",
            en: "Read the sentence and fill in the missing word.",
          })}
        </p>
      </div>
    )
  }

  if (promptType === "letters") {
    return (
      <div className="rounded-2xl bg-secondary/50 p-5 sm:p-6">
        {item.meaning_zh && (
          <p className="text-lg font-medium">{item.meaning_zh}</p>
        )}
        <p className="mt-2 text-xs text-muted-foreground">
          {t({
            zh: "把下面的字母重新排好，拼出这个单词：",
            en: "Rearrange these letters to spell the word:",
          })}
        </p>
        <ul className="mt-3 flex flex-wrap gap-2" aria-label="字母块">
          {(item.letters_pool ?? []).map((letter, index) => (
            <li
              key={`${letter}-${index}`}
              className="flex size-11 items-center justify-center rounded-xl border border-primary/25 bg-card font-mono text-lg font-semibold uppercase"
            >
              {letter}
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-muted-foreground">
          {t(VOCAB_PROMPT_META.letters.hint)}
        </p>
      </div>
    )
  }

  if (promptType === "roots") {
    return (
      <div className="rounded-2xl bg-secondary/50 p-5 sm:p-6">
        <p className="mb-3 text-xs text-muted-foreground">
          {t({
            zh: "用下面的词块拼出完整单词（顺序可能需要调整）：",
            en: "Put these word parts together to spell the word (order may need fixing):",
          })}
        </p>
        <ul className="flex flex-wrap gap-2">
          {(item.morph_segments ?? []).map((segment) => (
            <li
              key={`${segment.text}-${segment.gloss}`}
              className="rounded-xl border border-primary/25 bg-card px-3.5 py-2"
            >
              <span className="font-mono text-base font-semibold">
                {segment.text}
              </span>
              <span className="ml-2 text-xs text-muted-foreground">
                {segment.gloss}
              </span>
              <span className="ml-2 text-[10px] uppercase tracking-wide text-primary">
                {t(SEGMENT_KIND[segment.kind ?? "root"] ?? SEGMENT_KIND.root)}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-muted-foreground">
          {t(vocabPromptMeta("roots").hint)}
        </p>
      </div>
    )
  }

  return null
}

/** 选项按钮（四选一）：答前只给候选，答后按服务端 is_answer 高亮正确项。 */
export function ChoiceOptions({
  item,
  answered,
  disabled,
  onPick,
}: {
  item: VocabularyTodayItem
  answered: boolean
  disabled: boolean
  onPick: (wordId: string) => void
}) {
  const { t } = useI18n()
  const labelIsChinese = item.prompt_type === "en_zh"
  return (
    <ul className="grid gap-2 sm:grid-cols-2" aria-label="选项">
      {(item.choices ?? []).map((choice, index) => {
        const isAnswer = choice.is_answer === true
        const picked = item.first_choice_word_id === choice.word_id
        return (
          <li key={choice.word_id}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onPick(choice.word_id)}
              className={`min-h-14 w-full rounded-2xl border px-4 py-3 text-left text-base transition-colors ${
                isAnswer
                  ? "border-primary bg-primary/10 text-primary"
                  : picked
                    ? "border-amber-500/60 bg-amber-500/10"
                    : "border-input bg-card hover:border-primary/50"
              } disabled:opacity-70`}
            >
              <span className="mr-2 text-xs text-muted-foreground">
                {String.fromCharCode(65 + index)}.
              </span>
              {labelIsChinese ? choice.meaning_zh : choice.headword}
              {!labelIsChinese && choice.meaning_zh && (
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {choice.meaning_zh}
                </span>
              )}
              {answered && isAnswer && (
                <span className="ml-2 text-xs font-medium text-primary">
                  {t({ zh: "正确", en: "Correct" })}
                </span>
              )}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
