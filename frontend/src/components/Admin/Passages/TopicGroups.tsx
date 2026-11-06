import type { PassageWithSentences } from "@/client"
import { Badge } from "@/components/ui/badge"
import { useI18n } from "@/lib/i18n"
import { PassageCard } from "./PassageCard"
/** 题库树中间层：按主题（单元）分组的篇目列表，「未归属」置底兜底。 */
export function TopicGroups({
  passages,
  units,
  expandedId,
  onToggle,
  onEdit,
  onDelete,
  onMutated,
}: {
  passages: PassageWithSentences[]
  units: Array<{
    id: string
    title: string
    topic: string
    is_active: boolean
  }>
  expandedId: string | null
  onToggle: (id: string | null) => void
  onEdit: (passage: PassageWithSentences) => void
  onDelete: (passage: PassageWithSentences) => void
  onMutated: () => void
}) {
  const { t } = useI18n()
  const unassigned = passages.filter((p) => !p.unit_id)
  return (
    <div className="space-y-7">
      {units.map((unit) => {
        const group = passages.filter((p) => p.unit_id === unit.id)
        return (
          <section key={unit.id} className="space-y-2">
            <div className="flex flex-wrap items-center gap-2 border-b pb-2">
              <h2 className="text-sm font-semibold">{unit.title}</h2>
              <Badge variant="secondary">{unit.topic}</Badge>
              {unit.is_active === false && (
                <Badge variant="outline">
                  {t({ zh: "已停用", en: "Disabled" })}
                </Badge>
              )}
              <span className="text-xs text-muted-foreground">
                {t({
                  zh: `${group.length} 篇`,
                  en: `${group.length} passage${group.length === 1 ? "" : "s"}`,
                })}
              </span>
            </div>
            {group.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                {t({
                  zh: "该主题下还没有篇目，可在上方新建时选择本主题。",
                  en: "No passages under this topic yet — pick it when creating a passage above.",
                })}
              </p>
            ) : (
              group.map((passage) => (
                <PassageCard
                  key={passage.id}
                  passage={passage}
                  unitTitle={unit.title}
                  expanded={expandedId === passage.id}
                  onToggle={() =>
                    onToggle(expandedId === passage.id ? null : passage.id)
                  }
                  onEdit={onEdit}
                  onDelete={() => onDelete(passage)}
                  onMutated={onMutated}
                />
              ))
            )}
          </section>
        )
      })}
      {unassigned.length > 0 && (
        <section className="space-y-2">
          <div className="flex flex-wrap items-center gap-2 border-b pb-2">
            <h2 className="text-sm font-semibold">
              {t({ zh: "未归属", en: "Unassigned" })}
            </h2>
            <span className="text-xs text-muted-foreground">
              {t({
                zh: `${unassigned.length} 篇 · 建议在编辑里归入主题`,
                en: `${unassigned.length} · assign a topic when editing`,
              })}
            </span>
          </div>
          {unassigned.map((passage) => (
            <PassageCard
              key={passage.id}
              passage={passage}
              unitTitle={t({ zh: "未归属", en: "Unassigned" })}
              expanded={expandedId === passage.id}
              onToggle={() =>
                onToggle(expandedId === passage.id ? null : passage.id)
              }
              onEdit={onEdit}
              onDelete={() => onDelete(passage)}
              onMutated={onMutated}
            />
          ))}
        </section>
      )}
    </div>
  )
}
