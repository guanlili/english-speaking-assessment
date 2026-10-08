import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  ChevronDown,
  ChevronRight,
  Pencil,
  Plus,
  Scissors,
  Trash2,
  Undo2,
} from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import type { PassageWithSentences } from "@/client"
import { AdminService } from "@/client"
import { ContentNavigation } from "@/components/Admin/ContentNavigation"
import { TopicPicker } from "@/components/Admin/TopicPicker"
import { ConfirmDialog } from "@/components/Common/ConfirmDialog"
import AudioSetter from "@/components/Practice/AudioSetter"
import { PassageSentences } from "@/components/Teaching/PassageSentences"
import { ReadingSentences } from "@/components/Teaching/ReadingSentences"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import { NumberInput } from "@/components/ui/number-input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { APP_NAME } from "@/config"
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"
import { TERMS } from "@/lib/terms"
import { extractErrorMessage } from "@/utils"

export const Route = createFileRoute("/_layout/admin/passages")({
  component: PassagesAdmin,
  head: () => ({ meta: [{ title: `篇目管理 / Passages - ${APP_NAME}` }] }),
})

/** 难度位是枚举（后端同样校验），不再自由输入。 */
const CEFR_BANDS = ["A2", "B1", "B2"] as const
const NO_UNIT = "__none__"

interface PassageForm {
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

const emptyForm: PassageForm = {
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

interface UnitOption {
  id: string
  title: string
  topic: string
}

function toRequestBody(form: PassageForm) {
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

export function PassagesAdmin({ embedded = false }: { embedded?: boolean }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [keyword, setKeyword] = useState("")
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [editing, setEditing] = useState<PassageWithSentences | null>(null)
  const [toDelete, setToDelete] = useState<PassageWithSentences | null>(null)

  const passagesQuery = useQuery({
    queryKey: ["admin", "passages"],
    queryFn: () => AdminService.listPassages(),
  })
  const unitsQuery = useQuery({
    queryKey: ["admin", "units"],
    queryFn: () => AdminService.listUnits(),
  })
  const topicsQuery = useQuery({
    queryKey: ["admin", "topics"],
    queryFn: () => AdminService.listTopics(),
  })
  const scenariosQuery = useQuery({
    queryKey: ["admin", "scenarios"],
    queryFn: () => AdminService.listScenarios(),
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["admin", "passages"] })
    void queryClient.invalidateQueries({ queryKey: ["admin", "units"] })
  }

  const createMutation = useMutation({
    mutationFn: (form: PassageForm) =>
      AdminService.createPassage({ requestBody: toRequestBody(form) }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "篇目已创建", en: "Passage created" }))
      invalidate()
    },
    onError: (err) => showErrorToast(extractErrorMessage(err)),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, form }: { id: string; form: PassageForm }) =>
      AdminService.updatePassage({
        passageId: id,
        requestBody: toRequestBody(form),
      }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "篇目已更新", en: "Passage updated" }))
      setEditing(null)
      invalidate()
    },
    onError: (err) => showErrorToast(extractErrorMessage(err)),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => AdminService.deletePassage({ passageId: id }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "已删除", en: "Deleted" }))
      setToDelete(null)
      invalidate()
    },
    onError: (err) => showErrorToast(extractErrorMessage(err)),
  })

  const units = (unitsQuery.data ?? []).map((u) => ({
    id: u.id,
    title: u.title,
    topic: u.topic,
  }))

  return (
    <div className="flex flex-col gap-6">
      {!embedded && <ContentNavigation />}
      {!embedded && (
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            {t(TERMS.typeReading)}
          </h1>
          <p className="text-muted-foreground">
            {t({
              zh: "未拆分的文章整篇一道题；拆分过的文章组卷时按句出题、学生逐句朗读。展开文章可查看正文和分句，也可管理配套的听句复述。",
              en: "An unsplit article is one read-aloud question; a split article becomes one question per sentence so students read aloud sentence by sentence. Expand an article to view its text and sentences, or manage its paired Listen & Repeat items.",
            })}
          </p>
        </div>
      )}

      <details className="rounded-xl border bg-card p-4">
        <summary className="cursor-pointer font-medium text-primary">
          {t({ zh: "新建篇目", en: "New Passage" })}
        </summary>
        <div className="mt-4">
          <NewPassageForm
            topics={topicsQuery.data ?? []}
            units={units}
            scenarioTopics={
              new Set((scenariosQuery.data ?? []).map((s) => s.topic ?? ""))
            }
            pending={createMutation.isPending}
            onSubmit={(form) => createMutation.mutateAsync(form)}
          />
        </div>
      </details>
      <Input
        aria-label={t({ zh: "搜索篇目", en: "Search passages" })}
        placeholder={t({
          zh: "搜索篇目标题或主题…",
          en: "Search passage title or topic…",
        })}
        value={keyword}
        onChange={(event) => setKeyword(event.target.value)}
      />
      {passagesQuery.isPending ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : passagesQuery.isError ? (
        <div className="flex flex-col items-center gap-3 py-8 text-muted-foreground">
          <p>
            {t({ zh: "篇目列表加载失败。", en: "Failed to load passages." })}
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void passagesQuery.refetch()}
          >
            {t({ zh: "重试", en: "Retry" })}
          </Button>
        </div>
      ) : (passagesQuery.data ?? []).length === 0 ? (
        <p className="py-8 text-center text-muted-foreground">
          {t({
            zh: "还没有篇目，点击上方新建按钮开始备课。",
            en: "No passages yet — use the New Passage form above to start building.",
          })}
        </p>
      ) : (
        <TopicGroups
          passages={(passagesQuery.data ?? []).filter((passage) =>
            `${passage.title} ${passage.topic}`
              .toLowerCase()
              .includes(keyword.trim().toLowerCase()),
          )}
          units={unitsQuery.data ?? []}
          expandedId={expandedId}
          onToggle={setExpandedId}
          onEdit={setEditing}
          onDelete={setToDelete}
          onMutated={invalidate}
        />
      )}

      {passagesQuery.isSuccess &&
        (passagesQuery.data ?? []).length > 0 &&
        !(passagesQuery.data ?? []).some((passage) =>
          `${passage.title} ${passage.topic}`
            .toLowerCase()
            .includes(keyword.trim().toLowerCase()),
        ) && (
          <p className="py-8 text-center text-muted-foreground">
            {t({
              zh: "没有匹配的篇目，请换个关键词。",
              en: "No passages match — try another keyword.",
            })}
          </p>
        )}
      <EditPassageDialog
        passage={editing}
        topics={topicsQuery.data ?? []}
        units={units}
        scenarioTopics={
          new Set((scenariosQuery.data ?? []).map((s) => s.topic ?? ""))
        }
        pending={updateMutation.isPending}
        onClose={() => setEditing(null)}
        onSubmit={(form) => {
          if (editing) updateMutation.mutate({ id: editing.id, form })
        }}
      />

      <ConfirmDialog
        open={toDelete !== null}
        title={t({
          zh: `删除篇目「${toDelete?.title ?? ""}」？`,
          en: `Delete passage "${toDelete?.title ?? ""}"?`,
        })}
        description={t({
          zh: "删除会连带清掉它的复述句，正在练习中的学生下次会拿到别的篇目。此操作不可撤销。",
          en: "Deleting also removes its repeat sentences; students mid-practice will get a different passage next time. This cannot be undone.",
        })}
        confirmText={t({ zh: "删除篇目", en: "Delete Passage" })}
        onOpenChange={(next) => {
          if (!next) setToDelete(null)
        }}
        onConfirm={async () => {
          if (toDelete) await deleteMutation.mutateAsync(toDelete.id)
        }}
      />
    </div>
  )
}

function PassageFields({
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

/** 题库树中间层：按主题（单元）分组的篇目列表，「未归属」置底兜底。 */
function TopicGroups({
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
                  onEdit={() => onEdit(passage)}
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
              onEdit={() => onEdit(passage)}
              onDelete={() => onDelete(passage)}
              onMutated={onMutated}
            />
          ))}
        </section>
      )}
    </div>
  )
}

function NewPassageForm({
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

function EditPassageDialog({
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

function PassageCard({
  passage,
  unitTitle,
  expanded,
  onToggle,
  onEdit,
  onDelete,
  onMutated,
}: {
  passage: PassageWithSentences
  unitTitle: string
  expanded: boolean
  onToggle: () => void
  onEdit: () => void
  onDelete: () => void
  onMutated: () => void
}) {
  const { t } = useI18n()
  const [splitConfirm, setSplitConfirm] = useState(false)
  const [unsplitConfirm, setUnsplitConfirm] = useState(false)
  const splitPassage = useMutation({
    mutationFn: () =>
      AdminService.splitPassageIntoReadings({ passageId: passage.id }),
    onSuccess: (data) => {
      toast.success(
        t({
          zh: `已拆分出 ${data.created} 句：组卷时这篇文章将按句出题`,
          en: `Split into ${data.created} sentences — this article now becomes one question per sentence when composing practice`,
        }),
      )
      setSplitConfirm(false)
      if (!expanded) onToggle()
      onMutated()
    },
    onError: (err: { body?: { detail?: string } }) =>
      toast.error(
        err.body?.detail === "正文只有一个段落，无需拆分；请先用换行分段" ||
          err.body?.detail === "正文不足两句，无法按句拆分"
          ? t({
              zh: "正文至少需要两句才能拆分。",
              en: "The text needs at least two sentences to split.",
            })
          : extractErrorMessage(err),
      ),
  })
  const unsplitPassage = useMutation({
    mutationFn: () =>
      AdminService.unsplitPassageReadings({ passageId: passage.id }),
    onSuccess: () => {
      toast.success(
        t({
          zh: "已取消拆分：此后组卷回到整篇一道题",
          en: "Split removed — future practices use the whole article as one question",
        }),
      )
      setUnsplitConfirm(false)
      onMutated()
    },
    onError: (err: { body?: { detail?: string } }) =>
      toast.error(extractErrorMessage(err)),
  })
  return (
    <Card data-testid={`passage-${passage.id}`}>
      <CardHeader className="flex flex-wrap items-start justify-between gap-3 space-y-0">
        <div className="min-w-0 flex-1">
          <CardTitle className="text-base leading-relaxed">
            <button
              type="button"
              className="flex min-h-11 w-full items-center gap-2 text-left"
              aria-expanded={expanded}
              aria-controls={`passage-content-${passage.id}`}
              onClick={onToggle}
            >
              {expanded ? (
                <ChevronDown className="size-4 shrink-0" />
              ) : (
                <ChevronRight className="size-4 shrink-0" />
              )}
              <span className="min-w-0 break-words [overflow-wrap:anywhere]">
                {passage.title}
              </span>
            </button>
          </CardTitle>
          <CardDescription className="mt-1 flex flex-wrap items-center gap-2">
            <Badge variant="outline">{unitTitle}</Badge>
            <span>
              {(passage.reading_segments ?? []).length > 0
                ? t({
                    zh: `按句出题 · ${(passage.reading_segments ?? []).length} 句`,
                    en: `${(passage.reading_segments ?? []).length} sentence questions`,
                  })
                : t({ zh: "1 道文章朗读题", en: "1 read-aloud question" })}
            </span>
            {(passage.reading_segments ?? []).length > 0 && (
              <span>
                {t({
                  zh: `${(passage.reading_segments ?? []).length} 句朗读分句`,
                  en: `${(passage.reading_segments ?? []).length} reading sentences`,
                })}
              </span>
            )}
            <span>
              {t({
                zh: `${(passage.sentences ?? []).length} 句复述`,
                en: `${(passage.sentences ?? []).length} repeat sentences`,
              })}
            </span>
            {passage.is_active === false && (
              <Badge variant="secondary">
                {t({ zh: "已停用", en: "Disabled" })}
              </Badge>
            )}
          </CardDescription>
        </div>
        <div className="flex max-w-full flex-wrap items-center gap-1.5">
          <Button
            variant="outline"
            size="sm"
            className="min-h-11"
            aria-expanded={expanded}
            onClick={onToggle}
          >
            {expanded
              ? t({ zh: "收起", en: "Collapse" })
              : t({ zh: "查看文章", en: "View Text" })}
          </Button>
          {!passage.reading_split && (
            <Button
              variant="outline"
              size="sm"
              className="min-h-11"
              disabled={splitPassage.isPending}
              title={t({
                zh: "按原文顺序拆句，组卷时这篇文章按句出题",
                en: "Split sentences in source order; the article then becomes one question per sentence",
              })}
              onClick={() => setSplitConfirm(true)}
            >
              <Scissors />
              {t({ zh: "自动拆分句子", en: "Auto-split Sentences" })}
            </Button>
          )}
          {passage.reading_split && (
            <Button
              variant="outline"
              size="sm"
              className="min-h-11"
              disabled={unsplitPassage.isPending}
              title={t({
                zh: "取消拆分：此后组卷回到整篇一道题",
                en: "Remove the split — future practices use the whole article as one question",
              })}
              onClick={() => setUnsplitConfirm(true)}
            >
              <Undo2 />
              {t({ zh: "取消拆分", en: "Unsplit" })}
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={t({
              zh: `编辑 ${passage.title}`,
              en: `Edit ${passage.title}`,
            })}
            onClick={(e) => {
              e.stopPropagation()
              onEdit()
            }}
          >
            <Pencil />
          </Button>
          <AudioSetter
            audioUrl={passage.audio_url}
            text={passage.text ?? ""}
            stopPropagation
            onSet={async (audio_url) => {
              await AdminService.updatePassage({
                passageId: passage.id,
                requestBody: {
                  title: passage.title ?? "",
                  topic: passage.topic ?? "",
                  cefr_band: passage.cefr_band ?? "B1",
                  text: passage.text ?? "",
                  translation: passage.translation ?? undefined,
                  audio_url,
                  suggested_seconds: passage.suggested_seconds ?? 45,
                  is_active: passage.is_active ?? true,
                  unit_id: passage.unit_id ?? undefined,
                },
              })
              onMutated()
            }}
          />
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={t({
              zh: `删除 ${passage.title}`,
              en: `Delete ${passage.title}`,
            })}
            onClick={(e) => {
              e.stopPropagation()
              onDelete()
            }}
          >
            <Trash2 className="text-destructive" />
          </Button>
        </div>
      </CardHeader>
      {expanded && (
        <CardContent id={`passage-content-${passage.id}`} className="space-y-4">
          <p className="whitespace-pre-wrap break-words rounded-md bg-muted p-3 text-sm [overflow-wrap:anywhere]">
            {passage.text}
          </p>
          <ReadingSentences segments={passage.reading_segments ?? []} />
          <PassageSentences passage={passage} onMutated={onMutated} />
        </CardContent>
      )}

      <ConfirmDialog
        open={splitConfirm}
        title={t({
          zh: `拆分「${passage.title}」的朗读句子？`,
          en: `Split reading sentences for "${passage.title}"?`,
        })}
        description={t({
          zh: "按原文顺序拆分全部句子，折叠在文章下。组卷时这篇文章按句出题，学生逐句朗读；修改正文后分句自动更新，听句复述单独管理。",
          en: "All sentences appear in source order under the collapsible article. Composing practice then creates one question per sentence — students read aloud sentence by sentence. Sentence views update with the text; Listen & Repeat items are managed separately.",
        })}
        confirmText={t({ zh: "拆分", en: "Split" })}
        onOpenChange={(next) => {
          if (!next) setSplitConfirm(false)
        }}
        onConfirm={async () => {
          await splitPassage.mutateAsync()
        }}
      />
      <ConfirmDialog
        open={unsplitConfirm}
        title={t({
          zh: `取消拆分「${passage.title}」？`,
          en: `Remove the split for "${passage.title}"?`,
        })}
        description={t({
          zh: "此后组卷回到整篇一道题。已发布练习的快照不受影响，学生继续按发布时的逐句题单作答。",
          en: "Future practices go back to the whole article as one question. Already-published exercises keep their snapshots — students finish them as published.",
        })}
        confirmText={t({ zh: "取消拆分", en: "Unsplit" })}
        onOpenChange={(next) => {
          if (!next) setUnsplitConfirm(false)
        }}
        onConfirm={async () => {
          await unsplitPassage.mutateAsync()
        }}
      />
    </Card>
  )
}
