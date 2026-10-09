import type { PassageWithSentences } from "@/client"
import { ReadingPassagePicker } from "@/components/Teaching/ReadingPassagePicker"
import { useI18n } from "@/lib/i18n"

/** 朗读篇目选题区：未拆分的文章整篇一道题；拆分过的按句出题。 */
export default function PassagesSection({
  sectionNo,
  passages,
  selectedIds,
  onToggle,
}: {
  sectionNo: number
  passages: PassageWithSentences[]
  selectedIds: string[]
  onToggle: (id: string) => void
}) {
  const { t } = useI18n()
  return (
    <section>
      <h2 className="font-semibold">
        {sectionNo}. {t({ zh: "朗读篇目", en: "Read Aloud Passages" })}
      </h2>
      <p className="mb-3 mt-2 text-sm text-muted-foreground">
        {t({
          zh: "可多选：未拆分的文章整篇一道题；拆分过的文章按句出题，学生逐句朗读。",
          en: "Multi-select: unsplit articles count as one question; split articles become one question per sentence, read aloud sentence by sentence.",
        })}
      </p>
      <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
        {passages.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {t({
              zh: "还没有朗读篇目，去题目库创建。",
              en: "No read-aloud passages yet — create some in the Question Bank.",
            })}
          </p>
        )}
        {passages.map((p) => (
          <ReadingPassagePicker
            key={p.id}
            passage={p}
            checked={selectedIds.includes(p.id)}
            onCheckedChange={() => onToggle(p.id)}
          />
        ))}
      </div>
    </section>
  )
}
