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
import { NumberInput } from "@/components/ui/number-input"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { APP_NAME } from "@/config"
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"
import { randomId } from "@/utils"

export const Route = createFileRoute("/_layout/admin/scenarios")({
  component: ScenariosAdmin,
  head: () => ({
    meta: [{ title: `问答主题与出题 / Topics & Questions - ${APP_NAME}` }],
  }),
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
  const { t } = useI18n()
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
      showSuccessToast(t({ zh: "情景已创建", en: "Topic created" }))
      setNewTopic("")
      invalidate()
    },
    onError: (err: { body?: { detail?: string } }) =>
      showErrorToast(
        err.body?.detail ?? t({ zh: "创建失败", en: "Create failed" }),
      ),
  })

  return (
    <div className="flex flex-col gap-6">
      {!embedded && <ContentNavigation />}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          {t({ zh: "情景问答 · 题目管理", en: "Scenario Q&A · Questions" })}
        </h1>
        <p className="text-muted-foreground">
          {t({
            zh: "同一主题，分级练习：KET 对应 A2，PET 对应 B1，另有 B2 进阶题。",
            en: "One topic, graded practice: KET maps to A2, PET to B1, plus B2 advanced questions.",
          })}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          {t({
            zh: "题目用于课堂练习，非官方考试真题。主题需与篇目的主题一致才会配对。",
            en: "Questions are for classroom practice, not official past papers. Topics must match passage topics to pair up.",
          })}
        </p>
      </div>

      <Card>
        <CardContent className="flex items-end gap-3 py-4">
          <div className="flex-1 space-y-1">
            <Label>{t({ zh: "新建问答主题", en: "New Q&A Topic" })}</Label>
            <Input
              value={newTopic}
              onChange={(e) => setNewTopic(e.target.value)}
              placeholder={t({ zh: "如：School Life", en: "e.g. School Life" })}
            />
          </div>
          <Button
            onClick={() => createScenario.mutate()}
            disabled={!newTopic.trim() || createScenario.isPending}
          >
            <Plus />
            {t({ zh: "创建", en: "Create" })}
          </Button>
        </CardContent>
      </Card>

      <Input
        aria-label={t({ zh: "搜索问答主题", en: "Search Q&A topics" })}
        placeholder={t({ zh: "搜索主题…", en: "Search topics…" })}
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
          <p>{t({ zh: "情景列表加载失败。", en: "Failed to load topics." })}</p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void scenariosQuery.refetch()}
          >
            {t({ zh: "重试", en: "Retry" })}
          </Button>
        </div>
      ) : (scenariosQuery.data ?? []).length === 0 ? (
        <p className="py-8 text-center text-muted-foreground">
          {t({
            zh: "还没有情景主题，先在上面创建一个（主题需与篇目一致才会配对）。",
            en: "No topics yet — create one above (topics must match passage topics to pair up).",
          })}
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
            {t({
              zh: "没有匹配的主题，请换个关键词。",
              en: "No topics match — try another keyword.",
            })}
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
  const { t } = useI18n()
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
      showSuccessToast(t({ zh: "题目已添加", en: "Question added" }))
      setQuestion({ text: "", seconds: 30 })
      onMutated()
    },
    onError: () =>
      toast.error(
        t({
          zh: "保存失败，请重试；题目内容已保留",
          en: "Save failed, please retry; your question text is kept",
        }),
      ),
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
          id: randomId(),
          text: d.text ?? "",
          seconds: d.suggested_seconds ?? 30,
        })),
      )
    },
    onError: (err: { body?: { detail?: string } }) =>
      toast.error(
        err.body?.detail ?? t({ zh: "生成失败", en: "Generation failed" }),
        {
          description: t({
            zh: "需配置方舟密钥后可用；也可手动录入",
            en: "Requires an Ark API key; you can also enter questions manually",
          }),
        },
      ),
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
      toast.success(t({ zh: "题目已更新", en: "Question updated" }))
      setEditingQ(null)
      onMutated()
    },
    onError: (err: { body?: { detail?: string } }) =>
      toast.error(
        err.body?.detail ?? t({ zh: "更新失败", en: "Update failed" }),
      ),
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
      showSuccessToast(t({ zh: "情景已更新", en: "Topic updated" }))
      onMutated()
    },
    onError: (err: { body?: { detail?: string } }) =>
      toast.error(
        err.body?.detail ?? t({ zh: "更新失败", en: "Update failed" }),
      ),
  })

  const deleteScenario = useMutation({
    mutationFn: () => AdminService.deleteScenario({ scenarioId: scenario.id }),
    onSuccess: () => {
      setConfirmDelete(false)
      onMutated()
    },
    onError: (err: { body?: { detail?: string } }) =>
      toast.error(
        err.body?.detail ?? t({ zh: "删除失败", en: "Delete failed" }),
      ),
  })

  return (
    <Card>
      <CardHeader className="flex-row items-end justify-between gap-3 space-y-0">
        <div className="flex-1 space-y-1">
          <div className="flex items-center gap-2">
            <Input
              aria-label={t({ zh: "情景主题", en: "Q&A topic" })}
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
              {t({ zh: "改名", en: "Rename" })}
            </Button>
            {scenario.is_active === false && (
              <Badge variant="secondary">
                {t({ zh: "已停用", en: "Disabled" })}
              </Badge>
            )}
          </div>
          <CardDescription>
            {scenario.topic === "School Life"
              ? t({ zh: "学校生活 · ", en: "School Life · " })
              : ""}
            {t({
              zh: `共 ${scenario.questions.length} 道题`,
              en: `${scenario.questions.length} questions`,
            })}
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
            {t({ zh: "启用", en: "Enabled" })}
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={t({
              zh: `删除情景 ${scenario.topic}`,
              en: `Delete topic ${scenario.topic}`,
            })}
            onClick={() => setConfirmDelete(true)}
          >
            <Trash2 className="text-destructive" />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <details>
          <summary className="cursor-pointer text-sm font-medium text-primary">
            {t({
              zh: "展开题目 · 手动添加 / AI 起草",
              en: "Questions · Add Manually / AI Draft",
            })}
          </summary>
          <div className="mt-4 space-y-3">
            <div className="space-y-1">
              <Badge variant="outline">
                {t({
                  zh: `共 ${scenario.questions.length} 道`,
                  en: `${scenario.questions.length} total`,
                })}
              </Badge>
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
                      {t({
                        zh: `建议作答 ${q.suggested_seconds} 秒`,
                        en: `Suggested ${q.suggested_seconds}s`,
                      })}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={t({
                        zh: `编辑题目 ${index + 1}`,
                        en: `Edit question ${index + 1}`,
                      })}
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
                      aria-label={t({ zh: "删除题目", en: "Delete question" })}
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
                <Label>{t({ zh: "题目", en: "Question" })}</Label>
                <Input
                  value={question.text}
                  onChange={(e) =>
                    setQuestion({ ...question, text: e.target.value })
                  }
                />
              </div>
              <div className="w-24 space-y-1">
                <Label>{t({ zh: "秒数", en: "Seconds" })}</Label>
                <NumberInput
                  value={question.seconds}
                  onValueChange={(seconds) =>
                    setQuestion({ ...question, seconds })
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
                {t({ zh: "添加", en: "Add" })}
              </Button>
            </div>

            {/* AI 起草（不入库，采纳后才保存） */}
            <div className="space-y-2 border-t pt-3">
              <div className="flex flex-wrap items-end gap-2">
                <div className="w-24 space-y-1">
                  <Label>{t({ zh: "数量", en: "Count" })}</Label>
                  <NumberInput
                    min={1}
                    max={10}
                    value={gen.count}
                    onValueChange={(count) => setGen({ ...gen, count })}
                  />
                </div>
                <div className="min-w-48 flex-1 space-y-1">
                  <Label>
                    {t({ zh: "要求（可选）", en: "Requirements (optional)" })}
                  </Label>
                  <Input
                    value={gen.hint}
                    onChange={(e) => setGen({ ...gen, hint: e.target.value })}
                    placeholder={t({
                      zh: "如：贴近校园生活",
                      en: "e.g. close to campus life",
                    })}
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
                  {t({ zh: "AI 起草", en: "AI Draft" })}
                </Button>
              </div>

              {drafts.length > 0 && (
                <div className="space-y-2 rounded-md border border-dashed p-2">
                  <p className="text-xs text-muted-foreground">
                    {t({
                      zh: "AI 草稿（可编辑后采纳；不会自动入库）",
                      en: "AI drafts (edit then adopt; not saved automatically)",
                    })}
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
                      <NumberInput
                        className="w-16"
                        value={d.seconds}
                        onValueChange={(seconds) => {
                          const next = [...drafts]
                          next[i] = { ...d, seconds }
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
                        {t({ zh: "采纳", en: "Adopt" })}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          setDrafts(drafts.filter((_, j) => j !== i))
                        }
                      >
                        {t({ zh: "丢弃", en: "Discard" })}
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
            <DialogTitle>
              {t({ zh: "编辑题目", en: "Edit Question" })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: "修改即时生效；学生下一轮抽题使用新内容。",
                en: "Changes take effect immediately; students see the new content next round.",
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="scn-q-text">
                {t({ zh: "英文题目", en: "Question" })}
              </Label>
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
              <Label htmlFor="scn-q-translation">
                {t({ zh: "中文提示（可选）", en: "Chinese Hint (optional)" })}
              </Label>
              <Input
                id="scn-q-translation"
                value={editForm.translation}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, translation: e.target.value }))
                }
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="scn-q-seconds">
                {t({
                  zh: "建议秒数（10–60）",
                  en: "Suggested Seconds (10–60)",
                })}
              </Label>
              <NumberInput
                id="scn-q-seconds"
                min={10}
                max={60}
                value={editForm.seconds}
                onValueChange={(seconds) =>
                  setEditForm((f) => ({ ...f, seconds }))
                }
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingQ(null)}>
              {t({ zh: "取消", en: "Cancel" })}
            </Button>
            <LoadingButton
              disabled={!editValid}
              loading={updateQuestion.isPending}
              onClick={() => updateQuestion.mutate()}
            >
              {t({ zh: "保存", en: "Save" })}
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={confirmDelete}
        title={t({
          zh: `删除情景「${scenario.topic}」？`,
          en: `Delete topic "${scenario.topic}"?`,
        })}
        description={t({
          zh: "该主题下的全部题目与录音都会一起删除，学生端不再出现这个主题。此操作不可撤销。",
          en: "All questions and recordings under this topic will be deleted, and the topic disappears for students. This cannot be undone.",
        })}
        confirmText={t({ zh: "删除情景", en: "Delete Topic" })}
        onOpenChange={setConfirmDelete}
        onConfirm={async () => {
          await deleteScenario.mutateAsync()
        }}
      />

      <ConfirmDialog
        open={confirmDeleteQ !== null}
        title={t({ zh: "删除这道题？", en: "Delete this question?" })}
        description={t({
          zh: "删除后学生端不再出现这道题，已有作答记录保留。此操作不可撤销。",
          en: "This question disappears for students; existing answers are kept. This cannot be undone.",
        })}
        confirmText={t({ zh: "删除", en: "Delete" })}
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
