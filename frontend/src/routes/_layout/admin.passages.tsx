import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, redirect } from "@tanstack/react-router"
import { Loader2, Plus, Trash2 } from "lucide-react"
import { useState } from "react"
import type { PassageWithSentences } from "@/client"
import { AdminService, UsersService } from "@/client"
import AudioSetter from "@/components/Practice/AudioSetter"
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
import { Textarea } from "@/components/ui/textarea"
import { APP_NAME } from "@/config"
import useCustomToast from "@/hooks/useCustomToast"

export const Route = createFileRoute("/_layout/admin/passages")({
  component: PassagesAdmin,
  beforeLoad: async () => {
    const user = await UsersService.readUserMe()
    if (!user.is_superuser) {
      throw redirect({ to: "/" })
    }
  },
  head: () => ({ meta: [{ title: `篇目管理 - ${APP_NAME}` }] }),
})

function PassagesAdmin() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const passagesQuery = useQuery({
    queryKey: ["admin", "passages"],
    queryFn: () => AdminService.listPassages(),
  })

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["admin", "passages"] })

  const createMutation = useMutation({
    mutationFn: (body: {
      slug: string
      title: string
      topic: string
      cefr_band: string
      text: string
      suggested_seconds?: number
    }) => AdminService.createPassage({ requestBody: body }),
    onSuccess: () => {
      showSuccessToast("篇目已创建")
      invalidate()
    },
    onError: (err: { body?: { detail?: string } }) =>
      showErrorToast(err.body?.detail ?? "创建失败"),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => AdminService.deletePassage({ passageId: id }),
    onSuccess: () => {
      showSuccessToast("已删除")
      invalidate()
    },
  })

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">篇目管理</h1>
        <p className="text-muted-foreground">
          练习篇目与听后复述句。EIP 文本由学校书面提供后录入，不进代码仓库。
        </p>
      </div>

      <NewPassageForm onSubmit={(body) => createMutation.mutate(body)} />

      {passagesQuery.isPending ? (
        <Loader2 className="size-5 animate-spin" />
      ) : (
        (passagesQuery.data ?? []).map((passage) => (
          <PassageCard
            key={passage.id}
            passage={passage}
            expanded={expandedId === passage.id}
            onToggle={() =>
              setExpandedId(expandedId === passage.id ? null : passage.id)
            }
            onDelete={() => deleteMutation.mutate(passage.id)}
            onMutated={invalidate}
          />
        ))
      )}
    </div>
  )
}

function NewPassageForm({
  onSubmit,
}: {
  onSubmit: (body: {
    slug: string
    title: string
    topic: string
    cefr_band: string
    text: string
    suggested_seconds?: number
  }) => void
}) {
  const [form, setForm] = useState({
    slug: "",
    title: "",
    topic: "",
    cefr_band: "B1",
    text: "",
    suggested_seconds: 45,
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">新建篇目</CardTitle>
        <CardDescription>slug 用于唯一标识（英文短横线）</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="slug">Slug</Label>
          <Input
            id="slug"
            value={form.slug}
            onChange={(e) => setForm({ ...form, slug: e.target.value })}
            placeholder="eip-unit1-pets"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="title">标题</Label>
          <Input
            id="title"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="topic">主题（与情景主题一致才会配对）</Label>
          <Input
            id="topic"
            value={form.topic}
            onChange={(e) => setForm({ ...form, topic: e.target.value })}
            placeholder="Pets"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label htmlFor="band">CEFR 档</Label>
            <Input
              id="band"
              value={form.cefr_band}
              onChange={(e) => setForm({ ...form, cefr_band: e.target.value })}
              placeholder="A2/B1/B2"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="seconds">建议秒数</Label>
            <Input
              id="seconds"
              type="number"
              value={form.suggested_seconds}
              onChange={(e) =>
                setForm({ ...form, suggested_seconds: Number(e.target.value) })
              }
            />
          </div>
        </div>
        <div className="space-y-1 md:col-span-2">
          <Label htmlFor="text">正文（朗读参考文本）</Label>
          <Textarea
            id="text"
            rows={4}
            value={form.text}
            onChange={(e) => setForm({ ...form, text: e.target.value })}
          />
        </div>
        <div className="md:col-span-2">
          <Button
            onClick={() => onSubmit(form)}
            disabled={!form.slug || !form.title || !form.text}
          >
            <Plus />
            创建
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function PassageCard({
  passage,
  expanded,
  onToggle,
  onDelete,
  onMutated,
}: {
  passage: PassageWithSentences
  expanded: boolean
  onToggle: () => void
  onDelete: () => void
  onMutated: () => void
}) {
  const { showSuccessToast } = useCustomToast()
  const [sentence, setSentence] = useState({ text: "", suggested_seconds: 8 })

  const addSentence = useMutation({
    mutationFn: () =>
      AdminService.createSentence({
        passageId: passage.id,
        requestBody: {
          passage_id: passage.id,
          order_index: (passage.sentences ?? []).length,
          text: sentence.text,
          suggested_seconds: sentence.suggested_seconds,
        },
      }),
    onSuccess: () => {
      showSuccessToast("复述句已添加")
      setSentence({ text: "", suggested_seconds: 8 })
      onMutated()
    },
  })

  const deleteSentence = useMutation({
    mutationFn: (id: string) => AdminService.deleteSentence({ sentenceId: id }),
    onSuccess: () => onMutated(),
  })

  return (
    <Card>
      <CardHeader
        className="cursor-pointer select-none flex-row items-center justify-between space-y-0"
        onClick={onToggle}
      >
        <div>
          <CardTitle className="text-base">
            {passage.title}{" "}
            <span className="font-normal text-muted-foreground">
              · {passage.topic} · {passage.cefr_band} ·{" "}
              {(passage.sentences ?? []).length} 句复述
            </span>
          </CardTitle>
          <CardDescription className="mt-1 font-mono">
            {passage.slug}
          </CardDescription>
        </div>
        <div className="flex items-center gap-1">
          <AudioSetter
            hasAudio={Boolean(passage.audio_url)}
            text={passage.text ?? ""}
            stopPropagation
            onSet={async (audio_url) => {
              await AdminService.updatePassage({
                passageId: passage.id,
                requestBody: {
                  slug: passage.slug ?? "",
                  title: passage.title ?? "",
                  topic: passage.topic ?? "",
                  cefr_band: passage.cefr_band ?? "B1",
                  text: passage.text ?? "",
                  suggested_seconds: passage.suggested_seconds ?? 45,
                  ...(audio_url !== null ? { audio_url } : {}),
                },
              })
              onMutated()
            }}
          />
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={(e) => {
              e.stopPropagation()
              onDelete()
            }}
          >
            <Trash2 className="text-destructive" />
          </Button>
        </div>
      </CardHeader>
      {expanded && (
        <CardContent className="space-y-4">
          <p className="whitespace-pre-wrap rounded-md bg-muted p-3 text-sm">
            {passage.text}
          </p>
          <div className="space-y-2">
            {(passage.sentences ?? []).map((s, i) => (
              <div
                key={s.id}
                className="flex items-center justify-between gap-3 rounded-md border px-3 py-2"
              >
                <span className="text-sm">
                  {i + 1}. {s.text}
                  <span className="ml-2 text-xs text-muted-foreground">
                    {s.suggested_seconds}s
                  </span>
                </span>
                <div className="flex items-center gap-1">
                  <AudioSetter
                    hasAudio={Boolean(s.audio_url)}
                    text={s.text ?? ""}
                    onSet={async (audio_url) => {
                      await AdminService.updateSentence({
                        sentenceId: s.id ?? "",
                        requestBody: {
                          passage_id: passage.id,
                          order_index: s.order_index ?? 0,
                          text: s.text ?? "",
                          suggested_seconds: s.suggested_seconds ?? 8,
                          ...(audio_url !== null ? { audio_url } : {}),
                        },
                      })
                      onMutated()
                    }}
                  />
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => s.id && deleteSentence.mutate(s.id)}
                  >
                    <Trash2 className="size-3.5 text-destructive" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-64 flex-1 space-y-1">
              <Label>添加复述句（由短到长）</Label>
              <Input
                value={sentence.text}
                onChange={(e) =>
                  setSentence({ ...sentence, text: e.target.value })
                }
              />
            </div>
            <div className="w-24 space-y-1">
              <Label>秒数</Label>
              <Input
                type="number"
                value={sentence.suggested_seconds}
                onChange={(e) =>
                  setSentence({
                    ...sentence,
                    suggested_seconds: Number(e.target.value),
                  })
                }
              />
            </div>
            <Button
              onClick={() => addSentence.mutate()}
              disabled={!sentence.text || addSentence.isPending}
            >
              <Plus />
              添加
            </Button>
          </div>
        </CardContent>
      )}
    </Card>
  )
}
