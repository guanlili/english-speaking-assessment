import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  BookOpenText,
  Check,
  Ear,
  Eye,
  MessagesSquare,
  Send,
} from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import {
  AdminService,
  type AssignmentInfo,
  ClassesService,
  type PassageWithSentences,
  type ScenarioOut,
  type SentenceWithPassage,
} from "@/client"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  inspectSelection,
  type LessonSelection,
  type LessonTypes,
} from "@/lib/lesson-readiness"

const questionTypes = [
  {
    key: "reading",
    title: "文章朗读",
    description: "看文章或段落，录音提交",
    icon: BookOpenText,
  },
  {
    key: "repeat",
    title: "听句复述",
    description: "听标准音，按设定次数重听",
    icon: Ear,
  },
  {
    key: "qa",
    title: "模拟问答",
    description: "按主题出题，一问一答",
    icon: MessagesSquare,
  },
] as const

type AssignedItemRef = { [key: string]: string }

export function AssignmentComposer({
  code,
  assignment,
  assignedItems,
}: {
  code: string
  assignment?: AssignmentInfo | null
  assignedItems?: AssignedItemRef[] | null
}) {
  // 三种题型互相独立：各自的题库列表分别加载
  const passagesQuery = useQuery({
    queryKey: ["admin", "passages"],
    queryFn: () => AdminService.listPassages(),
  })
  const sentencesQuery = useQuery({
    queryKey: ["admin", "sentences"],
    queryFn: () => AdminService.listSentencesFlat(),
  })
  const scenariosQuery = useQuery({
    queryKey: ["admin", "scenarios"],
    queryFn: () => AdminService.listScenarios(),
  })

  if (passagesQuery.isError || sentencesQuery.isError || scenariosQuery.isError)
    return (
      <div className="rounded-2xl border p-6">
        <p>练习内容加载失败。</p>
        <Button
          className="mt-3"
          variant="outline"
          onClick={() => {
            void passagesQuery.refetch()
            void sentencesQuery.refetch()
            void scenariosQuery.refetch()
          }}
        >
          重新加载
        </Button>
      </div>
    )
  if (
    passagesQuery.isPending ||
    sentencesQuery.isPending ||
    scenariosQuery.isPending
  )
    return (
      <p className="rounded-2xl border p-6 text-muted-foreground">
        正在加载可用练习…
      </p>
    )

  const passages = passagesQuery.data
  const sentences = sentencesQuery.data
  const scenarios = scenariosQuery.data

  // 当前按题指派回显
  const currentItems = assignedItems ?? []
  const currentPassages = currentItems
    .filter((i) => i.type === "passage")
    .map((i) => i.id)
  const currentSentences = currentItems
    .filter((i) => i.type === "repeat")
    .map((i) => i.id)
  const currentQuestionIds = new Set(
    currentItems.filter((i) => i.type === "question").map((i) => i.id),
  )
  const currentScenario = scenarios.find((s) =>
    s.questions.some((q) => currentQuestionIds.has(q.id)),
  )

  const initialTypes: LessonTypes = {
    reading: currentPassages.length > 0,
    repeat: currentSentences.length > 0,
    qa: currentQuestionIds.size > 0,
  }
  const initialSelection: LessonSelection = {
    passages: currentPassages,
    sentences: currentSentences,
    scenarioId: currentScenario?.id ?? null,
  }

  return (
    <ComposerForm
      code={code}
      hasUnitAssignment={Boolean(assignment)}
      unitTitle={assignment?.title}
      hasItemAssignment={currentItems.length > 0}
      passages={passages}
      sentences={sentences}
      scenarios={scenarios}
      initialTypes={initialTypes}
      initialSelection={initialSelection}
    />
  )
}

function ComposerForm({
  code,
  hasUnitAssignment,
  unitTitle,
  hasItemAssignment,
  passages,
  sentences,
  scenarios,
  initialTypes,
  initialSelection,
}: {
  code: string
  hasUnitAssignment: boolean
  unitTitle?: string
  hasItemAssignment: boolean
  passages: PassageWithSentences[]
  sentences: SentenceWithPassage[]
  scenarios: ScenarioOut[]
  initialTypes: LessonTypes
  initialSelection: LessonSelection
}) {
  const [types, setTypes] = useState<LessonTypes>(initialTypes)
  const [selection, setSelection] = useState<LessonSelection>(initialSelection)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [clearOpen, setClearOpen] = useState(false)
  const queryClient = useQueryClient()

  const { scenario, problems } = inspectSelection(types, selection, {
    sentences,
    scenarios,
  })

  const selectedPassages = passages.filter((p) =>
    selection.passages.includes(p.id ?? ""),
  )
  const selectedSentences = sentences.filter((s) =>
    selection.sentences.includes(s.id ?? ""),
  )
  const scenarioQuestions = scenario?.questions ?? []

  const changed =
    JSON.stringify(types) !== JSON.stringify(initialTypes) ||
    JSON.stringify(selection) !== JSON.stringify(initialSelection)

  const publish = useMutation({
    mutationFn: (clear: boolean) =>
      ClassesService.setAssignment({
        code,
        requestBody: clear
          ? { items: [] }
          : {
              items: [
                ...selection.passages.map((id) => ({ type: "passage", id })),
                ...selection.sentences.map((id) => ({ type: "repeat", id })),
                ...(selection.scenarioId
                  ? (
                      scenarios.find((s) => s.id === selection.scenarioId)
                        ?.questions ?? []
                    ).map((q) => ({
                      type: "question",
                      id: q.id,
                    }))
                  : []),
              ],
            },
      }),
    onSuccess: async (_, clear) => {
      setPreviewOpen(false)
      setClearOpen(false)
      toast.success(clear ? "已恢复学生自主练习" : "本次课堂练习已发布")
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["teacher", "board", code] }),
        queryClient.invalidateQueries({ queryKey: ["admin", "sentences"] }),
      ])
    },
    onError: () => toast.error("发布失败，选择已保留，请重试"),
  })

  const toggleInList = (list: string[], id: string) =>
    list.includes(id) ? list.filter((x) => x !== id) : [...list, id]

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-secondary/40 px-5 py-4">
        <div>
          <p className="text-xs text-muted-foreground">学生当前练习</p>
          <p className="mt-1 font-semibold">
            {hasItemAssignment
              ? `按题指派 · ${initialSelection.passages.length} 篇朗读 · ${initialSelection.sentences.length} 句复述 · ${currentQuestionCount(scenarios, initialSelection)} 道问答`
              : unitTitle
                ? `单元指派 · ${unitTitle}（旧版，重新发布后转为按题指派）`
                : "自主练习 · 尚未安排统一内容"}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {hasItemAssignment || unitTitle
              ? "发布后，全班按本次设置练习。"
              : "发布后，全班按本次设置练习。"}
          </p>
        </div>
        {(hasItemAssignment || hasUnitAssignment) && (
          <Button variant="ghost" size="sm" onClick={() => setClearOpen(true)}>
            恢复自主练习
          </Button>
        )}
      </div>
      <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
        <div className="space-y-6 rounded-2xl border bg-card p-6">
          <section>
            <h2 className="font-semibold">1. 选择题型</h2>
            <p className="mb-4 mt-2 text-sm text-muted-foreground">
              三种题型互相独立：勾选后在下方为该题型挑选内容。
            </p>
            <div className="space-y-3">
              {questionTypes.map((type) => (
                <label
                  key={type.key}
                  htmlFor={`lesson-type-${type.key}`}
                  className={`flex cursor-pointer items-center gap-4 rounded-xl border p-4 ${types[type.key] ? "border-primary/50 bg-primary/5" : ""}`}
                >
                  <Checkbox
                    id={`lesson-type-${type.key}`}
                    checked={types[type.key]}
                    onCheckedChange={(checked) =>
                      setTypes((current) => ({
                        ...current,
                        [type.key]: checked === true,
                      }))
                    }
                  />
                  <type.icon className="size-5 shrink-0 text-primary" />
                  <span>
                    <span className="block text-sm font-medium">
                      {type.title}
                    </span>
                    <span className="mt-1 block text-xs text-muted-foreground">
                      {type.description}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          </section>
          {types.reading && (
            <section>
              <h2 className="font-semibold">2. 朗读篇目</h2>
              <p className="mb-3 mt-2 text-sm text-muted-foreground">
                可多选：长文拆成几篇时学生按顺序分别朗读。
              </p>
              <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
                {passages.length === 0 && (
                  <p className="text-sm text-muted-foreground">
                    还没有朗读篇目，去题目库创建。
                  </p>
                )}
                {passages.map((p) => (
                  <label
                    key={p.id}
                    htmlFor={`pick-passage-${p.id}`}
                    className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 ${selection.passages.includes(p.id ?? "") ? "border-primary/50 bg-primary/5" : ""}`}
                  >
                    <Checkbox
                      id={`pick-passage-${p.id}`}
                      checked={selection.passages.includes(p.id ?? "")}
                      onCheckedChange={() =>
                        setSelection((cur) => ({
                          ...cur,
                          passages: toggleInList(cur.passages, p.id ?? ""),
                        }))
                      }
                    />
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium">
                        {p.title}
                      </span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        {p.topic} · 建议 {p.suggested_seconds} 秒
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </section>
          )}
          {types.repeat && (
            <section>
              <h2 className="font-semibold">
                {types.reading ? "3" : "2"}. 复述句
              </h2>
              <p className="mb-3 mt-2 text-sm text-muted-foreground">
                从复述句题库多选，学生只能听语音复述。
              </p>
              <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
                {sentences.length === 0 && (
                  <p className="text-sm text-muted-foreground">
                    还没有复述句，去题目库创建。
                  </p>
                )}
                {sentences.map((s) => (
                  <label
                    key={s.id}
                    htmlFor={`pick-sentence-${s.id}`}
                    className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 ${selection.sentences.includes(s.id ?? "") ? "border-primary/50 bg-primary/5" : ""}`}
                  >
                    <Checkbox
                      id={`pick-sentence-${s.id}`}
                      checked={selection.sentences.includes(s.id ?? "")}
                      onCheckedChange={() =>
                        setSelection((cur) => ({
                          ...cur,
                          sentences: toggleInList(cur.sentences, s.id ?? ""),
                        }))
                      }
                    />
                    <span className="min-w-0">
                      <span className="block truncate text-sm">{s.text}</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        {s.suggested_seconds} 秒 · 可听{" "}
                        {(s.replay_limit ?? 3) === 0
                          ? "不限"
                          : `${s.replay_limit ?? 3} 次`}
                        {s.passage_title
                          ? ` · 挂篇目：${s.passage_title}`
                          : " · 独立题"}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </section>
          )}
          {types.qa && (
            <section>
              <h2 className="font-semibold">
                {types.reading && types.repeat
                  ? "4"
                  : types.reading || types.repeat
                    ? "3"
                    : "2"}
                . 问答主题
              </h2>
              <p className="mb-3 mt-2 text-sm text-muted-foreground">
                选一个主题，该主题下全部题目按序进入本次练习。
              </p>
              <Select
                value={selection.scenarioId ?? ""}
                onValueChange={(id) =>
                  setSelection((cur) => ({ ...cur, scenarioId: id || null }))
                }
              >
                <SelectTrigger aria-label="选择问答主题">
                  <SelectValue placeholder="选择问答主题" />
                </SelectTrigger>
                <SelectContent>
                  {scenarios
                    .filter((s) => s.is_active)
                    .map((s) => (
                      <SelectItem key={s.id} value={s.id}>
                        {s.topic}（{s.questions.length} 题）
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
              {scenario && (
                <div className="mt-3 space-y-1 rounded-lg border p-3 text-sm">
                  {scenario.questions.map((q) => (
                    <p key={q.id} className="truncate">
                      · {q.text}{" "}
                      <span className="text-xs text-muted-foreground">
                        {q.suggested_seconds} 秒
                      </span>
                    </p>
                  ))}
                </div>
              )}
            </section>
          )}
        </div>
        <aside className="self-start rounded-2xl border bg-card p-6">
          <h2 className="font-semibold">检查并发布</h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            选好内容和题型后，先预览学生将看到的内容，再确认发布。
          </p>
          <div className="my-5 space-y-1 border-y py-4 text-sm">
            <p className="font-medium">
              {types.reading ? `朗读 ${selection.passages.length} 篇` : null}
              {types.repeat ? `复述 ${selection.sentences.length} 句` : null}
              {types.qa ? `问答 ${scenarioQuestions.length} 道` : null}
              {!types.reading && !types.repeat && !types.qa && "尚未选择题型"}
            </p>
          </div>
          {problems.length ? (
            <ul className="space-y-3 text-sm leading-6 text-muted-foreground">
              {problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          ) : (
            <p className="flex items-center gap-2 text-sm text-primary">
              <Check className="size-4" />
              内容已齐备，可以预览
            </p>
          )}
          <Button
            className="mt-5 w-full"
            disabled={problems.length > 0 || publish.isPending}
            onClick={() => setPreviewOpen(true)}
          >
            <Eye className="size-4" />
            预览练习
          </Button>
          <p className="mt-3 text-xs leading-5 text-muted-foreground">
            当前选择尚未发布。只有确认发布后，才会更新学生练习。
          </p>
          <Button variant="link" className="mt-2 h-auto px-0" asChild>
            <Link to="/create" search={{ kind: "reading", classroom: code }}>
              到题目库补充内容 →
            </Link>
          </Button>
        </aside>
      </div>
      <Dialog
        open={previewOpen}
        onOpenChange={(open) => !publish.isPending && setPreviewOpen(open)}
      >
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>练习预览</DialogTitle>
            <DialogDescription>
              发布到课堂 {code}
              。学生按以下顺序作答；已有作答的处理沿用当前课堂规则。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-5">
            {selectedPassages.map((p, index) => (
              <section key={p.id} className="rounded-xl border p-4">
                <h3 className="font-semibold">
                  文章朗读{" "}
                  {selectedPassages.length > 1
                    ? `${index + 1}/${selectedPassages.length}`
                    : ""}{" "}
                  · {p.title} · 建议 {p.suggested_seconds} 秒
                </h3>
                <p className="mt-3 whitespace-pre-wrap text-sm leading-7">
                  {p.text}
                </p>
              </section>
            ))}
            {selectedSentences.length > 0 && (
              <section className="rounded-xl border p-4">
                <h3 className="font-semibold">听句复述</h3>
                <ol className="mt-3 space-y-3">
                  {selectedSentences.map((s, index) => (
                    <li key={s.id} className="text-sm leading-6">
                      <p>
                        {index + 1}. {s.text}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        建议 {s.suggested_seconds} 秒 · 可听{" "}
                        {(s.replay_limit ?? 3) === 0
                          ? "不限次数"
                          : `${s.replay_limit ?? 3} 次`}{" "}
                        · {s.audio_url ? "已配标准音" : "使用浏览器语音"}
                      </p>
                    </li>
                  ))}
                </ol>
              </section>
            )}
            {scenarioQuestions.length > 0 && (
              <section className="rounded-xl border p-4">
                <h3 className="font-semibold">模拟问答 · {scenario?.topic}</h3>
                {scenarioQuestions.map((q) => (
                  <p key={q.id} className="mt-3 text-sm leading-6">
                    {q.text}{" "}
                    <span className="text-muted-foreground">
                      · {q.suggested_seconds} 秒
                    </span>
                  </p>
                ))}
              </section>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              disabled={publish.isPending}
              onClick={() => setPreviewOpen(false)}
            >
              返回修改
            </Button>
            <LoadingButton
              loading={publish.isPending}
              disabled={problems.length > 0 || !changed}
              onClick={() => publish.mutate(false)}
            >
              <Send className="size-4" />
              {changed ? "确认发布到课堂" : "与当前发布一致"}
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={clearOpen}
        onOpenChange={(open) => !publish.isPending && setClearOpen(open)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>恢复学生自主练习？</DialogTitle>
            <DialogDescription>
              移除课堂统一指派后，学生将按各自学习进度练习，已提交记录保留。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              disabled={publish.isPending}
              onClick={() => setClearOpen(false)}
            >
              取消
            </Button>
            <LoadingButton
              loading={publish.isPending}
              onClick={() => publish.mutate(true)}
            >
              确认恢复
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function currentQuestionCount(
  scenarios: ScenarioOut[],
  selection: LessonSelection,
): number {
  return (
    scenarios.find((s) => s.id === selection.scenarioId)?.questions.length ?? 0
  )
}
