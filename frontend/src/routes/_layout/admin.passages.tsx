import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Loader2, Pencil, Plus, Scissors, Trash2 } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import type { PassageWithSentences } from "@/client"
import { AdminService } from "@/client"
import { ContentNavigation } from "@/components/Admin/ContentNavigation"
import { TopicPicker } from "@/components/Admin/TopicPicker"
import { ConfirmDialog } from "@/components/Common/ConfirmDialog"
import AudioSetter from "@/components/Practice/AudioSetter"
import { RepeatSettings } from "@/components/Teaching/RepeatSettings"
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

export const Route = createFileRoute("/_layout/admin/passages")({
  component: PassagesAdmin,
  head: () => ({ meta: [{ title: `篇目管理 - ${APP_NAME}` }] }),
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

export function PassagesAdmin({
  mode = "reading",
  embedded = false,
}: {
  mode?: "reading" | "repeat"
  embedded?: boolean
}) {
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
      showSuccessToast("篇目已创建")
      invalidate()
    },
    onError: (err: { body?: { detail?: string } }) =>
      showErrorToast(err.body?.detail ?? "创建失败"),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, form }: { id: string; form: PassageForm }) =>
      AdminService.updatePassage({
        passageId: id,
        requestBody: toRequestBody(form),
      }),
    onSuccess: () => {
      showSuccessToast("篇目已更新")
      setEditing(null)
      invalidate()
    },
    onError: (err: { body?: { detail?: string } }) =>
      showErrorToast(err.body?.detail ?? "更新失败"),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => AdminService.deletePassage({ passageId: id }),
    onSuccess: () => {
      showSuccessToast("已删除")
      setToDelete(null)
      invalidate()
    },
    onError: (err: { body?: { detail?: string } }) =>
      showErrorToast(err.body?.detail ?? "删除失败"),
  })

  const units = (unitsQuery.data ?? []).map((u) => ({
    id: u.id,
    title: u.title,
  }))
  const unitTitle = (id?: string | null) =>
    units.find((u) => u.id === id)?.title ?? "未归属"

  return (
    <div className="flex flex-col gap-6">
      {!embedded && <ContentNavigation />}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          {mode === "repeat" ? "听句复述" : "文章朗读"}
        </h1>
        <p className="text-muted-foreground">
          {mode === "repeat"
            ? "按篇目整理复述句，为每句设置标准音、作答时间和可听次数。"
            : "录入文章或段落，学生朗读并提交录音，系统提供参考反馈。"}
        </p>
      </div>

      <details className="rounded-xl border bg-card p-4">
        <summary className="cursor-pointer font-medium text-primary">
          {mode === "repeat" ? "新建复述材料" : "新建朗读题"}
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
        aria-label="搜索篇目"
        placeholder="搜索篇目标题或主题…"
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
          <p>篇目列表加载失败。</p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void passagesQuery.refetch()}
          >
            重试
          </Button>
        </div>
      ) : (passagesQuery.data ?? []).length === 0 ? (
        <p className="py-8 text-center text-muted-foreground">
          还没有材料，点击上方新建按钮开始备课。
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
              mode={mode}
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
            没有匹配的篇目，请换个关键词。
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
        title={`删除篇目「${toDelete?.title ?? ""}」？`}
        description="删除会连带清掉它的复述句，正在练习中的学生下次会拿到别的篇目。此操作不可撤销。"
        confirmText="删除篇目"
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
  return (
    <>
      <div className="space-y-1">
        <Label htmlFor={`${idPrefix}title`}>标题</Label>
        <Input
          id={`${idPrefix}title`}
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
        />
      </div>
      <div className="space-y-1">
        <Label>配套问答主题</Label>
        <TopicPicker
          value={form.topic}
          topics={topics}
          onChange={(topic) => setForm({ ...form, topic })}
        />
      </div>
      <div className="space-y-1">
        <Label>练习分组（用于课堂指派）</Label>
        <Select
          value={form.unit_id}
          onValueChange={(next) => setForm({ ...form, unit_id: next })}
        >
          <SelectTrigger className="w-full">
            <SelectValue placeholder="选择练习分组" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_UNIT}>未归属</SelectItem>
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
          <Label htmlFor={`${idPrefix}band`}>难度</Label>
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
          <Label htmlFor={`${idPrefix}seconds`}>建议秒数</Label>
          <Input
            id={`${idPrefix}seconds`}
            type="number"
            value={form.suggested_seconds}
            onChange={(e) =>
              setForm({ ...form, suggested_seconds: Number(e.target.value) })
            }
          />
        </div>
      </div>
      <div className="space-y-1">
        <Label htmlFor={`${idPrefix}text`}>正文（朗读参考文本）</Label>
        <Textarea
          id={`${idPrefix}text`}
          rows={4}
          value={form.text}
          onChange={(e) => setForm({ ...form, text: e.target.value })}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor={`${idPrefix}translation`}>
          中文提示（可选，学生端显示）
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
        启用（学生端可练；停用后今天练习与地图里都不再出现）
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
  const [form, setForm] = useState<PassageForm>(emptyForm)
  const canSubmit = form.title.trim().length > 0 && form.text.trim().length > 0

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">新建篇目</CardTitle>
        <CardDescription>
          填写短文并选择主题；相同主题的问答会用于配套练习。
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
            创建
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
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>编辑篇目</DialogTitle>
          <DialogDescription>
            slug 建成后不可改（学生进度与录音都挂在它上面）：{" "}
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
            取消
          </Button>
          <LoadingButton
            disabled={!canSubmit}
            loading={pending}
            onClick={() => onSubmit(form)}
          >
            保存
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function PassageCard({
  mode,
  passage,
  unitTitle,
  expanded,
  onToggle,
  onEdit,
  onDelete,
  onMutated,
}: {
  mode: "reading" | "repeat"
  passage: PassageWithSentences
  unitTitle: string
  expanded: boolean
  onToggle: () => void
  onEdit: () => void
  onDelete: () => void
  onMutated: () => void
}) {
  const { showSuccessToast } = useCustomToast()
  const [sentence, setSentence] = useState({
    text: "",
    suggested_seconds: 8,
    replay_limit: 3,
  })

  const addSentence = useMutation({
    mutationFn: () =>
      AdminService.createSentence({
        passageId: passage.id,
        requestBody: {
          passage_id: passage.id,
          order_index: (passage.sentences ?? []).length,
          text: sentence.text,
          suggested_seconds: sentence.suggested_seconds,
          replay_limit: sentence.replay_limit,
        },
      }),
    onSuccess: () => {
      showSuccessToast("复述句已添加")
      setSentence({ text: "", suggested_seconds: 8, replay_limit: 3 })
      onMutated()
    },
  })

  const deleteSentence = useMutation({
    mutationFn: (id: string) => AdminService.deleteSentence({ sentenceId: id }),
    onSuccess: () => onMutated(),
  })

  const [sentenceToDelete, setSentenceToDelete] = useState<{
    id: string
    text: string | null
  } | null>(null)

  const autoSplit = useMutation({
    mutationFn: () =>
      AdminService.autoSplitSentences({ passageId: passage.id }),
    onSuccess: (data) => {
      toast.success(`已拆分出 ${data.created ?? 0} 句复述句`)
      onMutated()
    },
    onError: (err: { body?: { detail?: string } }) =>
      toast.error(err.body?.detail ?? "拆分失败"),
  })

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-3 space-y-0">
        <div>
          <CardTitle className="text-base">
            {passage.title}{" "}
            <span className="font-normal text-muted-foreground">
              · {passage.topic} · {passage.cefr_band} ·{" "}
              {(passage.sentences ?? []).length} 句复述
            </span>
          </CardTitle>
          <CardDescription className="mt-1 flex flex-wrap items-center gap-2">
            <Badge variant="outline">{unitTitle}</Badge>
            {passage.is_active === false && (
              <Badge variant="secondary">已停用</Badge>
            )}
          </CardDescription>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="sm"
            aria-expanded={expanded}
            onClick={onToggle}
          >
            {expanded ? "收起" : mode === "repeat" ? "管理复述句" : "查看文章"}
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
            aria-label={`编辑 ${passage.title}`}
            onClick={(e) => {
              e.stopPropagation()
              onEdit()
            }}
          >
            <Pencil />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`删除 ${passage.title}`}
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
          {mode === "repeat" && (
            <>
              <div className="space-y-2">
                {(passage.sentences ?? []).map((s, i) => (
                  <div
                    key={s.id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-md border px-3 py-2"
                  >
                    <span className="text-sm">
                      {i + 1}. {s.text}
                      <span className="ml-2 text-xs text-muted-foreground">
                        {s.suggested_seconds} 秒 · 可听{" "}
                        {(s.replay_limit ?? 3) === 0
                          ? "不限"
                          : `${s.replay_limit ?? 3} 次`}
                      </span>
                    </span>
                    <div className="flex items-center gap-1">
                      <RepeatSettings sentence={s} onSaved={onMutated} />
                      <AudioSetter
                        hasAudio={Boolean(s.audio_url)}
                        text={s.text ?? ""}
                        onSet={async (audio_url) => {
                          await AdminService.updateSentence({
                            sentenceId: s.id ?? "",
                            requestBody: {
                              passage_id: passage.id,
                              order_index: s.order_index ?? 0,
                              text: s.text ?? "",
                              translation: s.translation ?? undefined,
                              audio_url,
                              suggested_seconds: s.suggested_seconds ?? 8,
                              replay_limit: s.replay_limit ?? 3,
                            },
                          })
                          onMutated()
                        }}
                      />
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="删除复述句"
                        onClick={() =>
                          s.id &&
                          setSentenceToDelete({ id: s.id, text: s.text })
                        }
                      >
                        <Trash2 className="size-3.5 text-destructive" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => autoSplit.mutate()}
                disabled={
                  autoSplit.isPending || (passage.sentences ?? []).length > 0
                }
                title={
                  (passage.sentences ?? []).length > 0
                    ? "已有复述句，清空后可自动拆分"
                    : "按句切分正文，由短到长取 3 句"
                }
              >
                {autoSplit.isPending ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <Scissors />
                )}
                自动拆分复述句
              </Button>
              <div className="flex flex-wrap items-end gap-2">
                <div className="min-w-64 flex-1 space-y-1">
                  <Label>添加复述句（由短到长）</Label>
                  <Input
                    value={sentence.text}
                    onChange={(e) =>
                      setSentence({ ...sentence, text: e.target.value })
                    }
                  />
                </div>
                <div className="w-24 space-y-1">
                  <Label>秒数</Label>
                  <Input
                    type="number"
                    value={sentence.suggested_seconds}
                    onChange={(e) =>
                      setSentence({
                        ...sentence,
                        suggested_seconds: Number(e.target.value),
                      })
                    }
                  />
                </div>
                <div className="w-28 space-y-1">
                  <Label>可重听</Label>
                  <Input
                    type="number"
                    min={0}
                    max={9}
                    title="0 = 不限次数"
                    value={sentence.replay_limit}
                    onChange={(e) =>
                      setSentence({
                        ...sentence,
                        replay_limit: Math.max(
                          0,
                          Math.min(9, Number(e.target.value) || 0),
                        ),
                      })
                    }
                  />
                </div>
                <Button
                  onClick={() => addSentence.mutate()}
                  disabled={!sentence.text || addSentence.isPending}
                >
                  <Plus />
                  添加
                </Button>
              </div>
            </>
          )}
        </CardContent>
      )}

      <ConfirmDialog
        open={sentenceToDelete !== null}
        title={`删除复述句「${sentenceToDelete?.text ?? ""}」？`}
        description="删除会连同它的标准音一起移除，正在练习的学生下次会拿到别的句子。此操作不可撤销。"
        confirmText="删除复述句"
        onOpenChange={(next) => {
          if (!next) setSentenceToDelete(null)
        }}
        onConfirm={async () => {
          if (sentenceToDelete)
            await deleteSentence.mutateAsync(sentenceToDelete.id)
        }}
      />
    </Card>
  )
}
