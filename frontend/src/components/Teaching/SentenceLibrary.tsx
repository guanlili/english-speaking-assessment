import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Pencil, Plus, Scissors, Trash2 } from "lucide-react"
import { useState } from "react"
import { AdminService, type SentenceWithPassage } from "@/client"
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
import useCustomToast from "@/hooks/useCustomToast"

const NO_PASSAGE = "__none__"

/** 听句复述独立题库：句子直接创建与管理，挂篇目仅为自主练习复用。 */
export function SentenceLibrary() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [keyword, setKeyword] = useState("")
  const [toDelete, setToDelete] = useState<SentenceWithPassage | null>(null)

  const sentencesQuery = useQuery({
    queryKey: ["admin", "sentences"],
    queryFn: () => AdminService.listSentencesFlat(),
  })
  const passagesQuery = useQuery({
    queryKey: ["admin", "passages"],
    queryFn: () => AdminService.listPassages(),
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["admin", "sentences"] })
    void queryClient.invalidateQueries({ queryKey: ["admin", "passages"] })
  }

  const deleteMutation = useMutation({
    mutationFn: (id: string) => AdminService.deleteSentence({ sentenceId: id }),
    onSuccess: () => {
      showSuccessToast("复述句已删除")
      setToDelete(null)
      invalidate()
    },
    onError: (err: { body?: { detail?: string } }) =>
      showErrorToast(err.body?.detail ?? "删除失败"),
  })

  // ── 编辑（与文章朗读编辑弹窗同款：铅笔入口 + 全字段）──
  const [editing, setEditing] = useState<SentenceWithPassage | null>(null)
  const [editForm, setEditForm] = useState({
    text: "",
    translation: "",
    seconds: 12,
    replays: 3,
    passageId: NO_PASSAGE,
  })
  const openEdit = (s: SentenceWithPassage) => {
    setEditing(s)
    setEditForm({
      text: s.text ?? "",
      translation: s.translation ?? "",
      seconds: s.suggested_seconds ?? 12,
      replays: s.replay_limit ?? 3,
      passageId: s.passage_id ?? NO_PASSAGE,
    })
  }
  const updateMutation = useMutation({
    mutationFn: () =>
      AdminService.updateSentence({
        sentenceId: editing?.id ?? "",
        requestBody: {
          order_index: editing?.order_index ?? 0,
          text: editForm.text.trim(),
          translation: editForm.translation.trim() || null,
          suggested_seconds: editForm.seconds,
          replay_limit: editForm.replays,
          passage_id:
            editForm.passageId === NO_PASSAGE ? null : editForm.passageId,
        },
      }),
    onSuccess: () => {
      showSuccessToast("复述句已更新")
      setEditing(null)
      invalidate()
    },
    onError: (err: { body?: { detail?: string } }) =>
      showErrorToast(err.body?.detail ?? "更新失败"),
  })
  const editValid =
    editForm.text.trim().length > 0 &&
    Number.isInteger(editForm.seconds) &&
    editForm.seconds >= 3 &&
    editForm.seconds <= 60 &&
    Number.isInteger(editForm.replays) &&
    editForm.replays >= 0 &&
    editForm.replays <= 9

  const passages = passagesQuery.data ?? []
  const sentences = (sentencesQuery.data ?? []).filter((s) =>
    (s.text ?? "").toLowerCase().includes(keyword.trim().toLowerCase()),
  )

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">听句复述</h1>
        <p className="text-muted-foreground">
          复述句独立成题：直接创建、直接在课堂发布时选用。挂到篇目的句子还会出现在学生的自主练习里。
        </p>
      </div>

      <NewSentenceCard
        passages={passages.map((p) => ({ id: p.id, title: p.title }))}
        onCreated={invalidate}
      />

      <AutoSplitCard
        passages={passages.map((p) => ({
          id: p.id,
          title: p.title,
          sentenceCount: (p.sentences ?? []).length,
        }))}
        onCreated={invalidate}
      />

      <Input
        aria-label="搜索复述句"
        placeholder="搜索复述句…"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
      />
      {sentencesQuery.isPending ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      ) : sentencesQuery.isError ? (
        <div className="flex flex-col items-center gap-3 py-8 text-muted-foreground">
          <p>复述句库加载失败。</p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void sentencesQuery.refetch()}
          >
            重试
          </Button>
        </div>
      ) : sentences.length === 0 ? (
        <p className="py-8 text-center text-muted-foreground">
          还没有复述句，点上方新建开始出题。
        </p>
      ) : (
        <div className="space-y-2">
          {sentences.map((s) => (
            <div
              key={s.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card px-4 py-3"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm">{s.text}</p>
                <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span>{s.suggested_seconds} 秒</span>
                  <span>
                    · 可听
                    {(s.replay_limit ?? 3) === 0
                      ? "不限次数"
                      : ` ${s.replay_limit ?? 3} 次`}
                  </span>
                  {s.passage_title ? (
                    <Badge variant="outline">挂篇目：{s.passage_title}</Badge>
                  ) : (
                    <Badge variant="secondary">独立题目</Badge>
                  )}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="编辑复述句"
                  onClick={() => openEdit(s)}
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
                  aria-label="删除复述句"
                  onClick={() => setToDelete(s)}
                >
                  <Trash2 className="size-3.5 text-destructive" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <Dialog
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>编辑复述句</DialogTitle>
            <DialogDescription>
              修改即时生效；修改句子后原标准音会失效，需重新配置。
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="edit-sentence-text">英文句子</Label>
              <Textarea
                id="edit-sentence-text"
                rows={3}
                value={editForm.text}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, text: e.target.value }))
                }
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="edit-sentence-translation">
                中文提示（可选）
              </Label>
              <Input
                id="edit-sentence-translation"
                value={editForm.translation}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, translation: e.target.value }))
                }
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col gap-2">
                <Label htmlFor="edit-sentence-seconds">作答秒数（3–60）</Label>
                <Input
                  id="edit-sentence-seconds"
                  type="number"
                  min={3}
                  max={60}
                  value={editForm.seconds}
                  onChange={(e) =>
                    setEditForm((f) => ({
                      ...f,
                      seconds: Number(e.target.value),
                    }))
                  }
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="edit-sentence-replays">可听次数（0–9）</Label>
                <Input
                  id="edit-sentence-replays"
                  type="number"
                  min={0}
                  max={9}
                  value={editForm.replays}
                  onChange={(e) =>
                    setEditForm((f) => ({
                      ...f,
                      replays: Number(e.target.value),
                    }))
                  }
                />
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <Label>挂到篇目（可选）</Label>
              <Select
                value={editForm.passageId}
                onValueChange={(v) =>
                  setEditForm((f) => ({ ...f, passageId: v }))
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_PASSAGE}>不挂（独立题目）</SelectItem>
                  {passages.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)}>
              取消
            </Button>
            <LoadingButton
              disabled={!editValid}
              loading={updateMutation.isPending}
              onClick={() => updateMutation.mutate()}
            >
              保存
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={toDelete !== null}
        title={`删除复述句「${toDelete?.text?.slice(0, 20) ?? ""}…」？`}
        description="删除后课堂发布不再可选，正在练习的学生下次会拿到别的句子。此操作不可撤销。"
        confirmText="删除复述句"
        onOpenChange={(next) => {
          if (!next) setToDelete(null)
        }}
        onConfirm={async () => {
          if (toDelete?.id) await deleteMutation.mutateAsync(toDelete.id)
        }}
      />
    </div>
  )
}

function AutoSplitCard({
  passages,
  onCreated,
}: {
  passages: Array<{ id: string; title: string; sentenceCount: number }>
  onCreated: () => void
}) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [passageId, setPassageId] = useState("")
  const ready = passages.filter((p) => p.sentenceCount === 0)
  const selected = ready.find((p) => p.id === passageId)

  const split = useMutation({
    mutationFn: () => AdminService.autoSplitSentences({ passageId }),
    onSuccess: (data) => {
      showSuccessToast(`已拆分出 ${data.created ?? 0} 句复述句`)
      setPassageId("")
      onCreated()
    },
    onError: (err: { body?: { detail?: string } }) =>
      showErrorToast(err.body?.detail ?? "拆分失败"),
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">从篇目自动拆分复述句</CardTitle>
        <CardDescription>
          选一篇还没有复述句的朗读材料，按句切分正文、由短到长自动生成 3
          句；已有复述句的篇目需先删除句子才能再拆分。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Select value={passageId} onValueChange={setPassageId}>
          <SelectTrigger>
            <SelectValue placeholder="选择篇目" />
          </SelectTrigger>
          <SelectContent>
            {ready.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.title}
              </SelectItem>
            ))}
            {ready.length === 0 && (
              <SelectItem value="__none__" disabled>
                暂无可拆分的篇目
              </SelectItem>
            )}
          </SelectContent>
        </Select>
        <Button
          disabled={!selected || split.isPending}
          onClick={() => split.mutate()}
        >
          <Scissors />
          自动拆分复述句
        </Button>
      </CardContent>
    </Card>
  )
}

function NewSentenceCard({
  passages,
  onCreated,
}: {
  passages: Array<{ id: string; title: string }>
  onCreated: () => void
}) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [text, setText] = useState("")
  const [seconds, setSeconds] = useState(12)
  const [replays, setReplays] = useState(3)
  const [passageId, setPassageId] = useState(NO_PASSAGE)

  const create = useMutation({
    mutationFn: () =>
      AdminService.createSentenceStandalone({
        requestBody: {
          order_index: 0,
          text: text.trim(),
          suggested_seconds: seconds,
          replay_limit: replays,
          ...(passageId === NO_PASSAGE
            ? {}
            : { passage_id: passageId, order_index: 999 }),
        },
      }),
    onSuccess: () => {
      showSuccessToast("复述句已创建")
      setText("")
      onCreated()
    },
    onError: (err: { body?: { detail?: string } }) =>
      showErrorToast(err.body?.detail ?? "创建失败"),
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
    <Card>
      <CardHeader>
        <CardTitle className="text-base">新建复述句</CardTitle>
        <CardDescription>
          输入一句英文，设置作答时间与可听次数（0
          表示不限）。可选挂到某篇朗读材料，供学生自主练习复用。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="new-sentence-text">英文句子</Label>
          <Input
            id="new-sentence-text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="I would like to talk about a boring place I visited."
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <div className="space-y-2">
            <Label htmlFor="new-sentence-seconds">作答秒数（3–60）</Label>
            <Input
              id="new-sentence-seconds"
              type="number"
              min={3}
              max={60}
              value={seconds}
              onChange={(e) => setSeconds(Number(e.target.value))}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new-sentence-replays">可听次数（0–9）</Label>
            <Input
              id="new-sentence-replays"
              type="number"
              min={0}
              max={9}
              value={replays}
              onChange={(e) => setReplays(Number(e.target.value))}
            />
          </div>
          <div className="space-y-2">
            <Label>挂到篇目（可选）</Label>
            <Select value={passageId} onValueChange={setPassageId}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_PASSAGE}>不挂（独立题目）</SelectItem>
                {passages.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <Button
          disabled={!valid || create.isPending}
          onClick={() => create.mutate()}
        >
          <Plus />
          创建复述句
        </Button>
      </CardContent>
    </Card>
  )
}
