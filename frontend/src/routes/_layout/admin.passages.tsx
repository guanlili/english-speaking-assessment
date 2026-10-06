import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Pencil, Plus, Scissors, Trash2 } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import type { PassageWithSentences } from "@/client"
import { AdminService } from "@/client"
import { ContentNavigation } from "@/components/Admin/ContentNavigation"
import { TopicPicker } from "@/components/Admin/TopicPicker"
import { ConfirmDialog } from "@/components/Common/ConfirmDialog"
import AudioSetter from "@/components/Practice/AudioSetter"
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
    onError: (err: { body?: { detail?: string } }) =>
      showErrorToast(
        err.body?.detail ?? t({ zh: "创建失败", en: "Create failed" }),
      ),
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
    onError: (err: { body?: { detail?: string } }) =>
      showErrorToast(
        err.body?.detail ?? t({ zh: "更新失败", en: "Update failed" }),
      ),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => AdminService.deletePassage({ passageId: id }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "已删除", en: "Deleted" }))
      setToDelete(null)
      invalidate()
    },
    onError: (err: { body?: { detail?: string } }) =>
      showErrorToast(
        err.body?.detail ?? t({ zh: "删除失败", en: "Delete failed" }),
      ),
  })

  const units = (unitsQuery.data ?? []).map((u) => ({
    id: u.id,
    title: u.title,
  }))
  const unitTitle = (id?: string | null) =>
    units.find((u) => u.id === id)?.title ??
    t({ zh: "未归属", en: "Unassigned" })

  return (
    <div className="flex flex-col gap-6">
      {!embedded && <ContentNavigation />}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          {t(TERMS.typeReading)}
        </h1>
        <p className="text-muted-foreground">
          {t({
            zh: "录入文章或段落，学生朗读并提交录音，系统提供参考反馈。听句复述请到「听句复述」题库。",
            en: "Add articles or paragraphs for students to read aloud and submit recordings, with reference feedback from the system. For Listen & Repeat, use its own question bank.",
          })}
        </p>
      </div>

      <details className="rounded-xl border bg-card p-4">
        <summary className="cursor-pointer font-medium text-primary">
          {t({ zh: "新建篇目", en: "New Passage" })}
        </summary>
        <div className="mt-4">
          <NewPassageForm
            topics={topicsQuery.data ?? []}
            units={units}
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
        (passagesQuery.data ?? [])
          .filter((passage) =>
            `${passage.title} ${passage.topic}`
              .toLowerCase()
              .includes(keyword.trim().toLowerCase()),
          )
          .map((passage) => (
            <PassageCard
              key={passage.id}
              passage={passage}
              unitTitle={unitTitle(passage.unit_id)}
              expanded={expandedId === passage.id}
              onToggle={() =>
                setExpandedId(expandedId === passage.id ? null : passage.id)
              }
              onEdit={() => setEditing(passage)}
              onDelete={() => setToDelete(passage)}
              onMutated={invalidate}
            />
          ))
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
  idPrefix = "passage-",
}: {
  form: PassageForm
  setForm: (next: PassageForm) => void
  topics: string[]
  units: UnitOption[]
  /** 新建表单与编辑弹窗同时在页面上，用前缀避免重复 id。 */
  idPrefix?: string
}) {
  const { t } = useI18n()
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
        <Label>{t({ zh: "配套问答主题", en: "Paired Q&A Topic" })}</Label>
        <TopicPicker
          value={form.topic}
          topics={topics}
          onChange={(topic) => setForm({ ...form, topic })}
        />
      </div>
      <div className="space-y-1">
        <Label>
          {t({
            zh: "所属单元（用于课堂指派）",
            en: "Unit (for class assignment)",
          })}
        </Label>
        <Select
          value={form.unit_id}
          onValueChange={(next) => setForm({ ...form, unit_id: next })}
        >
          <SelectTrigger className="w-full">
            <SelectValue
              placeholder={t({ zh: "选择单元", en: "Select unit" })}
            />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_UNIT}>
              {t({ zh: "未归属", en: "Unassigned" })}
            </SelectItem>
            {units.map((u) => (
              <SelectItem key={u.id} value={u.id}>
                {u.title}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
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

function NewPassageForm({
  onSubmit,
  pending,
  topics,
  units,
}: {
  onSubmit: (form: PassageForm) => Promise<unknown>
  pending: boolean
  topics: string[]
  units: UnitOption[]
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
            zh: "填写篇目并选择主题；相同主题的情景问答会用于配套练习。",
            en: "Fill in the passage and pick a topic; Scenario Q&A under the same topic is used as paired practice.",
          })}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-2">
        <PassageFields
          form={form}
          setForm={setForm}
          topics={topics}
          units={units}
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
  pending,
  onClose,
  onSubmit,
}: {
  passage: PassageWithSentences | null
  topics: string[]
  units: UnitOption[]
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
  const splitPassage = useMutation({
    mutationFn: () =>
      AdminService.splitPassageIntoReadings({ passageId: passage.id }),
    onSuccess: (data) => {
      toast.success(
        t({
          zh: `已拆分为 ${data.created} 篇朗读材料，原长文已停用（可再启用）`,
          en: `Split into ${data.created} reading passages; the original long text is now disabled (can be re-enabled)`,
        }),
      )
      setSplitConfirm(false)
      onMutated()
    },
    onError: (err: { body?: { detail?: string } }) =>
      toast.error(
        err.body?.detail ?? t({ zh: "拆分失败", en: "Split failed" }),
      ),
  })
  const paragraphCount = (passage.text ?? "")
    .split(/\n+/)
    .filter((p) => p.trim()).length

  return (
    <Card>
      <CardHeader className="flex flex-wrap items-start justify-between gap-3 space-y-0">
        <div className="min-w-0">
          <CardTitle className="break-words text-base leading-relaxed">
            {passage.title}{" "}
            <span className="font-normal text-muted-foreground">
              · {passage.topic} · {passage.cefr_band} ·{" "}
              {(passage.sentences ?? []).length}{" "}
              {t({ zh: "句复述", en: "repeat sentences" })}
            </span>
          </CardTitle>
          <CardDescription className="mt-1 flex flex-wrap items-center gap-2">
            <Badge variant="outline">{unitTitle}</Badge>
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
            aria-expanded={expanded}
            onClick={onToggle}
          >
            {expanded
              ? t({ zh: "收起", en: "Collapse" })
              : t({ zh: "查看文章", en: "View Text" })}
          </Button>
          {passage.is_active !== false && (
            <Button
              variant="outline"
              size="sm"
              disabled={paragraphCount < 2 || splitPassage.isPending}
              title={
                paragraphCount < 2
                  ? t({
                      zh: "正文只有一个段落：请先用换行分段，再拆分",
                      en: "Only one paragraph: separate paragraphs with line breaks before splitting",
                    })
                  : t({
                      zh: "按段落拆成多篇朗读材料，原长文停用",
                      en: "Split by paragraph into multiple readings; the original is disabled",
                    })
              }
              onClick={() => setSplitConfirm(true)}
            >
              <Scissors />
              {t({ zh: "拆分为多篇", en: "Split" })}
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
            hasAudio={Boolean(passage.audio_url)}
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
        <CardContent className="space-y-4">
          <p className="whitespace-pre-wrap rounded-md bg-muted p-3 text-sm">
            {passage.text}
          </p>
          {(passage.sentences ?? []).length > 0 && (
            <p className="text-xs text-muted-foreground">
              {t({
                zh: `本篇挂有 ${(passage.sentences ?? []).length} 句复述句，请在「听句复述」题库中管理。`,
                en: `This passage has ${(passage.sentences ?? []).length} repeat sentences — manage them in the Listen & Repeat bank.`,
              })}
            </p>
          )}
        </CardContent>
      )}

      <ConfirmDialog
        open={splitConfirm}
        title={t({
          zh: `把「${passage.title}」拆分为多篇朗读材料？`,
          en: `Split "${passage.title}" into multiple readings?`,
        })}
        description={t({
          zh: `按段落拆成 ${paragraphCount} 篇（超长段会再按句聚合），新篇沿用标题、主题与分组并自动编号；原长文将停用，历史与挂靠的复述句保留。`,
          en: `Split into ${paragraphCount} passages by paragraph (very long paragraphs are regrouped by sentence); new passages reuse the title, topic, and group with automatic numbering. The original long text is disabled; history and attached repeat sentences are kept.`,
        })}
        confirmText={t({ zh: "拆分", en: "Split" })}
        onOpenChange={(next) => {
          if (!next) setSplitConfirm(false)
        }}
        onConfirm={async () => {
          await splitPassage.mutateAsync()
        }}
      />
    </Card>
  )
}
