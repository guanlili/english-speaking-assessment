import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Settings2 } from "lucide-react"
import { useState } from "react"
import { AdminService, type ExamItemSettings } from "@/client"
import AudioSetter from "@/components/Practice/AudioSetter"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { useI18n } from "@/lib/i18n"

export default function ExamItemSettingsButton({
  itemType,
  itemId,
  text,
}: {
  itemType: "passage" | "repeat" | "question" | "instruction"
  itemId: string
  text: string
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="shrink-0"
          onClick={(e) => e.stopPropagation()}
          aria-label={t({ zh: "考试流程设置", en: "Exam flow settings" })}
        >
          <Settings2 className="size-4" />
        </Button>
      </DialogTrigger>
      <DialogContent onClick={(e) => e.stopPropagation()}>
        <DialogHeader>
          <DialogTitle>
            {t({ zh: "考试流程设置", en: "Exam flow settings" })}
          </DialogTitle>
        </DialogHeader>
        {open && (
          <SettingsEditor
            itemType={itemType}
            itemId={itemId}
            text={text}
            onSaved={() => setOpen(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

function SettingsEditor({
  itemType,
  itemId,
  text,
  onSaved,
}: {
  itemType: "passage" | "repeat" | "question" | "instruction"
  itemId: string
  text: string
  onSaved: () => void
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ["exam-settings", itemType, itemId],
    queryFn: () => AdminService.readExamItemSettings({ itemType, itemId }),
  })
  const [edited, setEdited] = useState<ExamItemSettings | null>(null)
  const value = edited ?? query.data
  const mutation = useMutation({
    mutationFn: (requestBody: ExamItemSettings) =>
      AdminService.updateExamItemSettings({ itemType, itemId, requestBody }),
    onSuccess: (data) => {
      // 用返回值同步缓存：60s staleTime 内重开弹窗必须看到刚保存的值，
      // 否则下次保存会把旧值一起写回。
      queryClient.setQueryData(["exam-settings", itemType, itemId], data)
      onSaved()
    },
  })
  if (!value)
    return (
      <p>
        {t(
          query.isError
            ? {
                zh: "加载失败，请重新打开",
                en: "Could not load. Reopen to retry.",
              }
            : { zh: "加载中…", en: "Loading…" },
        )}
      </p>
    )
  const fields = [
    {
      key: "wait_seconds" as const,
      max: 60,
      label: t({
        zh: "新题出现后等待（秒）",
        en: "Wait after item appears (seconds)",
      }),
      show: true,
    },
    {
      key: "prep_seconds" as const,
      max: 180,
      label: t({
        zh: "准备时间（秒；留空沿用题目设置）",
        en: "Preparation (seconds; blank uses item default)",
      }),
      show: itemType === "question",
    },
    {
      key: "after_audio_seconds" as const,
      max: 60,
      label: t({
        zh: "录音前缓冲等待（秒）",
        en: "Wait before recording (seconds)",
      }),
      show: itemType === "repeat" || itemType === "question",
    },
  ]
  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault()
        mutation.mutate(value)
      }}
    >
      <p className="text-sm text-muted-foreground">
        {t({
          zh: "保存到题库，下次发布考试时生效。已发布考试保留原设置。",
          en: "Saved to the question bank for future exams. Published exams keep their original settings.",
        })}
      </p>
      {fields
        .filter((f) => f.show)
        .map((f) => (
          <label key={f.key} className="grid gap-2 text-sm">
            {f.label}
            <input
              type="number"
              min={0}
              max={f.max}
              required={f.key !== "prep_seconds"}
              className="min-h-11 rounded-md border px-3 text-base"
              value={value[f.key] ?? ""}
              onChange={(e) =>
                setEdited({
                  ...value,
                  [f.key]:
                    e.target.value === "" ? null : Number(e.target.value),
                })
              }
            />
          </label>
        ))}
      {itemType !== "passage" && (
        <div className="flex flex-wrap items-center gap-2">
          <p className="w-full text-sm text-muted-foreground">
            {t({
              zh: "自动考试的说明、复述和问答题须有音频；可在此生成或上传，也可沿用题目已有的标准音。",
              en: "Automated exam instructions, repeat items and questions require audio. Generate or upload it here, or use the item's existing standard audio.",
            })}
          </p>
          <span>{t({ zh: "考试播放音频", en: "Exam audio" })}</span>
          <AudioSetter
            text={text}
            audioUrl={value.audio_url}
            onSet={async (audio_url) => setEdited({ ...value, audio_url })}
          />
        </div>
      )}
      {mutation.isError && (
        <p role="alert">
          {t({ zh: "保存失败，请重试", en: "Could not save. Please retry." })}
        </p>
      )}
      <Button type="submit" disabled={mutation.isPending} className="min-h-11">
        {t({ zh: "保存", en: "Save" })}
      </Button>
    </form>
  )
}
