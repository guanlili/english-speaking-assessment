import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  BookOpenText,
  Check,
  ChevronDown,
  ChevronUp,
  Ear,
  Eye,
  MessagesSquare,
  Send,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import {
  AdminService,
  type AssignmentInfo,
  type AssignmentItemIn,
  ClassesService,
  type ClassroomExercisePublic,
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
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import { NumberInput } from "@/components/ui/number-input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  assignmentItemKey,
  defaultAssignmentOrder,
  moveAssignmentItem,
  reconcileAssignmentOrder,
} from "@/lib/assignment-order"
import { useI18n } from "@/lib/i18n"
import {
  inspectSelection,
  type LessonSelection,
  type LessonTypes,
} from "@/lib/lesson-readiness"
import {
  EXAM_KIND_LABELS,
  EXAM_LEVEL_LABELS,
  ITEM_TYPE_LABELS,
  TERMS,
} from "@/lib/terms"

const questionTypes = [
  {
    key: "reading",
    title: TERMS.typeReading,
    description: {
      zh: "看文章或段落，录音提交",
      en: "Read a text or paragraph, record and submit",
    },
    icon: BookOpenText,
  },
  {
    key: "repeat",
    title: TERMS.typeRepeat,
    description: {
      zh: "听标准音，按设定次数重听",
      en: "Listen to the model audio, replay as set",
    },
    icon: Ear,
  },
  {
    key: "qa",
    title: { zh: "模拟问答", en: "Scenario Q&A" },
    description: {
      zh: "按主题出题，一问一答",
      en: "Questions by topic, ask and answer",
    },
    icon: MessagesSquare,
  },
] as const

type AssignedItemRef = { [key: string]: string }

export function AssignmentComposer({
  code,
  assignment,
  assignedItems,
  currentExercise,
}: {
  code: string
  assignment?: AssignmentInfo | null
  assignedItems?: AssignedItemRef[] | null
  currentExercise?: ClassroomExercisePublic | null
}) {
  const { t } = useI18n()
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
  const exercisesQuery = useQuery({
    queryKey: ["teacher", "exercises", code],
    queryFn: () => ClassesService.listClassroomExercises({ code }),
  })

  if (passagesQuery.isError || sentencesQuery.isError || scenariosQuery.isError)
    return (
      <div className="rounded-2xl border p-6">
        <p>
          {t({
            zh: "练习内容加载失败。",
            en: "Failed to load practice content.",
          })}
        </p>
        <Button
          className="mt-3"
          variant="outline"
          onClick={() => {
            void passagesQuery.refetch()
            void sentencesQuery.refetch()
            void scenariosQuery.refetch()
          }}
        >
          {t({ zh: "重新加载", en: "Reload" })}
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
        {t({
          zh: "正在加载可用练习…",
          en: "Loading available practice…",
        })}
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
      initialItems={currentItems as AssignmentItemIn[]}
      initialTitle={
        currentExercise?.title ?? t({ zh: "课堂练习", en: "Class Practice" })
      }
      exerciseHistory={exercisesQuery.data ?? []}
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
  initialItems,
  initialTitle,
  exerciseHistory,
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
  initialItems: AssignmentItemIn[]
  initialTitle: string
  exerciseHistory: ClassroomExercisePublic[]
}) {
  const { t } = useI18n()
  const [types, setTypes] = useState<LessonTypes>(initialTypes)
  const [selection, setSelection] = useState<LessonSelection>(initialSelection)
  const [orderedKeys, setOrderedKeys] = useState<string[] | null>(
    initialItems.length ? initialItems.map(assignmentItemKey) : null,
  )
  const [title, setTitle] = useState(initialTitle)
  // 模考模式：整场限时（分钟），确认页点「开始考试」后计时、到时自动交卷、切屏记录
  const [isExam, setIsExam] = useState(false)
  const [examMinutes, setExamMinutes] = useState(30)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [clearOpen, setClearOpen] = useState(false)
  const dirtyRef = useRef(false)
  const prevServerTypesRef = useRef(initialTypes)
  const prevServerSelectionRef = useRef(initialSelection)
  const prevServerTitleRef = useRef(initialTitle)
  const prevServerItemsRef = useRef(initialItems)
  const queryClient = useQueryClient()

  // 服务端指派变更时同步本地表单（如老师在另一设备改了指派）
  // 1. 用深比较判断是否真的变了，避免父组件重渲染导致的引用变化
  // 2. 用户已编辑过则不同步，避免覆盖正在编辑的内容
  useEffect(() => {
    const typesSame =
      JSON.stringify(initialTypes) ===
      JSON.stringify(prevServerTypesRef.current)
    const selectionSame =
      JSON.stringify(initialSelection) ===
      JSON.stringify(prevServerSelectionRef.current)
    const titleSame = initialTitle === prevServerTitleRef.current
    const itemsSame =
      JSON.stringify(initialItems) ===
      JSON.stringify(prevServerItemsRef.current)
    if (typesSame && selectionSame && titleSame && itemsSame) return
    prevServerTypesRef.current = initialTypes
    prevServerSelectionRef.current = initialSelection
    prevServerTitleRef.current = initialTitle
    prevServerItemsRef.current = initialItems
    if (!dirtyRef.current) {
      setTypes(initialTypes)
      setSelection(initialSelection)
      setTitle(initialTitle)
      setOrderedKeys(
        initialItems.length ? initialItems.map(assignmentItemKey) : null,
      )
    }
  }, [initialTypes, initialSelection, initialTitle, initialItems])

  const setTypesDirty = (
    next: LessonTypes | ((prev: LessonTypes) => LessonTypes),
  ) => {
    dirtyRef.current = true
    setTypes(next)
  }
  const setSelectionDirty = (
    next: LessonSelection | ((prev: LessonSelection) => LessonSelection),
  ) => {
    dirtyRef.current = true
    setSelection(next)
  }

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

  // 唯一题单：预览 / 数量摘要 / 提交请求共用同一份「按启用题型过滤后的题单」，
  // 避免教师取消勾选某题型后，预览或提交仍带上该题型已选内容。
  const planItems = useMemo(() => {
    const available = defaultAssignmentOrder(
      types.reading
        ? selection.passages.map((id) => ({ type: "passage", id }))
        : [],
      types.repeat
        ? selection.sentences.map((id) => ({ type: "repeat", id }))
        : [],
      types.qa && selection.scenarioId
        ? scenarioQuestions.map((q) => ({ type: "question", id: q.id }))
        : [],
    )
    return reconcileAssignmentOrder(available, orderedKeys)
  }, [types, selection, scenarioQuestions, orderedKeys])

  const moveItem = (index: number, direction: -1 | 1) => {
    dirtyRef.current = true
    setOrderedKeys(
      moveAssignmentItem(planItems, index, direction).map(assignmentItemKey),
    )
  }

  const planCounts = useMemo(
    () => ({
      reading: planItems.filter((i) => i.type === "passage").length,
      repeat: planItems.filter((i) => i.type === "repeat").length,
      qa: planItems.filter((i) => i.type === "question").length,
    }),
    [planItems],
  )

  const changed =
    JSON.stringify(types) !== JSON.stringify(initialTypes) ||
    JSON.stringify(selection) !== JSON.stringify(initialSelection) ||
    title.trim() !== initialTitle.trim() ||
    JSON.stringify(planItems.map(assignmentItemKey)) !==
      JSON.stringify(initialItems.map(assignmentItemKey))

  const publish = useMutation({
    mutationFn: (clear: boolean) =>
      ClassesService.setAssignment({
        code,
        requestBody: clear
          ? { items: [] }
          : {
              items: planItems,
              title: title.trim() || undefined,
              ...(isExam
                ? { is_exam: true, time_limit_minutes: examMinutes }
                : {}),
            },
      }),
    onSuccess: async (_, clear) => {
      setPreviewOpen(false)
      setClearOpen(false)
      dirtyRef.current = false
      toast.success(
        clear
          ? t({
              zh: "已恢复学生自主练习",
              en: "Restored student self practice",
            })
          : t({
              zh: "本次课堂练习已发布",
              en: "Class practice published",
            }),
      )
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["teacher", "board", code] }),
        queryClient.invalidateQueries({
          queryKey: ["teacher", "exercises", code],
        }),
        queryClient.invalidateQueries({ queryKey: ["admin", "sentences"] }),
      ])
    },
    onError: () =>
      toast.error(
        t({
          zh: "发布失败，选择已保留，请重试",
          en: "Publish failed — your selections are kept, please retry",
        }),
      ),
  })

  const toggleInList = (list: string[], id: string) =>
    list.includes(id) ? list.filter((x) => x !== id) : [...list, id]

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-secondary/40 px-5 py-4">
        <div>
          <p className="text-xs text-muted-foreground">
            {t({ zh: "学生当前练习", en: "Students are currently practicing" })}
          </p>
          <p className="mt-1 font-semibold">
            {hasItemAssignment
              ? t({
                  zh: `按题指派 · ${initialSelection.passages.length} 篇朗读 · ${initialSelection.sentences.length} 句复述 · ${currentQuestionCount(scenarios, initialSelection)} 道问答`,
                  en: `Item-based assignment · ${initialSelection.passages.length} read-aloud · ${initialSelection.sentences.length} repeat · ${currentQuestionCount(scenarios, initialSelection)} Q&A`,
                })
              : unitTitle
                ? t({
                    zh: `单元指派 · ${unitTitle}（旧版，重新发布后转为按题指派）`,
                    en: `Unit assignment · ${unitTitle} (legacy; republish to convert to item-based)`,
                  })
                : t({
                    zh: "自主练习 · 尚未安排统一内容",
                    en: "Self Practice · no shared content assigned yet",
                  })}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {hasItemAssignment || unitTitle
              ? t({
                  zh: "发布后，全班按本次设置练习。",
                  en: "After publishing, the whole class practices with these settings.",
                })
              : t({
                  zh: "发布后，全班按本次设置练习。",
                  en: "After publishing, the whole class practices with these settings.",
                })}
          </p>
        </div>
        {(hasItemAssignment || hasUnitAssignment) && (
          <Button variant="ghost" size="sm" onClick={() => setClearOpen(true)}>
            {t({ zh: "恢复自主练习", en: "Restore Self Practice" })}
          </Button>
        )}
      </div>
      <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
        <div className="space-y-6 rounded-2xl border bg-card p-6">
          <section>
            <h2 className="font-semibold">
              {t({ zh: "练习名称", en: "Practice Name" })}
            </h2>
            <p className="mb-3 mt-2 text-sm text-muted-foreground">
              {t({
                zh: "用一个清晰的名称标识这次发布，方便之后回看课堂练习版本。",
                en: "Give this publish a clear name so you can revisit classroom practice versions later.",
              })}
            </p>
            <Input
              value={title}
              maxLength={255}
              onChange={(event) => {
                dirtyRef.current = true
                setTitle(event.target.value)
              }}
              placeholder={t({
                zh: "例如：第 3 周｜旅行主题口语练习",
                en: "e.g., Week 3 | Travel-themed speaking",
              })}
            />
          </section>

          <section>
            <h2 className="font-semibold">
              {t({ zh: "模考模式", en: "Exam Mode" })}
            </h2>
            <p className="mb-3 mt-2 text-sm text-muted-foreground">
              {t({
                zh: "开启后整场限时：学生在确认页点「开始考试」后计时，到时自动交卷；考试中每题只能作答一次，切屏次数与离屏时长会被记录到教师面板。",
                en: 'Time-limited for the whole exam: the clock starts when a student taps "Start exam" on the confirmation screen and auto-submits at zero. One attempt per item; screen switches and away time are recorded for the teacher.',
              })}
            </p>
            <div className="flex flex-wrap items-center gap-4">
              <label
                htmlFor="exam-toggle"
                className="flex min-h-11 cursor-pointer items-center gap-2 text-sm"
              >
                <Checkbox
                  id="exam-toggle"
                  checked={isExam}
                  onCheckedChange={(checked) => {
                    dirtyRef.current = true
                    setIsExam(checked === true)
                  }}
                />
                {t({ zh: "作为模考发布", en: "Publish as exam" })}
              </label>
              {isExam && (
                <label
                  htmlFor="exam-minutes"
                  className="flex items-center gap-2 text-sm"
                >
                  <span className="sr-only">
                    {t({ zh: "限时（分钟）", en: "Time limit (minutes)" })}
                  </span>
                  <NumberInput
                    id="exam-minutes"
                    min={5}
                    max={240}
                    value={examMinutes}
                    onValueChange={(value) => {
                      dirtyRef.current = true
                      setExamMinutes(value)
                    }}
                    className="w-24"
                    aria-label={t({
                      zh: "限时（分钟，5–240）",
                      en: "Time limit (minutes, 5–240)",
                    })}
                  />
                  {t({ zh: "分钟（5–240）", en: "minutes (5–240)" })}
                </label>
              )}
            </div>
          </section>
          <section>
            <h2 className="font-semibold">
              {t({ zh: "1. 选择题型", en: "1. Choose Question Types" })}
            </h2>
            <p className="mb-4 mt-2 text-sm text-muted-foreground">
              {t({
                zh: "三种题型互相独立：勾选后在下方为该题型挑选内容。",
                en: "The three types are independent: check one, then pick its content below.",
              })}
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
                      setTypesDirty((current) => ({
                        ...current,
                        [type.key]: checked === true,
                      }))
                    }
                  />
                  <type.icon className="size-5 shrink-0 text-primary" />
                  <span>
                    <span className="block text-sm font-medium">
                      {t(type.title)}
                    </span>
                    <span className="mt-1 block text-xs text-muted-foreground">
                      {t(type.description)}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          </section>
          {types.reading && (
            <section>
              <h2 className="font-semibold">
                {t({ zh: "2. 朗读篇目", en: "2. Read Aloud Passages" })}
              </h2>
              <p className="mb-3 mt-2 text-sm text-muted-foreground">
                {t({
                  zh: "可多选：长文拆成几篇时学生按顺序分别朗读。",
                  en: "Multi-select: when a long text is split into passages, students read them in order.",
                })}
              </p>
              <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
                {passages.length === 0 && (
                  <p className="text-sm text-muted-foreground">
                    {t({
                      zh: "还没有朗读篇目，去题目库创建。",
                      en: "No read-aloud passages yet — create some in the Question Bank.",
                    })}
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
                        setSelectionDirty((cur) => ({
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
                        {t({
                          zh: `${p.topic} · 建议 ${p.suggested_seconds} 秒`,
                          en: `${p.topic} · suggested ${p.suggested_seconds}s`,
                        })}
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
                {types.reading ? "3" : "2"}.{" "}
                {t({ zh: "复述句", en: "Repeat Sentences" })}
              </h2>
              <p className="mb-3 mt-2 text-sm text-muted-foreground">
                {t({
                  zh: "从复述句题库多选，学生只能听语音复述。",
                  en: "Multi-select from the repeat-sentence bank; students repeat what they hear.",
                })}
              </p>
              <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
                {sentences.length === 0 && (
                  <p className="text-sm text-muted-foreground">
                    {t({
                      zh: "还没有复述句，去题目库创建。",
                      en: "No repeat sentences yet — create some in the Question Bank.",
                    })}
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
                        setSelectionDirty((cur) => ({
                          ...cur,
                          sentences: toggleInList(cur.sentences, s.id ?? ""),
                        }))
                      }
                    />
                    <span className="min-w-0">
                      <span className="block truncate text-sm">{s.text}</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        {t({
                          zh: `${s.suggested_seconds} 秒 · 可听 ${(s.replay_limit ?? 3) === 0 ? "不限" : `${s.replay_limit ?? 3} 次`}${s.passage_title ? ` · 挂篇目：${s.passage_title}` : " · 独立题"}`,
                          en: `${s.suggested_seconds}s · ${(s.replay_limit ?? 3) === 0 ? "unlimited replays" : `${s.replay_limit ?? 3} replays`}${s.passage_title ? ` · Passage: ${s.passage_title}` : " · Standalone"}`,
                        })}
                      </span>
                      {s.exam_kind && (
                        <span className="mt-1 flex flex-wrap gap-1">
                          <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] font-medium text-primary">
                            {t(
                              EXAM_KIND_LABELS[s.exam_kind] ?? {
                                zh: s.exam_kind,
                                en: s.exam_kind,
                              },
                            )}
                          </span>
                          {s.exam_level && (
                            <span className="rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground">
                              {t(
                                EXAM_LEVEL_LABELS[s.exam_level] ?? {
                                  zh: s.exam_level,
                                  en: s.exam_level,
                                },
                              )}
                            </span>
                          )}
                        </span>
                      )}
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
                . {t({ zh: "问答主题", en: "Q&A Topic" })}
              </h2>
              <p className="mb-3 mt-2 text-sm text-muted-foreground">
                {t({
                  zh: "选一个主题，该主题下全部题目按序进入本次练习。",
                  en: "Pick one topic; all its questions join this practice in order.",
                })}
              </p>
              <Select
                value={selection.scenarioId ?? ""}
                onValueChange={(id) =>
                  setSelectionDirty((cur) => ({
                    ...cur,
                    scenarioId: id || null,
                  }))
                }
              >
                <SelectTrigger
                  aria-label={t({
                    zh: "选择问答主题",
                    en: "Select a Q&A topic",
                  })}
                >
                  <SelectValue
                    placeholder={t({
                      zh: "选择问答主题",
                      en: "Select a Q&A topic",
                    })}
                  />
                </SelectTrigger>
                <SelectContent>
                  {scenarios
                    .filter((s) => s.is_active)
                    .map((s) => (
                      <SelectItem key={s.id} value={s.id}>
                        {t({
                          zh: `${s.topic}（${s.questions.length} 题）`,
                          en: `${s.topic} (${s.questions.length} questions)`,
                        })}
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
                        {t({
                          zh: `${q.suggested_seconds} 秒`,
                          en: `${q.suggested_seconds}s`,
                        })}
                      </span>
                      {q.exam_kind && (
                        <span className="ml-1.5 inline-flex gap-1 align-middle">
                          <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] font-medium text-primary">
                            {t(
                              EXAM_KIND_LABELS[q.exam_kind] ?? {
                                zh: q.exam_kind,
                                en: q.exam_kind,
                              },
                            )}
                          </span>
                          {q.exam_level && (
                            <span className="rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground">
                              {t(
                                EXAM_LEVEL_LABELS[q.exam_level] ?? {
                                  zh: q.exam_level,
                                  en: q.exam_level,
                                },
                              )}
                            </span>
                          )}
                        </span>
                      )}
                    </p>
                  ))}
                </div>
              )}
            </section>
          )}
          {planItems.length > 0 && (
            <section className="space-y-3">
              <h2 className="font-semibold">
                {t({ zh: "调整作答顺序", en: "Arrange Answer Order" })}
              </h2>
              <p className="text-sm text-muted-foreground">
                {t({
                  zh: "默认按复述句、问答交替；用上下按钮调整，学生会按此顺序练习。",
                  en: "Repeat sentences and Q&A alternate by default. Use the arrows to set the order students follow.",
                })}
              </p>
              <ol className="space-y-2">
                {planItems.map((item, index) => {
                  const label =
                    item.type === "passage"
                      ? passages.find((p) => p.id === item.id)?.title
                      : item.type === "repeat"
                        ? sentences.find((s) => s.id === item.id)?.text
                        : scenarioQuestions.find((q) => q.id === item.id)?.text
                  return (
                    <li
                      key={assignmentItemKey(item)}
                      className="flex min-w-0 items-center gap-2 rounded-lg border px-3 py-2"
                    >
                      <span className="w-6 shrink-0 text-sm font-medium">
                        {index + 1}.
                      </span>
                      <span className="min-w-0 flex-1 truncate text-sm">
                        {t(
                          ITEM_TYPE_LABELS[item.type] ?? {
                            zh: item.type,
                            en: item.type,
                          },
                        )}{" "}
                        · {label}
                      </span>
                      <Button
                        variant="outline"
                        size="icon-sm"
                        disabled={index === 0}
                        aria-label={t({
                          zh: `第 ${index + 1} 题上移`,
                          en: `Move item ${index + 1} up`,
                        })}
                        onClick={() => moveItem(index, -1)}
                      >
                        <ChevronUp />
                      </Button>
                      <Button
                        variant="outline"
                        size="icon-sm"
                        disabled={index === planItems.length - 1}
                        aria-label={t({
                          zh: `第 ${index + 1} 题下移`,
                          en: `Move item ${index + 1} down`,
                        })}
                        onClick={() => moveItem(index, 1)}
                      >
                        <ChevronDown />
                      </Button>
                    </li>
                  )
                })}
              </ol>
            </section>
          )}
        </div>
        <aside className="self-start rounded-2xl border bg-card p-6">
          <h2 className="font-semibold">
            {t({ zh: "检查并发布", en: "Review & Publish" })}
          </h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            {t({
              zh: "选好内容和题型后，先预览学生将看到的内容，再确认发布。",
              en: "After choosing content and types, preview what students will see, then confirm the publish.",
            })}
          </p>
          <div className="my-5 space-y-1 border-y py-4 text-sm">
            <p className="font-medium">
              {planCounts.reading > 0
                ? t({
                    zh: `朗读 ${planCounts.reading} 篇`,
                    en: `${planCounts.reading} Read Aloud`,
                  })
                : null}
              {planCounts.repeat > 0
                ? t({
                    zh: `复述 ${planCounts.repeat} 句`,
                    en: `${planCounts.repeat} Listen & Repeat`,
                  })
                : null}
              {planCounts.qa > 0
                ? t({
                    zh: `问答 ${planCounts.qa} 道`,
                    en: `${planCounts.qa} Scenario Q&A`,
                  })
                : null}
              {planCounts.reading + planCounts.repeat + planCounts.qa === 0 &&
                t({ zh: "尚未选择题型", en: "No question types selected" })}
            </p>
          </div>
          {problems.length ? (
            <ul className="space-y-3 text-sm leading-6 text-muted-foreground">
              {problems.map((problem) => (
                <li key={problem.zh}>{t(problem)}</li>
              ))}
            </ul>
          ) : (
            <p className="flex items-center gap-2 text-sm text-primary">
              <Check className="size-4" />
              {t({
                zh: "内容已齐备，可以预览",
                en: "Everything is ready — you can preview",
              })}
            </p>
          )}
          <Button
            className="mt-5 w-full"
            disabled={problems.length > 0 || publish.isPending}
            onClick={() => setPreviewOpen(true)}
          >
            <Eye className="size-4" />
            {t({ zh: "预览练习", en: "Preview Practice" })}
          </Button>
          <p className="mt-3 text-xs leading-5 text-muted-foreground">
            {t({
              zh: "当前选择尚未发布。只有确认发布后，才会更新学生练习。",
              en: "Your current selections aren't published yet. Student practice updates only after you confirm the publish.",
            })}
          </p>
          <Button variant="link" className="mt-2 h-auto px-0" asChild>
            <Link to="/create" search={{ kind: "reading", classroom: code }}>
              {t({
                zh: "到题目库补充内容 →",
                en: "Add content in the Question Bank →",
              })}
            </Link>
          </Button>
        </aside>
      </div>
      {exerciseHistory.length > 0 && (
        <details className="rounded-2xl border bg-card px-5 py-4">
          <summary className="cursor-pointer text-sm font-semibold">
            {t({
              zh: `发布历史（${exerciseHistory.length} 个版本）`,
              en: `Publish History (${exerciseHistory.length} versions)`,
            })}
          </summary>
          <div className="mt-4 divide-y text-sm">
            {exerciseHistory.map((exercise) => (
              <div
                key={exercise.id}
                className="flex flex-wrap items-center justify-between gap-2 py-3 first:pt-0 last:pb-0"
              >
                <span>
                  {t({
                    zh: `v${exercise.version_no} · ${exercise.title} · ${exercise.item_count} 道题`,
                    en: `v${exercise.version_no} · ${exercise.title} · ${exercise.item_count} items`,
                  })}
                </span>
                <span className="text-xs text-muted-foreground">
                  {exercise.status === "published"
                    ? t({ zh: "当前发布", en: "Current publish" })
                    : t({ zh: "已归档", en: "Archived" })}
                  {exercise.published_at
                    ? ` · ${new Date(exercise.published_at).toLocaleString()}`
                    : ""}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}
      <Dialog
        open={previewOpen}
        onOpenChange={(open) => !publish.isPending && setPreviewOpen(open)}
      >
        <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {t({ zh: "练习预览", en: "Practice Preview" })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: `发布到课堂 ${code}。学生按以下顺序作答；已有作答的处理沿用当前课堂规则。`,
                en: `Will be published to classroom ${code}. Students answer in the order below; existing answers follow the classroom's current rules.`,
              })}
            </DialogDescription>
          </DialogHeader>
          <ol className="space-y-3">
            {planItems.map((item, index) => {
              const source =
                item.type === "passage"
                  ? selectedPassages.find((p) => p.id === item.id)
                  : item.type === "repeat"
                    ? selectedSentences.find((s) => s.id === item.id)
                    : scenarioQuestions.find((q) => q.id === item.id)
              return (
                <li
                  key={assignmentItemKey(item)}
                  className="rounded-xl border p-4"
                >
                  <h3 className="font-semibold">
                    {index + 1}.{" "}
                    {t(
                      ITEM_TYPE_LABELS[item.type] ?? {
                        zh: item.type,
                        en: item.type,
                      },
                    )}
                    {item.type === "passage" && source && "title" in source
                      ? ` · ${source.title}`
                      : ""}
                  </h3>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-6">
                    {source?.text}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t({
                      zh: `建议 ${source?.suggested_seconds ?? 0} 秒`,
                      en: `Suggested ${source?.suggested_seconds ?? 0}s`,
                    })}
                  </p>
                </li>
              )
            })}
          </ol>
          <DialogFooter>
            <Button
              variant="outline"
              disabled={publish.isPending}
              onClick={() => setPreviewOpen(false)}
            >
              {t({ zh: "返回修改", en: "Back to Edit" })}
            </Button>
            <LoadingButton
              loading={publish.isPending}
              disabled={problems.length > 0 || !changed}
              onClick={() => publish.mutate(false)}
            >
              <Send className="size-4" />
              {changed
                ? t({
                    zh: "确认发布到课堂",
                    en: "Confirm Publish to Classroom",
                  })
                : t({
                    zh: "与当前发布一致",
                    en: "Same as current publish",
                  })}
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
            <DialogTitle>
              {t({
                zh: "恢复学生自主练习？",
                en: "Restore student self practice?",
              })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: "移除课堂统一指派后，学生将按各自学习进度练习，已提交记录保留。",
                en: "After removing the classroom-wide assignment, students practice at their own pace; submitted records are kept.",
              })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              disabled={publish.isPending}
              onClick={() => setClearOpen(false)}
            >
              {t({ zh: "取消", en: "Cancel" })}
            </Button>
            <LoadingButton
              loading={publish.isPending}
              onClick={() => publish.mutate(true)}
            >
              {t({ zh: "确认恢复", en: "Confirm Restore" })}
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
