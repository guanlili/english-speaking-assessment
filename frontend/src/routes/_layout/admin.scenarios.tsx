import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, redirect } from "@tanstack/react-router"
import { Loader2, Plus, Sparkles, Trash2 } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import { AdminService, UsersService } from "@/client"
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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { APP_NAME } from "@/config"
import useCustomToast from "@/hooks/useCustomToast"

export const Route = createFileRoute("/_layout/admin/scenarios")({
  component: ScenariosAdmin,
  beforeLoad: async () => {
    const user = await UsersService.readUserMe()
    if (!user.is_superuser) {
      throw redirect({ to: "/" })
    }
  },
  head: () => ({ meta: [{ title: `情景与问法 - ${APP_NAME}` }] }),
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

function ScenariosAdmin() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [newTopic, setNewTopic] = useState("")

  const scenariosQuery = useQuery({
    queryKey: ["admin", "scenarios"],
    queryFn: () => AdminService.listScenarios(),
  })

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["admin", "scenarios"] })

  const createScenario = useMutation({
    mutationFn: () =>
      AdminService.createScenario({ requestBody: { topic: newTopic } }),
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
      <div>
        <h1 className="text-2xl font-bold tracking-tight">情景与问法</h1>
        <p className="text-muted-foreground">
          每个主题一组问法，分属低/中/高档（A2/B1/B2）。主题需与篇目的主题一致才会配对。
        </p>
      </div>

      <Card>
        <CardContent className="flex items-end gap-3 py-4">
          <div className="flex-1 space-y-1">
            <Label>新建情景主题</Label>
            <Input
              value={newTopic}
              onChange={(e) => setNewTopic(e.target.value)}
              placeholder="如：School Life"
            />
          </div>
          <Button
            onClick={() => createScenario.mutate()}
            disabled={!newTopic || createScenario.isPending}
          >
            <Plus />
            创建
          </Button>
        </CardContent>
      </Card>

      {scenariosQuery.isPending ? (
        <Loader2 className="size-5 animate-spin" />
      ) : (
        (scenariosQuery.data ?? []).map((scenario) => (
          <ScenarioCard
            key={scenario.id}
            scenario={scenario as ScenarioShape}
            onMutated={invalidate}
          />
        ))
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

  const [gen, setGen] = useState({ band: "B1", count: 3, hint: "" })
  const [drafts, setDrafts] = useState<
    Array<{ text: string; band: string; seconds: number }>
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
      showSuccessToast("问法已添加")
      setQuestion({ band: question.band, text: "", seconds: 30 })
      onMutated()
    },
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
    addQuestion.mutate({ band: d.band, text: d.text, seconds: d.seconds })
    setDrafts(drafts.filter((_, i) => i !== index))
  }

  const deleteQuestion = useMutation({
    mutationFn: (id: string) => AdminService.deleteQuestion({ questionId: id }),
    onSuccess: () => onMutated(),
  })

  const deleteScenario = useMutation({
    mutationFn: () => AdminService.deleteScenario({ scenarioId: scenario.id }),
    onSuccess: () => onMutated(),
  })

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="text-base">{scenario.topic}</CardTitle>
          <CardDescription>{scenario.questions.length} 个问法</CardDescription>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => deleteScenario.mutate()}
        >
          <Trash2 className="text-destructive" />
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {BANDS.map((band) => {
          const questions = scenario.questions.filter((q) => q.band === band)
          if (questions.length === 0) return null
          return (
            <div key={band} className="space-y-1">
              <Badge variant="outline">{band}</Badge>
              {questions.map((q) => (
                <div
                  key={q.id}
                  className="flex items-center justify-between gap-3 rounded-md border px-3 py-2"
                >
                  <span className="text-sm">{q.text}</span>
                  <div className="flex items-center gap-1">
                    <AudioSetter
                      hasAudio={Boolean(q.audio_url)}
                      text={q.text ?? ""}
                      onSet={async (audio_url) => {
                        await AdminService.updateQuestion({
                          questionId: q.id,
                          requestBody: audio_url !== null ? { audio_url } : {},
                        })
                        onMutated()
                      }}
                    />
                    <Button
                      variant="ghost"
                      size="icon-sm"
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
          <div className="w-24 space-y-1">
            <Label>档位</Label>
            <Input
              value={question.band}
              onChange={(e) =>
                setQuestion({ ...question, band: e.target.value })
              }
              placeholder="A2/B1/B2"
            />
          </div>
          <div className="min-w-56 flex-1 space-y-1">
            <Label>问法</Label>
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
                setQuestion({ ...question, seconds: Number(e.target.value) })
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
            <div className="w-24 space-y-1">
              <Label>AI 档位</Label>
              <Input
                value={gen.band}
                onChange={(e) => setGen({ ...gen, band: e.target.value })}
                placeholder="A2/B1/B2"
              />
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
                <div key={d.text} className="flex flex-wrap items-center gap-2">
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
                  <Button size="sm" onClick={() => adoptDraft(i)}>
                    采纳
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setDrafts(drafts.filter((_, j) => j !== i))}
                  >
                    丢弃
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
