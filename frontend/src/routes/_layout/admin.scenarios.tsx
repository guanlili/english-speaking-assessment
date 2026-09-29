import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Loader2, Pencil, Plus, Sparkles, Trash2 } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import { AdminService } from "@/client"
import { ContentNavigation } from "@/components/Admin/ContentNavigation"
import { ConfirmDialog } from "@/components/Common/ConfirmDialog"
import AudioSetter from "@/components/Practice/AudioSetter"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
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
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { APP_NAME } from "@/config"
import useCustomToast from "@/hooks/useCustomToast"

export const Route = createFileRoute("/_layout/admin/scenarios")({
  component: ScenariosAdmin,
  head: () => ({ meta: [{ title: `问答主题与出题 - ${APP_NAME}` }] }),
})

interface QuestionShape {
  id: string
  band: string
  text: string
  translation?: string | null
  audio_url?: string | null
  suggested_seconds?: number
}

interface ScenarioShape {
  id: string
  topic: string
  is_active?: boolean
  questions: QuestionShape[]
}

export function ScenariosAdmin({ embedded = false }: { embedded?: boolean }) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [keyword, setKeyword] = useState("")
  const [newTopic, setNewTopic] = useState("")

  const scenariosQuery = useQuery({
    queryKey: ["admin", "scenarios"],
    queryFn: () => AdminService.listScenarios(),
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["admin", "scenarios"] })
    void queryClient.invalidateQueries({ queryKey: ["admin", "question-bank"] })
  }

  const createScenario = useMutation({
    mutationFn: () =>
      AdminService.createScenario({ requestBody: { topic: newTopic.trim() } }),
    onSuccess: () => {
      showSuccessToast("情景已创建")
      setNewTopic("")
      invalidate()
    },
    onError: (err: { body?: { detail?: string } }) =>
      showErrorToast(err.body?.detail ?? "创建失败"),
  })

  return (
    <div className="flex flex-col gap-6">
      {!embedded && <ContentNavigation />}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          情景问答 · 题目管理
        </h1>
        <p className="text-muted-foreground">
          同一主题，分级练习：KET 对应 A2，PET 对应 B1，另有 B2 进阶题。
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          题目用于课堂练习，非官方考试真题。主题需与篇目的主题一致才会配对。
        </p>
      </div>

      <Card>
        <CardContent className="flex items-end gap-3 py-4">
          <div className="flex-1 space-y-1">
            <Label>新建问答主题</Label>
            <Input
              value={newTopic}
              onChange={(e) => setNewTopic(e.target.value)}
              placeholder="如：School Life"
            />
          </div>
          <Button
            onClick={() => createScenario.mutate()}
            disabled={!newTopic.trim() || createScenario.isPending}
          >
            <Plus />
            创建
          </Button>
        </CardContent>
      </Card>

      <Input
        aria-label="搜索问答主题"
        placeholder="搜索主题…"
        value={keyword}
        onChange={(event) => setKeyword(event.target.value)}
      />
      {scenariosQuery.isPending ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : scenariosQuery.isError ? (
        <div className="flex flex-col items-center gap-3 py-8 text-muted-foreground">
          <p>情景列表加载失败。</p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void scenariosQuery.refetch()}
          >
            重试
          </Button>
        </div>
      ) : (scenariosQuery.data ?? []).length === 0 ? (
        <p className="py-8 text-center text-muted-foreground">
          还没有情景主题，先在上面创建一个（主题需与篇目一致才会配对）。
        </p>
      ) : (
        (scenariosQuery.data ?? [])
          .filter((scenario) =>
            scenario.topic.toLowerCase().includes(keyword.trim().toLowerCase()),
          )
          .map((scenario) => (
            <ScenarioCard
              key={scenario.id}
              scenario={scenario as ScenarioShape}
              onMutated={invalidate}
            />
          ))
      )}
      {scenariosQuery.isSuccess &&
        (scenariosQuery.data ?? []).length > 0 &&
        !(scenariosQuery.data ?? []).some((scenario) =>
          scenario.topic.toLowerCase().includes(keyword.trim().toLowerCase()),
        ) && (
          <p className="py-8 text-center text-muted-foreground">
            没有匹配的主题，请换个关键词。
          </p>
        )}
    </div>
  )
}

function ScenarioCard({
  scenario,
  onMutated,
}: {
  scenario: ScenarioShape
  onMutated: () => void
}) {
  const { showSuccessToast } = useCustomToast()
  const [question, setQuestion] = useState({
    text: "",
    seconds: 30,
  })
  const [topicDraft, setTopicDraft] = useState(scenario.topic)
  const [confirmDeleteQ, setConfirmDeleteQ] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const [gen, setGen] = useState({ count: 3, hint: "" })
  const [drafts, setDrafts] = useState<
    Array<{ id: string; text: string; seconds: number }>
  >([])

  const addQuestion = useMutation({
    mutationFn: (body: { text: string; seconds: number }) =>
      AdminService.createQuestion({
        scenarioId: scenario.id,
        requestBody: {
          scenario_id: scenario.id,
          text: body.text,
          suggested_seconds: body.seconds,
          order_index: scenario.questions.length,
        },
      }),
    onSuccess: () => {
      showSuccessToast("题目已添加")
      setQuestion({ text: "", seconds: 30 })
      onMutated()
    },
    onError: () => toast.error("保存失败，请重试；题目内容已保留"),
  })

  const generateMutation = useMutation({
    mutationFn: () =>
      AdminService.generateQuestions({
        scenarioId: scenario.id,
        requestBody: {
          count: gen.count,
          ...(gen.hint ? { hint: gen.hint } : {}),
        },
      }),
    onSuccess: (data) => {
      setDrafts(
        (data ?? []).map((d) => ({
          id: crypto.randomUUID(),
          text: d.text ?? "",
          seconds: d.suggested_seconds ?? 30,
        })),
      )
    },
    onError: (err: { body?: { detail?: string } }) =>
      toast.error(err.body?.detail ?? "生成失败", {
        description: "需配置方舟密钥后可用；也可手动录入",
      }),
  })

  const adoptDraft = (index: number) => {
    const d = drafts[index]
    addQuestion.mutate(
      { text: d.text, seconds: d.seconds },
      {
        onSuccess: () =>
          setDrafts((current) => current.filter((draft) => draft.id !== d.id)),
      },
    )
  }

  const deleteQuestion = useMutation({
    mutationFn: (id: string) => AdminService.deleteQuestion({ questionId: id }),
    onSuccess: () => onMutated(),
  })

  // ── 编辑题目（与题库页/文章朗读一致的弹窗形态）──
  const [editingQ, setEditingQ] = useState<QuestionShape | null>(null)
  const [editForm, setEditForm] = useState({
    text: "",
    translation: "",
    seconds: 30,
  })
  const openQEdit = (q: QuestionShape) => {
    setEditingQ(q)
    setEditForm({
      text: q.text ?? "",
      translation: q.translation ?? "",
      seconds: q.suggested_seconds ?? 30,
    })
  }
  const updateQuestion = useMutation({
    mutationFn: () =>
      AdminService.updateQuestion({
        questionId: editingQ!.id,
        requestBody: {
          text: editForm.text.trim(),
          translation: editForm.translation.trim() || null,
          suggested_seconds: editForm.seconds,
        },
      }),
    onSuccess: () => {
      toast.success("题目已更新")
      setEditingQ(null)
      onMutated()
    },
    onError: (err: { body?: { detail?: string } }) =>
      toast.error(err.body?.detail ?? "更新失败"),
  })
  const editValid =
    editForm.text.trim().length > 0 &&
    Number.isInteger(editForm.seconds) &&
    editForm.seconds >= 10 &&
    editForm.seconds <= 60

  const updateScenario = useMutation({
    mutationFn: (patch: { topic?: string; is_active?: boolean }) =>
      AdminService.updateScenario({
        scenarioId: scenario.id,
        requestBody: patch,
      }),
    onSuccess: () => {
      showSuccessToast("情景已更新")
      onMutated()
    },
    onError: (err: { body?: { detail?: string } }) =>
      toast.error(err.body?.detail ?? "更新失败"),
  })

  const deleteScenario = useMutation({
    mutationFn: () => AdminService.deleteScenario({ scenarioId: scenario.id }),
    onSuccess: () => {
      setConfirmDelete(false)
      onMutated()
    },
    onError: (err: { body?: { detail?: string } }) =>
      toast.error(err.body?.detail ?? "删除失败"),
  })

  return (
    <Card>
      <CardHeader className="flex-row items-end justify-between gap-3 space-y-0">
        <div className="flex-1 space-y-1">
          <div className="flex items-center gap-2">
            <Input
              aria-label="情景主题"
              className="h-8 max-w-56 font-medium"
              value={topicDraft}
              onChange={(e) => setTopicDraft(e.target.value)}
            />
            <Button
              size="sm"
              variant="outline"
              disabled={
                topicDraft.trim().length === 0 ||
                topicDraft === scenario.topic ||
                updateScenario.isPending
              }
              onClick={() =>
                updateScenario.mutate({ topic: topicDraft.trim() })
              }
            >
              改名
            </Button>
            {scenario.is_active === false && (
              <Badge variant="secondary">已停用</Badge>
            )}
          </div>
          <CardDescription>
            {scenario.topic === "School Life" ? "学校生活 · " : ""}共{" "}
            {scenario.questions.length} 道题
          </CardDescription>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 whitespace-nowrap text-sm">
            <Checkbox
              checked={scenario.is_active !== false}
              onCheckedChange={(checked) =>
                updateScenario.mutate({ is_active: checked === true })
              }
            />
            启用
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`删除情景 ${scenario.topic}`}
            onClick={() => setConfirmDelete(true)}
          >
            <Trash2 className="text-destructive" />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <details>
          <summary className="cursor-pointer text-sm font-medium text-primary">
            展开题目 · 手动添加 / AI 起草
          </summary>
          <div className="mt-4 space-y-3">
            <div className="space-y-1">
              <Badge variant="outline">共 {scenario.questions.length} 道</Badge>
              {scenario.questions.map((q, index) => (
                <div
                  key={q.id}
                  className="flex items-center justify-between gap-3 rounded-md border px-3 py-2"
                >
                  <div className="space-y-1">
                    <p className="text-sm">
                      {index + 1}. {q.text}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      建议作答 {q.suggested_seconds} 秒
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`编辑题目 ${index + 1}`}
                      onClick={() => openQEdit(q)}
                    >
                      <Pencil className="size-3.5" />
                    </Button>
                    <AudioSetter
                      hasAudio={Boolean(q.audio_url)}
                      text={q.text ?? ""}
                      onSet={async (audio_url) => {
                        await AdminService.updateQuestion({
                          questionId: q.id,
                          requestBody: { audio_url },
                        })
                        onMutated()
                      }}
                    />
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="删除题目"
                      onClick={() => setConfirmDeleteQ(q.id)}
                    >
                      <Trash2 className="size-3.5 text-destructive" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap items-end gap-2 border-t pt-3">
              <div className="min-w-56 flex-1 space-y-1">
                <Label>题目</Label>
                <Input
                  value={question.text}
                  onChange={(e) =>
                    setQuestion({ ...question, text: e.target.value })
                  }
                />
              </div>
              <div className="w-24 space-y-1">
                <Label>秒数</Label>
                <Input
                  type="number"
                  value={question.seconds}
                  onChange={(e) =>
                    setQuestion({
                      ...question,
                      seconds: Number(e.target.value),
                    })
                  }
                />
              </div>
              <Button
                onClick={() =>
                  addQuestion.mutate({
                    text: question.text,
                    seconds: question.seconds,
                  })
                }
                disabled={!question.text || addQuestion.isPending}
              >
                <Plus />
                添加
              </Button>
            </div>

            {/* AI 起草（不入库，采纳后才保存） */}
            <div className="space-y-2 border-t pt-3">
              <div className="flex flex-wrap items-end gap-2">
                <div className="w-24 space-y-1">
                  <Label>数量</Label>
                  <Input
                    type="number"
                    min={1}
                    max={10}
                    value={gen.count}
                    onChange={(e) =>
                      setGen({ ...gen, count: Number(e.target.value) })
                    }
                  />
                </div>
                <div className="min-w-48 flex-1 space-y-1">
                  <Label>要求（可选）</Label>
                  <Input
                    value={gen.hint}
                    onChange={(e) => setGen({ ...gen, hint: e.target.value })}
                    placeholder="如：贴近校园生活"
                  />
                </div>
                <Button
                  variant="secondary"
                  onClick={() => {
                    setDrafts([])
                    generateMutation.mutate()
                  }}
                  disabled={generateMutation.isPending}
                >
                  {generateMutation.isPending ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    <Sparkles />
                  )}
                  AI 起草
                </Button>
              </div>

              {drafts.length > 0 && (
                <div className="space-y-2 rounded-md border border-dashed p-2">
                  <p className="text-xs text-muted-foreground">
                    AI 草稿（可编辑后采纳；不会自动入库）
                  </p>
                  {drafts.map((d, i) => (
                    <div
                      key={d.id}
                      className="flex flex-wrap items-center gap-2"
                    >
                      <Input
                        className="min-w-48 flex-1"
                        value={d.text}
                        onChange={(e) => {
                          const next = [...drafts]
                          next[i] = { ...d, text: e.target.value }
                          setDrafts(next)
                        }}
                      />
                      <Input
                        className="w-16"
                        type="number"
                        value={d.seconds}
                        onChange={(e) => {
                          const next = [...drafts]
                          next[i] = { ...d, seconds: Number(e.target.value) }
                          setDrafts(next)
                        }}
                      />
                      <Button
                        size="sm"
                        disabled={
                          addQuestion.isPending ||
                          !d.text.trim() ||
                          !Number.isInteger(d.seconds) ||
                          d.seconds < 10 ||
                          d.seconds > 60
                        }
                        onClick={() => adoptDraft(i)}
                      >
                        采纳
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          setDrafts(drafts.filter((_, j) => j !== i))
                        }
                      >
                        丢弃
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </details>
      </CardContent>
      <Dialog
        open={editingQ !== null}
        onOpenChange={(open) => !open && setEditingQ(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>编辑题目</DialogTitle>
            <DialogDescription>
              修改即时生效；学生下一轮抽题使用新内容。
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="scn-q-text">英文题目</Label>
              <Textarea
                id="scn-q-text"
                rows={3}
                value={editForm.text}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, text: e.target.value }))
                }
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="scn-q-translation">中文提示（可选）</Label>
              <Input
                id="scn-q-translation"
                value={editForm.translation}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, translation: e.target.value }))
                }
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="scn-q-seconds">建议秒数（10–60）</Label>
              <Input
                id="scn-q-seconds"
                type="number"
                min={10}
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
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingQ(null)}>
              取消
            </Button>
            <LoadingButton
              disabled={!editValid}
              loading={updateQuestion.isPending}
              onClick={() => updateQuestion.mutate()}
            >
              保存
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={confirmDelete}
        title={`删除情景「${scenario.topic}」？`}
        description="该主题下的全部题目与录音都会一起删除，学生端不再出现这个主题。此操作不可撤销。"
        confirmText="删除情景"
        onOpenChange={setConfirmDelete}
        onConfirm={async () => {
          await deleteScenario.mutateAsync()
        }}
      />

      <ConfirmDialog
        open={confirmDeleteQ !== null}
        title="删除这道题？"
        description="删除后学生端不再出现这道题，已有作答记录保留。此操作不可撤销。"
        confirmText="删除"
        onOpenChange={(v) => {
          if (!v) setConfirmDeleteQ(null)
        }}
        onConfirm={async () => {
          if (confirmDeleteQ) deleteQuestion.mutate(confirmDeleteQ)
          setConfirmDeleteQ(null)
        }}
      />
    </Card>
  )
}
