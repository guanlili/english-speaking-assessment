import { Plus } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useI18n } from "@/lib/i18n"
import { PassageFields } from "./PassageFields"
import { emptyForm, type PassageForm, type UnitOption } from "./shared"
export function NewPassageForm({
  onSubmit,
  pending,
  topics,
  units,
  scenarioTopics,
}: {
  onSubmit: (form: PassageForm) => Promise<unknown>
  pending: boolean
  topics: string[]
  units: UnitOption[]
  scenarioTopics: Set<string>
}) {
  const { t } = useI18n()
  const [form, setForm] = useState<PassageForm>(emptyForm)
  const canSubmit = form.title.trim().length > 0 && form.text.trim().length > 0

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {t({ zh: "新建篇目", en: "New Passage" })}
        </CardTitle>
        <CardDescription>
          {t({
            zh: "选择所属主题（单元）后，配套问答主题自动跟随单元；未归属时可单独设主题。",
            en: "Pick a topic (unit) and the paired Q&A topic follows it; set one manually only for unassigned passages.",
          })}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-2">
        <PassageFields
          form={form}
          setForm={setForm}
          topics={topics}
          units={units}
          scenarioTopics={scenarioTopics}
        />
        <div className="md:col-span-2">
          <Button
            onClick={async () => {
              try {
                await onSubmit(form)
                setForm(emptyForm)
              } catch {
                // Mutation displays the error; retain the draft for retry.
              }
            }}
            disabled={!canSubmit || pending}
          >
            <Plus />
            {t({ zh: "创建", en: "Create" })}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
