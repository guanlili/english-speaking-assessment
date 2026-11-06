import { TopicPicker } from "@/components/Admin/TopicPicker"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { NumberInput } from "@/components/ui/number-input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { useI18n } from "@/lib/i18n"
import {
  CEFR_BANDS,
  NO_UNIT,
  type PassageForm,
  type UnitOption,
} from "./shared"
export function PassageFields({
  form,
  setForm,
  topics,
  units,
  scenarioTopics,
  idPrefix = "passage-",
}: {
  form: PassageForm
  setForm: (next: PassageForm) => void
  topics: string[]
  units: UnitOption[]
  scenarioTopics: Set<string>
  /** 新建表单与编辑弹窗同时在页面上，用前缀避免重复 id。 */
  idPrefix?: string
}) {
  const { t } = useI18n()
  const attachedUnit = units.find((u) => u.id === form.unit_id)
  return (
    <>
      <div className="space-y-1">
        <Label htmlFor={`${idPrefix}title`}>
          {t({ zh: "标题", en: "Title" })}
        </Label>
        <Input
          id={`${idPrefix}title`}
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
        />
      </div>
      <div className="space-y-1">
        <Label>{t({ zh: "所属主题（单元）", en: "Topic (Unit)" })}</Label>
        <Select
          value={form.unit_id}
          onValueChange={(next) => setForm({ ...form, unit_id: next })}
        >
          <SelectTrigger className="w-full">
            <SelectValue
              placeholder={t({ zh: "选择主题", en: "Select topic" })}
            />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_UNIT}>
              {t({ zh: "未归属", en: "Unassigned" })}
            </SelectItem>
            {units.map((u) => (
              <SelectItem key={u.id} value={u.id}>
                {u.title} · {u.topic}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">
          {t({
            zh: "题库按「主题 → 篇目 → 句子」组织；归属后篇目主题自动跟随单元。",
            en: "The bank is organized topic → passage → sentences; once assigned, the passage topic follows its unit.",
          })}
        </p>
      </div>
      {attachedUnit ? (
        <div className="space-y-1">
          <Label>{t({ zh: "配套问答主题", en: "Paired Q&A Topic" })}</Label>
          <Input value={attachedUnit.topic} disabled readOnly />
          <p className="text-xs text-muted-foreground">
            {t({
              zh: "跟随所属单元，改单元主题即可调整。",
              en: "Follows the unit — change the unit's topic to adjust.",
            })}
          </p>
        </div>
      ) : (
        <div className="space-y-1">
          <Label>{t({ zh: "配套问答主题", en: "Paired Q&A Topic" })}</Label>
          <TopicPicker
            value={form.topic}
            topics={topics}
            onChange={(topic) => setForm({ ...form, topic })}
          />
          {form.topic && !scenarioTopics.has(form.topic) && (
            <p className="text-xs text-amber-600 dark:text-amber-400">
              {t({
                zh: "该主题还没有情景问答题：学生自主练习将跳过问答环节。",
                en: "No Scenario Q&A exists for this topic yet — self practice will skip Q&A.",
              })}
            </p>
          )}
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label htmlFor={`${idPrefix}band`}>
            {t({ zh: "难度", en: "Level" })}
          </Label>
          <Select
            value={form.cefr_band}
            onValueChange={(next) => setForm({ ...form, cefr_band: next })}
          >
            <SelectTrigger id={`${idPrefix}band`} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CEFR_BANDS.map((band) => (
                <SelectItem key={band} value={band}>
                  {band}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${idPrefix}seconds`}>
            {t({ zh: "建议秒数", en: "Suggested Seconds" })}
          </Label>
          <NumberInput
            id={`${idPrefix}seconds`}
            value={form.suggested_seconds}
            onValueChange={(suggested_seconds) =>
              setForm({ ...form, suggested_seconds })
            }
          />
        </div>
      </div>
      <div className="space-y-1">
        <Label htmlFor={`${idPrefix}text`}>
          {t({
            zh: "正文（朗读参考文本）",
            en: "Text (read-aloud reference)",
          })}
        </Label>
        <Textarea
          id={`${idPrefix}text`}
          rows={4}
          value={form.text}
          onChange={(e) => setForm({ ...form, text: e.target.value })}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor={`${idPrefix}translation`}>
          {t({
            zh: "中文提示（可选，学生端显示）",
            en: "Chinese Hint (optional, shown to students)",
          })}
        </Label>
        <Input
          id={`${idPrefix}translation`}
          value={form.translation ?? ""}
          onChange={(e) => setForm({ ...form, translation: e.target.value })}
        />
      </div>
      <div className="flex items-center gap-2 text-sm">
        <Checkbox
          checked={form.is_active}
          onCheckedChange={(checked) =>
            setForm({ ...form, is_active: checked === true })
          }
        />
        {t({
          zh: "启用（学生端可练；停用后今天练习与地图里都不再出现）",
          en: "Enabled (visible to students; once disabled it leaves Today's Practice and the map)",
        })}
      </div>
    </>
  )
}
