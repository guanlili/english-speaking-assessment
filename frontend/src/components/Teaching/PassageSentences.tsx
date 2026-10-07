import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Pencil, Plus, Scissors, Trash2 } from "lucide-react"
import { useState } from "react"
import {
  AdminService,
  type PassageWithSentences,
  type RepeatSentence,
} from "@/client"
import { ConfirmDialog } from "@/components/Common/ConfirmDialog"
import AudioSetter from "@/components/Practice/AudioSetter"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"
import { EXAM_LEVEL_LABELS, TERMS, VOCAB_LEVEL_ORDER } from "@/lib/terms"

/** 篇目卡内联的复述句管理（题库三层：主题→篇目→句子的最底层）。 */
export function PassageSentences({
  passage,
  onMutated,
}: {
  passage: PassageWithSentences
  onMutated: () => void
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const sentences = passage.sentences ?? []

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["admin", "passages"] })
    void queryClient.invalidateQueries({ queryKey: ["admin", "sentences"] })
    onMutated()
  }

  const [addOpen, setAddOpen] = useState(false)
  const [editing, setEditing] = useState<RepeatSentence | null>(null)
  const [toDelete, setToDelete] = useState<RepeatSentence | null>(null)

  const autoSplit = useMutation({
    mutationFn: () =>
      AdminService.autoSplitSentences({ passageId: passage.id ?? "" }),
    onSuccess: (data) => {
      showSuccessToast(
        t({
          zh: `已生成 ${data.created ?? 0} 道听句复述题`,
          en: `Created ${data.created ?? 0} listen-and-repeat items`,
        }),
      )
      invalidate()
    },
    onError: () =>
      showErrorToast(
        t({
          zh: "生成失败，请确认正文至少有 3 句且尚无听句复述题",
          en: "Couldn't generate items. Check that the text has at least 3 sentences and no existing listen-and-repeat items.",
        }),
      ),
  })

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">
          {t(TERMS.typeRepeat)}{" "}
          <span className="text-xs text-muted-foreground">
            {t({
              zh: `· ${sentences.length} 句`,
              en: `· ${sentences.length}`,
            })}
          </span>
        </p>
        <div className="flex gap-1.5">
          {sentences.length === 0 && (
            <Button
              variant="outline"
              size="sm"
              disabled={autoSplit.isPending}
              title={t({
                zh: "从正文选出 3 句，生成听音后复述的题目；学生作答时不显示文字",
                en: "Select 3 sentences for listen-and-repeat items; students won't see the text while answering",
              })}
              onClick={() => autoSplit.mutate()}
            >
              <Scissors />
              {t({
                zh: "生成听句复述题",
                en: "Create listen-and-repeat items",
              })}
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => setAddOpen(true)}>
            <Plus />
            {t({ zh: "添加句子", en: "Add Sentence" })}
          </Button>
        </div>
      </div>
      {sentences.length === 0 ? (
        <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
          {t({
            zh: "本篇还没有听句复述题：可以手动添加，或从正文选出 3 句生成。",
            en: "No listen-and-repeat items yet — add one manually or generate 3 from the text.",
          })}
        </p>
      ) : (
        <ul className="space-y-1.5">
          {sentences.map((s, index) => (
            <li
              key={s.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm">
                  {index + 1}. {s.text}
                </p>
                <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span>
                    {t({
                      zh: `${s.suggested_seconds} 秒 · 可听 ${(s.replay_limit ?? 3) === 0 ? "不限" : `${s.replay_limit ?? 3} 次`}`,
                      en: `${s.suggested_seconds}s · ${(s.replay_limit ?? 3) === 0 ? "unlimited replays" : `${s.replay_limit ?? 3} replays`}`,
                    })}
                  </span>
                  {s.exam_level && (
                    <Badge variant="outline" className="text-[10px]">
                      {t(
                        EXAM_LEVEL_LABELS[s.exam_level] ?? {
                          zh: s.exam_level,
                          en: s.exam_level,
                        },
                      )}
                    </Badge>
                  )}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-0.5">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t({
                    zh: "编辑复述句",
                    en: "Edit repeat sentence",
                  })}
                  onClick={() => setEditing(s)}
                >
                  <Pencil className="size-3.5" />
                </Button>
                <AudioSetter
                  hasAudio={Boolean(s.audio_url)}
                  text={s.text ?? ""}
                  onSet={async (audio_url) => {
                    await AdminService.updateSentence({
                      sentenceId: s.id ?? "",
                      requestBody: {
                        order_index: s.order_index ?? 0,
                        text: s.text ?? "",
                        translation: s.translation ?? undefined,
                        audio_url,
                        suggested_seconds: s.suggested_seconds ?? 12,
                        replay_limit: s.replay_limit ?? 3,
                      },
                    })
                    invalidate()
                  }}
                />
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t({
                    zh: "删除复述句",
                    en: "Delete repeat sentence",
                  })}
                  onClick={() => setToDelete(s)}
                >
                  <Trash2 className="size-3.5 text-destructive" />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <SentenceFormDialog
        passageId={passage.id ?? ""}
        open={addOpen}
        editing={null}
        onClose={() => setAddOpen(false)}
        onSaved={invalidate}
      />
      <SentenceFormDialog
        passageId={passage.id ?? ""}
        open={editing !== null}
        editing={editing}
        onClose={() => setEditing(null)}
        onSaved={invalidate}
      />

      <ConfirmDialog
        open={toDelete !== null}
        title={t({
          zh: `删除复述句「${toDelete?.text?.slice(0, 20) ?? ""}…」？`,
          en: `Delete repeat sentence "${toDelete?.text?.slice(0, 20) ?? ""}…"?`,
        })}
        description={t({
          zh: "删除后课堂发布不再可选，正在练习的学生下次会拿到别的句子。此操作不可撤销。",
          en: "Once deleted, it can no longer be chosen when publishing; students mid-practice will get a different sentence next time. This cannot be undone.",
        })}
        confirmText={t({ zh: "删除复述句", en: "Delete Repeat Sentence" })}
        onOpenChange={(next) => {
          if (!next) setToDelete(null)
        }}
        onConfirm={async () => {
          if (toDelete?.id) {
            await AdminService.deleteSentence({ sentenceId: toDelete.id })
            setToDelete(null)
            invalidate()
          }
        }}
      />
    </div>
  )
}

/** 新建/编辑复述句共用弹窗（挂在本篇目下；editing 为 null 时是新建）。 */
function SentenceFormDialog({
  passageId,
  open,
  editing,
  onClose,
  onSaved,
}: {
  passageId: string
  open: boolean
  editing: RepeatSentence | null
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useI18n()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [text, setText] = useState("")
  const [translation, setTranslation] = useState("")
  const [seconds, setSeconds] = useState(12)
  const [replays, setReplays] = useState(3)
  const [examLevel, setExamLevel] = useState("")
  const [loadedId, setLoadedId] = useState<string | null>(null)

  const editKey = editing?.id ?? ""
  if (open && editing && editKey !== loadedId) {
    setLoadedId(editKey)
    setText(editing.text ?? "")
    setTranslation(editing.translation ?? "")
    setSeconds(editing.suggested_seconds ?? 12)
    setReplays(editing.replay_limit ?? 3)
    setExamLevel(editing.exam_level ?? "")
  }
  if (!open && loadedId !== null) setLoadedId(null)
  if (open && editing === null && loadedId !== "new") {
    // 新建弹窗每次打开时重置
    setLoadedId("new")
    setText("")
    setTranslation("")
    setSeconds(12)
    setReplays(3)
    setExamLevel("")
  }

  const save = useMutation({
    mutationFn: () => {
      if (editing) {
        return AdminService.updateSentence({
          sentenceId: editing.id ?? "",
          requestBody: {
            order_index: editing.order_index ?? 0,
            text: text.trim(),
            translation: translation.trim() || null,
            suggested_seconds: seconds,
            replay_limit: replays,
            passage_id: editing.passage_id ?? passageId,
            exam_kind: examLevel ? "toefl_lnr" : null,
            exam_level: examLevel || null,
          },
        })
      }
      return AdminService.createSentenceStandalone({
        requestBody: {
          order_index: 0,
          text: text.trim(),
          suggested_seconds: seconds,
          replay_limit: replays,
          passage_id: passageId,
          ...(examLevel
            ? { exam_kind: "toefl_lnr", exam_level: examLevel }
            : {}),
        },
      })
    },
    onSuccess: () => {
      showSuccessToast(
        editing
          ? t({ zh: "复述句已更新", en: "Repeat sentence updated" })
          : t({ zh: "复述句已创建", en: "Repeat sentence created" }),
      )
      onClose()
      onSaved()
    },
    onError: (err: { body?: { detail?: string } }) =>
      showErrorToast(
        err.body?.detail ?? t({ zh: "保存失败", en: "Failed to save" }),
      ),
  })

  const valid =
    text.trim().length > 0 &&
    Number.isInteger(seconds) &&
    seconds >= 3 &&
    seconds <= 60 &&
    Number.isInteger(replays) &&
    replays >= 0 &&
    replays <= 9

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {editing
              ? t({ zh: "编辑复述句", en: "Edit Repeat Sentence" })
              : t({ zh: "添加复述句", en: "Add Repeat Sentence" })}
          </DialogTitle>
          <DialogDescription>
            {t({
              zh: "句子挂在本篇目下，随篇目出现在自主练习；也可在课堂发布时单独勾选。",
              en: "The sentence belongs to this passage and appears in self practice with it; it can also be picked when publishing.",
            })}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="ps-sentence-text">
              {t({ zh: "英文句子", en: "English Sentence" })}
            </Label>
            <Textarea
              id="ps-sentence-text"
              rows={3}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="ps-sentence-translation">
              {t({ zh: "中文提示（可选）", en: "Chinese Hint (optional)" })}
            </Label>
            <Input
              id="ps-sentence-translation"
              value={translation}
              onChange={(e) => setTranslation(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="ps-sentence-seconds">
                {t({ zh: "作答秒数（3–60）", en: "Answer Seconds (3–60)" })}
              </Label>
              <NumberInput
                id="ps-sentence-seconds"
                min={3}
                max={60}
                value={seconds}
                onValueChange={setSeconds}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="ps-sentence-replays">
                {t({ zh: "可听次数（0–9）", en: "Replays (0–9)" })}
              </Label>
              <NumberInput
                id="ps-sentence-replays"
                min={0}
                max={9}
                value={replays}
                onValueChange={setReplays}
              />
            </div>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="ps-sentence-exam-level">
              {t({ zh: "考试级别（可选）", en: "Exam level (optional)" })}
            </Label>
            <select
              id="ps-sentence-exam-level"
              value={examLevel}
              onChange={(e) => setExamLevel(e.target.value)}
              className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground"
            >
              <option value="">
                {t({ zh: "普通听令复述", en: "Regular listen & repeat" })}
              </option>
              {VOCAB_LEVEL_ORDER.map((level) => (
                <option key={level} value={level}>
                  {t(EXAM_LEVEL_LABELS[level])}
                  {t({ zh: "（课堂版）", en: " (classroom)" })}
                </option>
              ))}
            </select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t({ zh: "取消", en: "Cancel" })}
          </Button>
          <LoadingButton
            disabled={!valid}
            loading={save.isPending}
            onClick={() => save.mutate()}
          >
            {editing
              ? t({ zh: "保存", en: "Save" })
              : t({ zh: "创建", en: "Create" })}
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
