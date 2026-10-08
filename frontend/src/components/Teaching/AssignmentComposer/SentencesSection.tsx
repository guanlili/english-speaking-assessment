import type { SentenceWithPassage } from "@/client"
import { Checkbox } from "@/components/ui/checkbox"
import { useI18n } from "@/lib/i18n"
import { EXAM_KIND_LABELS, EXAM_LEVEL_LABELS } from "@/lib/terms"

/** 复述句选题区：从复述句题库多选，学生只能听语音复述。 */
export default function SentencesSection({
  sectionNo,
  sentences,
  selectedIds,
  onToggle,
}: {
  sectionNo: number
  sentences: SentenceWithPassage[]
  selectedIds: string[]
  onToggle: (id: string) => void
}) {
  const { t } = useI18n()
  return (
    <section>
      <h2 className="font-semibold">
        {sectionNo}. {t({ zh: "复述句", en: "Repeat Sentences" })}
      </h2>
      <p className="mb-3 mt-2 text-sm text-muted-foreground">
        {t({
          zh: "从复述句题库多选，学生只能听语音复述。",
          en: "Multi-select from the repeat-sentence bank; students repeat what they hear.",
        })}
      </p>
      <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
        {sentences.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {t({
              zh: "还没有复述句，去题目库创建。",
              en: "No repeat sentences yet — create some in the Question Bank.",
            })}
          </p>
        )}
        {sentences.map((s) => (
          <label
            key={s.id}
            htmlFor={`pick-sentence-${s.id}`}
            className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 ${selectedIds.includes(s.id ?? "") ? "border-primary/50 bg-primary/5" : ""}`}
          >
            <Checkbox
              id={`pick-sentence-${s.id}`}
              checked={selectedIds.includes(s.id ?? "")}
              onCheckedChange={() => onToggle(s.id ?? "")}
            />
            <span className="min-w-0">
              <span className="block truncate text-sm">{s.text}</span>
              <span className="mt-0.5 block text-xs text-muted-foreground">
                {t({
                  zh: `${s.suggested_seconds} 秒 · 可听 ${(s.replay_limit ?? 3) === 0 ? "不限" : `${s.replay_limit ?? 3} 次`}${s.passage_title ? ` · 挂篇目：${s.passage_title}` : " · 独立题"}`,
                  en: `${s.suggested_seconds}s · ${(s.replay_limit ?? 3) === 0 ? "unlimited replays" : `${s.replay_limit ?? 3} replays`}${s.passage_title ? ` · Passage: ${s.passage_title}` : " · Standalone"}`,
                })}
              </span>
              {s.exam_kind && (
                <span className="mt-1 flex flex-wrap gap-1">
                  <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] font-medium text-primary">
                    {t(
                      EXAM_KIND_LABELS[s.exam_kind] ?? {
                        zh: s.exam_kind,
                        en: s.exam_kind,
                      },
                    )}
                  </span>
                  {s.exam_level && (
                    <span className="rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      {t(
                        EXAM_LEVEL_LABELS[s.exam_level] ?? {
                          zh: s.exam_level,
                          en: s.exam_level,
                        },
                      )}
                    </span>
                  )}
                </span>
              )}
            </span>
          </label>
        ))}
      </div>
    </section>
  )
}
