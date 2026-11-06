import { useState } from "react"
import type { PassageWithSentences } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import { useI18n } from "@/lib/i18n"
import { PassageFields } from "./PassageFields"
import { emptyForm, NO_UNIT, type PassageForm, type UnitOption } from "./shared"
export function EditPassageDialog({
  passage,
  topics,
  units,
  scenarioTopics,
  pending,
  onClose,
  onSubmit,
}: {
  passage: PassageWithSentences | null
  topics: string[]
  units: UnitOption[]
  scenarioTopics: Set<string>
  pending: boolean
  onClose: () => void
  onSubmit: (form: PassageForm) => void
}) {
  const { t } = useI18n()
  const [form, setForm] = useState<PassageForm>(emptyForm)
  const [loadedId, setLoadedId] = useState<string | null>(null)

  if (passage && passage.id !== loadedId) {
    setLoadedId(passage.id)
    setForm({
      slug: passage.slug ?? "",
      title: passage.title ?? "",
      topic: passage.topic ?? "",
      cefr_band: passage.cefr_band ?? "B1",
      text: passage.text ?? "",
      translation: passage.translation ?? "",
      suggested_seconds: passage.suggested_seconds ?? 45,
      unit_id: passage.unit_id ?? NO_UNIT,
      is_active: passage.is_active ?? true,
    })
  }
  if (!passage && loadedId !== null) setLoadedId(null)

  const canSubmit = form.title.trim().length > 0 && form.text.trim().length > 0

  return (
    <Dialog
      open={passage !== null}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t({ zh: "编辑篇目", en: "Edit Passage" })}</DialogTitle>
          <DialogDescription>
            {t({
              zh: "slug 建成后不可改（学生进度与录音都挂在它上面）：",
              en: "The slug cannot be changed once created (student progress and recordings are tied to it):",
            })}{" "}
            <span className="font-mono">{passage?.slug}</span>
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 md:grid-cols-2">
          <PassageFields
            form={form}
            setForm={setForm}
            topics={topics}
            units={units}
            scenarioTopics={scenarioTopics}
            idPrefix="edit-passage-"
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t({ zh: "取消", en: "Cancel" })}
          </Button>
          <LoadingButton
            disabled={!canSubmit}
            loading={pending}
            onClick={() => onSubmit(form)}
          >
            {t({ zh: "保存", en: "Save" })}
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
