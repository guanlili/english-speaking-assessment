import type { ScenarioOut } from "@/client"
import { Checkbox } from "@/components/ui/checkbox"
import { useI18n } from "@/lib/i18n"

/** 问答主题选题区：多选主题；选中主题下的全部题目进入本次练习。 */
export default function ScenariosSection({
  sectionNo,
  scenarios,
  selectedIds,
  selectedScenarios,
  onToggle,
}: {
  sectionNo: number
  scenarios: ScenarioOut[]
  selectedIds: string[]
  selectedScenarios: ScenarioOut[]
  onToggle: (id: string) => void
}) {
  const { t } = useI18n()
  return (
    <section>
      <h2 className="font-semibold">
        {sectionNo}. {t({ zh: "问答主题", en: "Q&A Topic" })}
      </h2>
      <p className="mb-3 mt-2 text-sm text-muted-foreground">
        {t({
          zh: "可多选主题；选中主题下的全部题目进入本次练习。",
          en: "Select multiple topics; all questions in each selected topic join this practice.",
        })}
      </p>
      <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
        {scenarios
          .filter((s) => s.is_active)
          .map((scenario) => (
            <label
              key={scenario.id}
              htmlFor={`pick-scenario-${scenario.id}`}
              className={`flex cursor-pointer items-center gap-3 rounded-lg border p-3 ${selectedIds.includes(scenario.id) ? "border-primary/50 bg-primary/5" : ""}`}
            >
              <Checkbox
                id={`pick-scenario-${scenario.id}`}
                checked={selectedIds.includes(scenario.id)}
                onCheckedChange={() => onToggle(scenario.id)}
              />
              <span className="min-w-0 flex-1 text-sm">
                {t({
                  zh: `${scenario.topic}（${scenario.questions.length} 题）`,
                  en: `${scenario.topic} (${scenario.questions.length} questions)`,
                })}
              </span>
            </label>
          ))}
      </div>
      {selectedScenarios.map((scenario) => (
        <div
          key={scenario.id}
          className="mt-3 space-y-1 rounded-lg border p-3 text-sm"
        >
          <p className="font-medium">{scenario.topic}</p>
          {scenario.questions.map((q) => (
            <p key={q.id} className="truncate">
              · {q.text}{" "}
              <span className="text-xs text-muted-foreground">
                {t({
                  zh: `${q.suggested_seconds} 秒`,
                  en: `${q.suggested_seconds}s`,
                })}
              </span>
            </p>
          ))}
        </div>
      ))}
    </section>
  )
}
