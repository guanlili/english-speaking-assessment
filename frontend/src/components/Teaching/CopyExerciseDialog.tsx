import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useRef, useState } from "react"
import { toast } from "sonner"
import { ClassesService, type ClassroomExercisePublic } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useI18n } from "@/lib/i18n"

export function CopyExerciseDialog({
  code,
  exercise,
  onClose,
  onCopied,
}: {
  code: string
  exercise: ClassroomExercisePublic
  onClose: () => void
  onCopied?: () => void
}) {
  const { t } = useI18n()
  const client = useQueryClient()
  const identityToken = useRef(localStorage.getItem("access_token"))
  const navigate = useNavigate()
  const [target, setTarget] = useState(code)
  const [replace, setReplace] = useState(false)
  const classes = useQuery({
    queryKey: ["classrooms"],
    queryFn: ClassesService.listMyClassrooms,
  })
  const draft = useQuery({
    queryKey: ["teacher", "composer-draft", target],
    queryFn: () => ClassesService.readComposerDraft({ code: target }),
    staleTime: 0,
  })
  const copy = useMutation({
    mutationFn: async () => {
      const state = await ClassesService.readExerciseComposerSeed({
        code,
        exerciseId: exercise.id,
      })
      if (localStorage.getItem("access_token") !== identityToken.current)
        throw new Error("Session changed")
      const classroom = classes.data?.find((row) => row.code === target)
      return ClassesService.saveComposerDraft({
        code: target,
        requestBody: {
          expected_revision: draft.data?.revision ?? 0,
          state: {
            ...state,
            base_exercise_id: classroom?.current_exercise_id ?? null,
          },
        },
      })
    },
    onSuccess: async (result) => {
      if (localStorage.getItem("access_token") !== identityToken.current) return
      client.setQueryData(["teacher", "composer-draft", target], result)
      toast.success(
        t({
          zh: "已复制到目标课堂草稿，请预览确认后发布。",
          en: "Copied to the target class draft. Review before publishing.",
        }),
      )
      onClose()
      onCopied?.()
      if (target !== code)
        await navigate({ to: "/t/$code", params: { code: target } })
    },
    onError: () =>
      toast.error(
        t({
          zh: "复制失败，草稿可能已被其他设备修改；请刷新后重试。",
          en: "Copy failed. The draft may have changed on another device; refresh and retry.",
        }),
      ),
  })
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !copy.isPending) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t({ zh: "复制为新练习草稿", en: "Copy to a new practice draft" })}
          </DialogTitle>
          <DialogDescription>
            {t({
              zh: "复制选题、顺序和考试模式；题文、音频及逐题设置使用题库当前版本，旧成绩不复制。请核对预览后发布，不会立即改变学生练习。",
              en: "Copies selections, order and exam mode. Text, audio and item settings use the current question bank; results are not copied. Review the preview before publishing. Student practice will not change yet.",
            })}
          </DialogDescription>
        </DialogHeader>
        <label className="space-y-2 text-sm">
          <span>{t({ zh: "目标课堂", en: "Target classroom" })}</span>
          <select
            disabled={copy.isPending}
            className="h-11 w-full rounded-md border px-3 text-base"
            value={target}
            onChange={(event) => {
              setTarget(event.target.value)
              setReplace(false)
            }}
          >
            {(classes.data ?? [])
              .filter((row) => row.is_active)
              .map((row) => (
                <option key={row.id} value={row.code}>
                  {row.name} · {row.code}
                </option>
              ))}
          </select>
        </label>
        {(classes.isError || draft.isError) && (
          <p role="alert">
            {t({
              zh: "加载失败，请关闭后重试。",
              en: "Could not load. Close and retry.",
            })}
          </p>
        )}
        {draft.data && (
          <label className="flex min-h-11 items-center gap-3 text-sm">
            <input
              type="checkbox"
              checked={replace}
              onChange={(event) => setReplace(event.target.checked)}
              disabled={copy.isPending}
              className="size-5"
            />
            {t({
              zh: "替换我在目标课堂已有的草稿",
              en: "Replace my existing draft in the target classroom",
            })}
          </label>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={copy.isPending}>
            {t({ zh: "取消", en: "Cancel" })}
          </Button>
          <Button
            className="min-h-11"
            disabled={
              copy.isPending ||
              !classes.data?.some(
                (row) => row.code === target && row.is_active,
              ) ||
              draft.isPending ||
              draft.isError ||
              Boolean(draft.data && !replace)
            }
            onClick={() => copy.mutate()}
          >
            {t({ zh: "复制到草稿", en: "Copy to draft" })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
