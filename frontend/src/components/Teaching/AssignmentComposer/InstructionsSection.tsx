import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Plus, Trash2 } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import { AdminService, type InstructionPublic } from "@/client"
import { ConfirmDialog } from "@/components/Common/ConfirmDialog"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import { NumberInput } from "@/components/ui/number-input"
import { Textarea } from "@/components/ui/textarea"
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
  // 说明内联新建表单（组卷时当场写一条说明，免跳题目库）
  const [newTitle, setNewTitle] = useState("")
  const [newText, setNewText] = useState("")
  const [newSeconds, setNewSeconds] = useState(20)
  const [deleteTarget, setDeleteTarget] = useState<InstructionPublic | null>(
    null,
  )

  const createInstruction = useMutation({
    mutationFn: () =>
      AdminService.createInstruction({
        requestBody: {
          text: newText.trim(),
          title: newTitle.trim() || null,
          suggested_seconds: newSeconds,
        },
      }),
    onSuccess: async (created) => {
      setNewTitle("")
      setNewText("")
      setNewSeconds(20)
      onAddCreated(created.id)
      toast.success(
        t({
          zh: "说明已创建并加入本次练习",
          en: "Instruction created and added to this lesson",
        }),
      )
      await queryClient.invalidateQueries({
        queryKey: ["admin", "instructions"],
      })
    },
    onError: () =>
      toast.error(
        t({ zh: "创建失败，请重试", en: "Failed to create, please retry" }),
      ),
  })

  const deleteInstruction = useMutation({
    mutationFn: (id: string) =>
      AdminService.deleteInstruction({ instructionId: id }),
    onSuccess: async () => {
      setDeleteTarget(null)
      await queryClient.invalidateQueries({
        queryKey: ["admin", "instructions"],
      })
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
        {instructions.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {t({
              zh: "说明库还是空的，用下方表单新建一条。",
              en: "The instruction bank is empty — create one with the form below.",
            })}
          </p>
        )}
        {instructions.map((ins) => (
          <div
            key={ins.id}
            className={`flex items-start gap-3 rounded-lg border p-3 ${selectedIds.includes(ins.id) ? "border-primary/50 bg-primary/5" : ""}`}
          >
            <Checkbox
              id={`pick-instruction-${ins.id}`}
              className="mt-0.5"
              checked={selectedIds.includes(ins.id)}
              onCheckedChange={() => onToggle(ins.id)}
            />
            <label
              htmlFor={`pick-instruction-${ins.id}`}
              className="min-w-0 flex-1 cursor-pointer"
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
            <Button
              variant="ghost"
              size="icon-sm"
              className="text-muted-foreground hover:text-destructive"
              aria-label={t({
                zh: "删除这条说明",
                en: "Delete this instruction",
              })}
              onClick={() => setDeleteTarget(ins)}
            >
              <Trash2 />
            </Button>
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
          onRemoveDeleted(deleteTarget.id)
          await deleteInstruction.mutateAsync(deleteTarget.id)
        }}
      />
    </section>
  )
}
