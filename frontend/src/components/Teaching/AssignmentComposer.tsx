import { useMutation, useQueryClient } from "@tanstack/react-query"
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
  type AssignmentInfo,
  ClassesService,
  type PassageWithSentences,
  type ScenarioOut,
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
import { useLessonContent } from "@/hooks/useLessonContent"
import { inspectLesson, type LessonTypes } from "@/lib/lesson-readiness"

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
    description: "按学生档位，一问一答",
    icon: MessagesSquare,
  },
] as const

export function AssignmentComposer({
  code,
  assignment,
}: {
  code: string
  assignment?: AssignmentInfo | null
}) {
  const { units, passages, scenarios } = useLessonContent(code)
  if (units.isError || passages.isError || scenarios.isError)
    return (
      <div className="rounded-2xl border p-6">
        <p>练习内容加载失败。</p>
        <Button
          className="mt-3"
          variant="outline"
          onClick={() => {
            void units.refetch()
            void passages.refetch()
            void scenarios.refetch()
          }}
        >
          重新加载
        </Button>
      </div>
    )
  if (units.isPending || passages.isPending || scenarios.isPending)
    return (
      <p className="rounded-2xl border p-6 text-muted-foreground">
        正在加载可用练习…
      </p>
    )
  const flags = units.data[0]
  const initialTypes = {
    reading: flags?.assign_reading === true,
    repeat: flags?.assign_repeat !== false,
    qa: flags?.assign_qa !== false,
  }
  return (
    <ComposerForm
      key={`${assignment?.unit_id ?? "none"}-${JSON.stringify(initialTypes)}`}
      code={code}
      assignment={assignment}
      units={units.data}
      passages={passages.data}
      scenarios={scenarios.data}
      initialTypes={initialTypes}
    />
  )
}

function ComposerForm({
  code,
  assignment,
  units,
  passages,
  scenarios,
  initialTypes,
}: {
  code: string
  assignment?: AssignmentInfo | null
  units: AssignmentInfo[]
  passages: PassageWithSentences[]
  scenarios: ScenarioOut[]
  initialTypes: LessonTypes
}) {
  const [unitId, setUnitId] = useState(assignment?.unit_id ?? "")
  const [types, setTypes] = useState(initialTypes)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [clearOpen, setClearOpen] = useState(false)
  const queryClient = useQueryClient()
  const { materials, scenario, problems } = inspectLesson(
    unitId,
    types,
    passages,
    scenarios,
  )
  const selectedUnit = units.find((unit) => unit.unit_id === unitId)
  const changed =
    unitId !== assignment?.unit_id ||
    JSON.stringify(types) !== JSON.stringify(initialTypes)
  const publish = useMutation({
    mutationFn: (clear: boolean) =>
      ClassesService.setAssignment({
        code,
        requestBody: clear
          ? { unit_id: null }
          : {
              unit_id: unitId,
              assign_reading: types.reading,
              assign_repeat: types.repeat,
              assign_qa: types.qa,
            },
      }),
    onSuccess: async (_, clear) => {
      setPreviewOpen(false)
      setClearOpen(false)
      toast.success(clear ? "已恢复学生自主练习" : "本次课堂练习已发布")
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["teacher", "board", code] }),
        queryClient.invalidateQueries({ queryKey: ["teacher", "units", code] }),
      ])
    },
    onError: () => toast.error("发布失败，选择已保留，请重试"),
  })
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-secondary/40 px-5 py-4">
        <div>
          <p className="text-xs text-muted-foreground">学生当前练习</p>
          <p className="mt-1 font-semibold">
            {assignment ? assignment.title : "自主练习 · 尚未安排统一内容"}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {assignment
              ? questionTypes
                  .filter((type) => initialTypes[type.key])
                  .map((type) => type.title)
                  .join(" · ")
              : "发布后，全班按本次设置练习。"}
          </p>
        </div>
        {assignment && (
          <Button variant="ghost" size="sm" onClick={() => setClearOpen(true)}>
            恢复自主练习
          </Button>
        )}
      </div>
      <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
        <div className="space-y-6 rounded-2xl border bg-card p-6">
          <section>
            <h2 className="font-semibold">1. 选择练习内容</h2>
            <p className="mb-4 mt-2 text-sm text-muted-foreground">
              使用题目库里整理好的分组，本次为全班统一安排。
            </p>
            <select
              aria-label="选择练习内容"
              className="h-11 w-full rounded-lg border bg-background px-3 text-sm"
              value={unitId}
              onChange={(event) => setUnitId(event.target.value)}
            >
              <option value="">请选择练习内容</option>
              {units.map((unit) => (
                <option key={unit.unit_id} value={unit.unit_id}>
                  {unit.title}
                  {unit.passage_count ? "" : "（尚无材料）"}
                </option>
              ))}
            </select>
            <Button variant="link" className="mt-2 px-0" asChild>
              <Link to="/create" search={{ kind: "reading", classroom: code }}>
                准备新内容或整理分组 →
              </Link>
            </Button>
          </section>
          <section>
            <h2 className="mb-4 font-semibold">2. 选择本次题型</h2>
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
        </div>
        <aside className="self-start rounded-2xl border bg-card p-6">
          <h2 className="font-semibold">3. 检查并发布</h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            选择内容和题型后，先查看学生练习内容，再确认发布。
          </p>
          <div className="my-5 border-y py-4 text-sm">
            <p className="font-medium">
              {selectedUnit?.title ?? "尚未选择内容"}
            </p>
            <p className="mt-2 text-muted-foreground">
              {questionTypes
                .filter((type) => types[type.key])
                .map((type) => type.title)
                .join(" / ") || "尚未选择题型"}
            </p>
            {types.reading && materials.length > 0 && (
              <p className="mt-2 text-muted-foreground">
                朗读材料 {materials.length} 篇
                {materials.length > 1 ? "（长文拆段，分别朗读）" : ""}
              </p>
            )}
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
          {problems.length > 0 && (
            <Button
              variant="link"
              className="mt-2 h-auto whitespace-normal px-0"
              asChild
            >
              <Link
                to="/create"
                search={{
                  kind: types.qa ? "qa" : types.repeat ? "repeat" : "reading",
                  classroom: code,
                }}
              >
                到题目库补充内容 →
              </Link>
            </Button>
          )}
        </aside>
      </div>
      <Dialog
        open={previewOpen}
        onOpenChange={(open) => !publish.isPending && setPreviewOpen(open)}
      >
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>练习预览 · {selectedUnit?.title}</DialogTitle>
            <DialogDescription>
              发布到课堂 {code}
              。问答按学生档位抽取，以下展示可用题目；已有作答的处理沿用当前课堂规则。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-5">
            {types.reading &&
              materials.map((material, index) => (
                <section key={material.id} className="rounded-xl border p-4">
                  <h3 className="font-semibold">
                    文章朗读{" "}
                    {materials.length > 1
                      ? `${index + 1}/${materials.length}`
                      : ""}{" "}
                    · {material.title} · 建议 {material.suggested_seconds} 秒
                  </h3>
                  <p className="mt-3 whitespace-pre-wrap text-sm leading-7">
                    {material.text}
                  </p>
                </section>
              ))}
            {types.repeat &&
              materials
                .filter((material) => material.sentences?.length)
                .map((material) => (
                  <section
                    key={`repeat-${material.id}`}
                    className="rounded-xl border p-4"
                  >
                    <h3 className="font-semibold">
                      听句复述 · {material.title}
                    </h3>
                    <ol className="mt-3 space-y-3">
                      {material.sentences?.map((sentence, index) => (
                        <li
                          key={sentence.id ?? index}
                          className="text-sm leading-6"
                        >
                          <p>
                            {index + 1}. {sentence.text}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            建议 {sentence.suggested_seconds} 秒 · 可听{" "}
                            {(sentence.replay_limit ?? 3) === 0
                              ? "不限次数"
                              : `${sentence.replay_limit ?? 3} 次`}{" "}
                            ·{" "}
                            {sentence.audio_url
                              ? "已配标准音"
                              : "使用浏览器语音"}
                          </p>
                        </li>
                      ))}
                    </ol>
                  </section>
                ))}
            {scenario && types.qa && (
              <section className="rounded-xl border p-4">
                <h3 className="font-semibold">模拟问答 · {scenario.topic}</h3>
                {["A2", "B1", "B2"].map((band) => (
                  <div key={band} className="mt-3">
                    <p className="text-xs font-semibold text-primary">{band}</p>
                    {scenario.questions
                      .filter((question) => question.band === band)
                      .map((question) => (
                        <p key={question.id} className="mt-2 text-sm leading-6">
                          {question.text}{" "}
                          <span className="text-muted-foreground">
                            · {question.suggested_seconds} 秒
                          </span>
                        </p>
                      ))}
                  </div>
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
