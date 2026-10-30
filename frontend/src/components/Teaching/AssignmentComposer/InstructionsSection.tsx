import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Pencil, Plus, Trash2 } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import { AdminService, type InstructionPublic } from "@/client"
import { ConfirmDialog } from "@/components/Common/ConfirmDialog"
import {
  CopyContentButton,
  invalidateContentQueries,
} from "@/components/Teaching/CopyContentButton"
import { ReadOnlyContentBadge } from "@/components/Teaching/ReadOnlyContentBadge"
import { Button } from "@/components/ui/button"
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
import { Textarea } from "@/components/ui/textarea"
import { useCanEditContent } from "@/hooks/useCanEditContent"
import { useI18n } from "@/lib/i18n"
import { TERMS } from "@/lib/terms"

/**
 * 题目说明选题区：从说明库勾选 + 内联新建表单（当场写一条，免跳题库）
 * + 删除（带确认；已发布练习的快照不受影响）。
 */
export default function InstructionsSection({
  sectionNo,
  instructions,
  selectedIds,
  onToggle,
  onAddCreated,
  onRemoveDeleted,
  onDirty,
}: {
  sectionNo: number
  instructions: InstructionPublic[]
  selectedIds: string[]
  onToggle: (id: string) => void
  /** 新建的说明自动加入本次选择 */
  onAddCreated: (id: string) => void
  /** 删除的说明从本次选择移除 */
  onRemoveDeleted: (id: string) => void
  /** 表单编辑过的标记（防止服务端指派变更覆盖正在编辑的内容） */
  onDirty: () => void
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const canEdit = useCanEditContent()
  // 说明内联新建表单（组卷时当场写一条说明，免跳题目库）
  const [newTitle, setNewTitle] = useState("")
  const [newText, setNewText] = useState("")
  const [newSeconds, setNewSeconds] = useState(20)
  const [deleteTarget, setDeleteTarget] = useState<InstructionPublic | null>(
    null,
  )
  const [editing, setEditing] = useState<InstructionPublic | null>(null)
  const [editForm, setEditForm] = useState({ title: "", text: "", seconds: 20 })
  // Newly copied/edited instructions stay reachable even outside the current page or search.
  const [recent, setRecent] = useState<InstructionPublic[]>([])
  const remember = (instruction: InstructionPublic) => {
    setRecent((current) => [
      instruction,
      ...current.filter((row) => row.id !== instruction.id),
    ])
  }
  const rows = [
    ...recent.map(
      (item) => instructions.find((row) => row.id === item.id) ?? item,
    ),
    ...instructions.filter((row) => !recent.some((item) => item.id === row.id)),
  ]
  const openEdit = (instruction: InstructionPublic) => {
    onDirty()
    setEditing(instruction)
    setEditForm({
      title: instruction.title ?? "",
      text: instruction.text,
      seconds: instruction.suggested_seconds,
    })
  }
  const updateInstruction = useMutation({
    mutationFn: () =>
      AdminService.updateInstruction({
        instruction_id: editing!.id,
        instructionUpdate: {
          title: editForm.title.trim() || null,
          text: editForm.text.trim(),
          suggested_seconds: editForm.seconds,
        },
      }),
    onSuccess: (updated) => {
      remember(updated)
      queryClient.setQueriesData<InstructionPublic[]>(
        { queryKey: ["admin", "instructions"] },
        (current) =>
          current?.map((row) => (row.id === updated.id ? updated : row)),
      )
      setEditing(null)
      void invalidateContentQueries(queryClient)
      toast.success(
        t({
          zh: "说明已更新；已发布内容不变",
          en: "Instruction updated; published content is unchanged",
        }),
      )
    },
    onError: () =>
      toast.error(
        t({
          zh: "保存失败，请重试；修改内容已保留",
          en: "Save failed. Please retry; your edits are kept.",
        }),
      ),
  })
  const editValid =
    editForm.text.trim().length > 0 &&
    Number.isInteger(editForm.seconds) &&
    editForm.seconds >= 5 &&
    editForm.seconds <= 300

  const createInstruction = useMutation({
    mutationFn: () =>
      AdminService.createInstruction({
        instructionCreate: {
          text: newText.trim(),
          title: newTitle.trim() || null,
          suggested_seconds: newSeconds,
        },
      }),
    onSuccess: async (created) => {
      setNewTitle("")
      setNewText("")
      setNewSeconds(20)
      onDirty()
      remember(created)
      onAddCreated(created.id)
      toast.success(
        t({
          zh: "说明已创建并加入本次练习",
          en: "Instruction created and added to this lesson",
        }),
      )
      await invalidateContentQueries(queryClient)
    },
    onError: () =>
      toast.error(
        t({ zh: "创建失败，请重试", en: "Failed to create, please retry" }),
      ),
  })

  const deleteInstruction = useMutation({
    mutationFn: (id: string) =>
      AdminService.deleteInstruction({ instruction_id: id }),
    onSuccess: async (_, id) => {
      onRemoveDeleted(id)
      setRecent((current) => current.filter((row) => row.id !== id))
      setDeleteTarget(null)
      await invalidateContentQueries(queryClient)
    },
    onError: () =>
      toast.error(
        t({ zh: "删除失败，请重试", en: "Failed to delete, please retry" }),
      ),
  })

  return (
    <section>
      <h2 className="font-semibold">
        {sectionNo}. {t(TERMS.typeInstruction)}
      </h2>
      <p className="mb-3 mt-2 text-sm text-muted-foreground">
        {t({
          zh: "纯文字引导页，可插在任意两题之间（默认排在最前，用下方顺序区调整）；学生读完点「继续」进入下一题。模考中按秒数倒计时，可提前继续。说明不能单独作为练习内容。",
          en: "Text-only intro pages you can slot between any two items (they default to the front — reorder below). Students tap Continue after reading. In exams they are timed by seconds but can be skipped early. Instructions alone can't form a lesson.",
        })}
      </p>
      <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
        {rows.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {t({
              zh: "说明库还是空的，用下方表单新建一条。",
              en: "The instruction bank is empty — create one with the form below.",
            })}
          </p>
        )}
        {rows.map((ins) => (
          <div
            key={ins.id}
            data-testid={`instruction-${ins.id}`}
            className={`flex flex-wrap items-start gap-3 rounded-lg border p-3 ${selectedIds.includes(ins.id) ? "border-primary/50 bg-primary/5" : ""}`}
          >
            <Checkbox
              id={`pick-instruction-${ins.id}`}
              className="mt-0.5"
              checked={selectedIds.includes(ins.id)}
              onCheckedChange={() => onToggle(ins.id)}
            />
            <label
              htmlFor={`pick-instruction-${ins.id}`}
              className="min-h-11 min-w-0 flex-1 basis-36 cursor-pointer"
            >
              <span className="block truncate text-sm">
                {ins.title ? `${ins.title} · ` : ""}
                {ins.text}
              </span>
              <span className="mt-0.5 block text-xs text-muted-foreground">
                {t({
                  zh: `${ins.suggested_seconds} 秒`,
                  en: `${ins.suggested_seconds}s`,
                })}
              </span>
            </label>
            <div className="flex max-w-full flex-wrap items-center gap-2">
              <CopyContentButton
                source={
                  ins.copied_from_id
                    ? { kind: "instruction", id: ins.copied_from_id }
                    : undefined
                }
                label={t({ zh: "复制这条说明", en: "Copy this instruction" })}
                copy={() =>
                  AdminService.copyInstruction({ instruction_id: ins.id })
                }
                onStart={onDirty}
                onCopied={(copy) => {
                  remember(copy)
                  // Append to the draft only; never replace the source or publish here.
                  onDirty()
                  if (!selectedIds.includes(copy.id)) onAddCreated(copy.id)
                  openEdit(copy)
                }}
              />
              {canEdit(ins.owner_id) ? (
                <>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label={t({
                      zh: "编辑这条说明",
                      en: "Edit this instruction",
                    })}
                    onClick={() => openEdit(ins)}
                  >
                    <Pencil />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="text-muted-foreground hover:text-destructive"
                    aria-label={t({
                      zh: "删除这条说明",
                      en: "Delete this instruction",
                    })}
                    onClick={() => setDeleteTarget(ins)}
                  >
                    <Trash2 />
                  </Button>
                </>
              ) : (
                <ReadOnlyContentBadge />
              )}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-3 space-y-2 rounded-lg border border-dashed p-3">
        <p className="text-sm font-medium">
          {t({ zh: "新建说明", en: "New instruction" })}
        </p>
        <Input
          value={newTitle}
          maxLength={100}
          className="text-base"
          placeholder={t({
            zh: "小标题（可选，如「Part B 开始」）",
            en: "Heading (optional, e.g., Part B)",
          })}
          onChange={(event) => {
            onDirty()
            setNewTitle(event.target.value)
          }}
        />
        <Textarea
          value={newText}
          maxLength={2000}
          className="min-h-20 text-base"
          placeholder={t({
            zh: "说明文字（学生会在下一题前看到这段内容）",
            en: "Instruction text (students see this before the next item)",
          })}
          onChange={(event) => {
            onDirty()
            setNewText(event.target.value)
          }}
        />
        <div className="flex flex-wrap items-center gap-2">
          <NumberInput
            id="instruction-seconds"
            min={5}
            max={300}
            value={newSeconds}
            onValueChange={(value) => {
              onDirty()
              setNewSeconds(value)
            }}
            className="w-24 text-base"
            aria-label={t({
              zh: "建议停留秒数（5–300）",
              en: "Suggested seconds (5–300)",
            })}
          />
          <span className="text-xs text-muted-foreground">
            {t({
              zh: "秒（5–300，模考窗口时长）",
              en: "seconds (5–300, exam window length)",
            })}
          </span>
          <LoadingButton
            className="ml-auto"
            loading={createInstruction.isPending}
            disabled={!newText.trim()}
            onClick={() => createInstruction.mutate()}
          >
            <Plus className="size-4" />
            {t({ zh: "创建并加入", en: "Create & add" })}
          </LoadingButton>
        </div>
      </div>
      <Dialog
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open && !updateInstruction.isPending) setEditing(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t({ zh: "编辑题目说明", en: "Edit Instruction" })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: "修改仅用于后续发布；已发布的说明和原有选择不变。复制时会将副本追加到当前草稿。",
                en: "Edits apply to future publishing only; published instructions and existing selections stay unchanged. Copying adds the copy to the current draft.",
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="edit-instruction-title">
                {t({ zh: "小标题（可选）", en: "Heading (optional)" })}
              </Label>
              <Input
                id="edit-instruction-title"
                className="text-base"
                maxLength={100}
                value={editForm.title}
                onChange={(event) => {
                  onDirty()
                  setEditForm((form) => ({
                    ...form,
                    title: event.target.value,
                  }))
                }}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-instruction-text">
                {t({ zh: "说明文字", en: "Instruction text" })}
              </Label>
              <Textarea
                id="edit-instruction-text"
                className="min-h-24 text-base"
                maxLength={2000}
                value={editForm.text}
                onChange={(event) => {
                  onDirty()
                  setEditForm((form) => ({ ...form, text: event.target.value }))
                }}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-instruction-seconds">
                {t({
                  zh: "建议停留秒数（5–300）",
                  en: "Suggested seconds (5–300)",
                })}
              </Label>
              <NumberInput
                id="edit-instruction-seconds"
                className="text-base"
                min={5}
                max={300}
                value={editForm.seconds}
                onValueChange={(seconds) => {
                  onDirty()
                  setEditForm((form) => ({ ...form, seconds }))
                }}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={updateInstruction.isPending}
              onClick={() => setEditing(null)}
            >
              {t({ zh: "取消", en: "Cancel" })}
            </Button>
            <LoadingButton
              type="button"
              disabled={!editValid}
              loading={updateInstruction.isPending}
              onClick={() => updateInstruction.mutate()}
            >
              {t({ zh: "保存", en: "Save" })}
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={deleteTarget !== null}
        title={t({
          zh: "删除这条题目说明？",
          en: "Delete this instruction?",
        })}
        description={t({
          zh: "已发布练习里的说明文字不受影响（发布时已快照）；本次选择中也会一并移除。",
          en: "Published lessons keep their copy (snapshotted at publish); it will also be removed from the current selection.",
        })}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        onConfirm={async () => {
          if (!deleteTarget) return
          onDirty()
          await deleteInstruction.mutateAsync(deleteTarget.id)
        }}
      />
    </section>
  )
}
