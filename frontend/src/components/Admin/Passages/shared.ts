/** 难度位是枚举（后端同样校验），不再自由输入。 */
export const CEFR_BANDS = ["A2", "B1", "B2"] as const
export const NO_UNIT = "__none__"

export interface PassageForm {
  slug: string
  title: string
  topic: string
  cefr_band: string
  text: string
  translation?: string
  suggested_seconds: number
  unit_id: string
  is_active: boolean
}

export const emptyForm: PassageForm = {
  slug: "",
  title: "",
  topic: "",
  cefr_band: "B1",
  text: "",
  translation: "",
  suggested_seconds: 45,
  unit_id: NO_UNIT,
  is_active: true,
}

export interface UnitOption {
  id: string
  title: string
  topic: string
}

export function toRequestBody(form: PassageForm) {
  return {
    slug: form.slug.trim() ? form.slug.trim() : null,
    title: form.title.trim(),
    topic: form.topic.trim(),
    cefr_band: form.cefr_band,
    text: form.text,
    translation: form.translation?.trim() ? form.translation.trim() : null,
    suggested_seconds: form.suggested_seconds,
    unit_id: form.unit_id === NO_UNIT ? null : form.unit_id,
    is_active: form.is_active,
  }
}
