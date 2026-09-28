import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Loader2, Plus, Sparkles, Trash2 } from "lucide-react"
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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
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
  audio_url?: string | null
  suggested_seconds?: number
}

interface ScenarioShape {
  id: string
  topic: string
  is_active?: boolean
  questions: QuestionShape[]
}

const BANDS = ["A2", "B1", "B2"] as const
const BAND_LABELS = { A2: "KET · A2", B1: "PET · B1", B2: "B2 · 进阶" }

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
    band: "B1",
    text: "",
    seconds: 30,
  })
  const [topicDraft, setTopicDraft] = useState(scenario.topic)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const [gen, setGen] = useState({ band: "B1", count: 3, hint: "" })
  const [drafts, setDrafts] = useState<
    Array<{ id: string; text: string; band: string; seconds: number }>
  >([])

  const addQuestion = useMutation({
    mutationFn: (body: { band: string; text: string; seconds: number }) =>
      AdminService.createQuestion({
        scenarioId: scenario.id,
        requestBody: {
          scenario_id: scenario.id,
          band: body.band,
          text: body.text,
          suggested_seconds: body.seconds,
          order_index: scenario.questions.length,
        },
      }),
    onSuccess: () => {
      showSuccessToast("题目已添加")
      setQuestion({ band: question.band, text: "", seconds: 30 })
      onMutated()
    },
    onError: () => toast.error("保存失败，请重试；题目内容已保留"),
  })

  const generateMutation = useMutation({
    mutationFn: () =>
      AdminService.generateQuestions({
        scenarioId: scenario.id,
        requestBody: {
          band: gen.band,
          count: gen.count,
          ...(gen.hint ? { hint: gen.hint } : {}),
        },
      }),
    onSuccess: (data) => {
      setDrafts(
        (data ?? []).map((d) => ({
          id: crypto.randomUUID(),
          text: d.text ?? "",
          band: gen.band,
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
      { band: d.band, text: d.text, seconds: d.seconds },
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
            {BANDS.map((band) => {
              const questions = scenario.questions.filter(
                (q) => q.band === band,
              )
              if (questions.length === 0) return null
              return (
                <div key={band} className="space-y-1">
                  <Badge variant="outline">
                    {BAND_LABELS[band]} · {questions.length} 道
                  </Badge>
                  {questions.map((q, index) => (
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
                          onClick={() => deleteQuestion.mutate(q.id)}
                        >
                          <Trash2 className="size-3.5 text-destructive" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )
            })}
            <div className="flex flex-wrap items-end gap-2 border-t pt-3">
              <div className="w-32 space-y-1">
                <Label>档位</Label>
                <Select
                  value={question.band}
                  onValueChange={(next) =>
                    setQuestion({ ...question, band: next })
                  }
                >
                  <SelectTrigger className="h-9 w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {BANDS.map((band) => (
                      <SelectItem key={band} value={band}>
                        {BAND_LABELS[band]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
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
                    band: question.band,
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
                <div className="w-32 space-y-1">
                  <Label>AI 档位</Label>
                  <Select
                    value={gen.band}
                    onValueChange={(next) => setGen({ ...gen, band: next })}
                  >
                    <SelectTrigger className="h-9 w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {BANDS.map((band) => (
                        <SelectItem key={band} value={band}>
                          {BAND_LABELS[band]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
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
    </Card>
  )
}
