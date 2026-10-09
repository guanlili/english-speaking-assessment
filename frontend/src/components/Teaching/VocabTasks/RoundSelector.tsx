import { useI18n } from "@/lib/i18n"

/** 期数选择器：当前任务 / 历史期数（含已归档）；无历史时不渲染。 */
export function RoundSelector({
  assignments,
  selectedAssignmentId,
  onSelect,
  className,
}: {
  assignments: Array<{
    id: string
    version_no: number
    title: string
    status: string
    word_count: number
  }>
  selectedAssignmentId: string | null
  onSelect: (id: string | null) => void
  className?: string
}) {
  const { t } = useI18n()
  if (assignments.length === 0) return null
  return (
    <div className={`flex flex-wrap items-center gap-2 ${className ?? ""}`}>
      <label
        htmlFor="vocab-round"
        className="text-xs font-medium text-muted-foreground"
      >
        {t({ zh: "查看期数：", en: "Round:" })}
      </label>
      {/* min-w-0 + max-w-full：option 文案很长（英文尤其），不限制会把 390px
          小屏撑出横向滚动 */}
      <select
        id="vocab-round"
        value={selectedAssignmentId ?? ""}
        onChange={(event) => onSelect(event.target.value || null)}
        className="h-11 min-w-0 w-full max-w-full rounded-xl border border-input bg-card px-3 text-base text-foreground transition-colors hover:border-primary/35 sm:w-auto"
      >
        <option value="">
          {t({ zh: "当前进行中的任务", en: "Current task in progress" })}
        </option>
        {assignments.map((item) => (
          <option key={item.id} value={item.id}>
            {`#${item.version_no} ${item.title} · ${item.word_count} ${t({ zh: "词", en: "words" })} · ${
              item.status === "published"
                ? t({ zh: "进行中", en: "active" })
                : t({ zh: "已结束", en: "ended" })
            }`}
          </option>
        ))}
      </select>
    </div>
  )
}
