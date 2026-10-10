import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BookOpenText, Ear, Info, MessagesSquare } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import {
  AdminService,
  type AssignmentInfo,
  type AssignmentItemIn,
  ClassesService,
  type ClassroomExercisePublic,
  type InstructionPublic,
  type PassageWithSentences,
  type ScenarioOut,
  type SentenceWithPassage,
} from "@/client"
import InstructionsSection from "@/components/Teaching/AssignmentComposer/InstructionsSection"
import OrderSection from "@/components/Teaching/AssignmentComposer/OrderSection"
import PassagesSection from "@/components/Teaching/AssignmentComposer/PassagesSection"
import {
  PreviewDialog,
  PublishHistory,
} from "@/components/Teaching/AssignmentComposer/PreviewDialog"
import PublishSidebar from "@/components/Teaching/AssignmentComposer/PublishSidebar"
import ScenariosSection from "@/components/Teaching/AssignmentComposer/ScenariosSection"
import SentencesSection from "@/components/Teaching/AssignmentComposer/SentencesSection"
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
import { normalizeReadingSelection } from "@/lib/reading-selection"
import { TERMS } from "@/lib/terms"

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
    title: TERMS.typeQa,
    description: {
      zh: "按主题出题，一问一答",
      en: "Questions by topic, ask and answer",
    },
    icon: MessagesSquare,
  },
  {
    key: "instruction",
    title: TERMS.typeInstruction,
    description: {
      zh: "纯文字引导页：学生读完点「继续」进入下一题，模考中按秒数计时",
      en: "A text-only intro page: students tap Continue to move on; timed in exams",
    },
    icon: Info,
  },
] as const

type AssignedItemRef = { [key: string]: string }

export function AssignmentComposer({
  code,
  assignment,
  assignedItems,
  currentExercise,
  onViewHistory,
}: {
  code: string
  assignment?: AssignmentInfo | null
  assignedItems?: AssignedItemRef[] | null
  currentExercise?: ClassroomExercisePublic | null
  onViewHistory?: (exerciseId: string) => void
}) {
  const { t } = useI18n()
  // 各题型互相独立：各自的题库列表分别加载
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
  const instructionsQuery = useQuery({
    queryKey: ["admin", "instructions"],
    queryFn: () => AdminService.listInstructions(),
  })
  const exercisesQuery = useQuery({
    queryKey: ["teacher", "exercises", code],
    queryFn: () => ClassesService.listClassroomExercises({ code }),
  })

  if (
    passagesQuery.isError ||
    sentencesQuery.isError ||
    scenariosQuery.isError ||
    instructionsQuery.isError
  )
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
            void instructionsQuery.refetch()
          }}
        >
          {t({ zh: "重新加载", en: "Reload" })}
        </Button>
      </div>
    )
  if (
    passagesQuery.isPending ||
    sentencesQuery.isPending ||
    scenariosQuery.isPending ||
    instructionsQuery.isPending
  )
    return (
      <p className="rounded-2xl border p-6 text-muted-foreground">
        {t({
          zh: "正在加载可用练习…",
          en: "Loading available practice…",
        })}
      </p>
    )

  // passages/scenarios 列表接口已改分页信封（limit=None 全量，组卷不变）
  const passages = passagesQuery.data?.data
  const sentences = sentencesQuery.data
  const scenarios = scenariosQuery.data?.data
  const instructions = instructionsQuery.data

  // 当前按题指派回显
  const currentItems = normalizeReadingSelection(
    (assignedItems ?? []).map((item) => ({ type: item.type, id: item.id })),
    passages,
  )
  const hasLegacyReadingSelection = (assignedItems ?? []).some(
    (item) =>
      item.type === "passage" &&
      !currentItems.some(
        (current) => current.type === "passage" && current.id === item.id,
      ),
  )
  const currentPassages = currentItems
    .filter((i) => i.type === "passage")
    .map((i) => i.id)
  const currentSentences = currentItems
    .filter((i) => i.type === "repeat")
    .map((i) => i.id)
  const currentQuestionIds = new Set(
    currentItems.filter((i) => i.type === "question").map((i) => i.id),
  )
  const currentScenarioIds = scenarios
    .filter((s) => s.questions.some((q) => currentQuestionIds.has(q.id)))
    .map((s) => s.id)
  const currentInstructionIds = currentItems
    .filter((i) => i.type === "instruction")
    .map((i) => i.id)

  const initialTypes: LessonTypes = {
    reading: currentPassages.length > 0,
    repeat: currentSentences.length > 0,
    qa: currentQuestionIds.size > 0,
    instruction: currentInstructionIds.length > 0,
  }
  const initialSelection: LessonSelection = {
    passages: currentPassages,
    sentences: currentSentences,
    scenarioIds: currentScenarioIds,
    instructions: currentInstructionIds,
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
      instructions={instructions}
      initialTypes={initialTypes}
      initialSelection={initialSelection}
      initialItems={currentItems as AssignmentItemIn[]}
      hasLegacyReadingSelection={hasLegacyReadingSelection}
      initialTitle={
        currentExercise?.title ?? t({ zh: "课堂练习", en: "Class Practice" })
      }
      exerciseHistory={exercisesQuery.data ?? []}
      onViewHistory={onViewHistory}
      initialIsExam={currentExercise?.is_exam ?? false}
      initialExamMinutes={currentExercise?.time_limit_minutes ?? 30}
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
  instructions,
  initialTypes,
  initialSelection,
  initialItems,
  hasLegacyReadingSelection,
  initialTitle,
  exerciseHistory,
  onViewHistory,
  initialIsExam,
  initialExamMinutes,
}: {
  code: string
  hasUnitAssignment: boolean
  unitTitle?: string
  hasItemAssignment: boolean
  passages: PassageWithSentences[]
  sentences: SentenceWithPassage[]
  scenarios: ScenarioOut[]
  instructions: InstructionPublic[]
  initialTypes: LessonTypes
  initialSelection: LessonSelection
  initialItems: AssignmentItemIn[]
  hasLegacyReadingSelection: boolean
  initialTitle: string
  exerciseHistory: ClassroomExercisePublic[]
  onViewHistory?: (exerciseId: string) => void
  initialIsExam: boolean
  initialExamMinutes: number
}) {
  const { t } = useI18n()
  const [types, setTypes] = useState<LessonTypes>(initialTypes)
  const [selection, setSelection] = useState<LessonSelection>(initialSelection)
  const [orderedKeys, setOrderedKeys] = useState<string[] | null>(
    initialItems.length ? initialItems.map(assignmentItemKey) : null,
  )
  const [title, setTitle] = useState(initialTitle)
  // 模考模式：整场限时（分钟），确认页点「开始考试」后计时、到时自动交卷、切屏记录
  const [isExam, setIsExam] = useState(initialIsExam)
  const [examMinutes, setExamMinutes] = useState(initialExamMinutes)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [clearOpen, setClearOpen] = useState(false)
  const dirtyRef = useRef(false)
  const prevServerTypesRef = useRef(initialTypes)
  const prevServerSelectionRef = useRef(initialSelection)
  const prevServerTitleRef = useRef(initialTitle)
  const prevServerItemsRef = useRef(initialItems)
  const prevServerExamRef = useRef({
    isExam: initialIsExam,
    minutes: initialExamMinutes,
  })
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
    const examSame =
      initialIsExam === prevServerExamRef.current.isExam &&
      initialExamMinutes === prevServerExamRef.current.minutes
    if (typesSame && selectionSame && titleSame && itemsSame && examSame) return
    prevServerTypesRef.current = initialTypes
    prevServerSelectionRef.current = initialSelection
    prevServerTitleRef.current = initialTitle
    prevServerItemsRef.current = initialItems
    prevServerExamRef.current = {
      isExam: initialIsExam,
      minutes: initialExamMinutes,
    }
    if (!dirtyRef.current) {
      setTypes(initialTypes)
      setSelection(initialSelection)
      setTitle(initialTitle)
      setIsExam(initialIsExam)
      setExamMinutes(initialExamMinutes)
      setOrderedKeys(
        initialItems.length ? initialItems.map(assignmentItemKey) : null,
      )
    }
  }, [
    initialTypes,
    initialSelection,
    initialTitle,
    initialItems,
    initialIsExam,
    initialExamMinutes,
  ])

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

  const { scenarios: selectedScenarios, problems: selectionProblems } =
    inspectSelection(types, selection, {
      sentences,
      scenarios,
      instructions,
    })
  const problems =
    isExam &&
    (!Number.isInteger(examMinutes) || examMinutes < 5 || examMinutes > 240)
      ? [
          ...selectionProblems,
          {
            zh: "模考限时须为 5–240 分钟的整数",
            en: "Exam time must be a whole number between 5 and 240 minutes",
          },
        ]
      : selectionProblems

  const selectedPassages = passages.filter((p) =>
    selection.passages.includes(p.id ?? ""),
  )
  const selectedSentences = sentences.filter((s) =>
    selection.sentences.includes(s.id ?? ""),
  )
  const selectedInstructions = instructions.filter((i) =>
    selection.instructions.includes(i.id),
  )
  const scenarioQuestions = selectedScenarios.flatMap(
    (scenario) => scenario.questions,
  )

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
      types.qa && selection.scenarioIds.length > 0
        ? scenarioQuestions.map((q) => ({ type: "question", id: q.id }))
        : [],
      types.instruction
        ? selection.instructions.map((id) => ({ type: "instruction", id }))
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
      // 拆分文章按句展开后的逐句题数（预览摘要给学生视角的总题量）
      readingSentences: selectedPassages.reduce(
        (total, p) =>
          total + (p.reading_split ? (p.reading_segments ?? []).length : 0),
        0,
      ),
      repeat: planItems.filter((i) => i.type === "repeat").length,
      qa: planItems.filter((i) => i.type === "question").length,
      instruction: planItems.filter((i) => i.type === "instruction").length,
    }),
    [planItems, selectedPassages],
  )

  const changed =
    isExam !== initialIsExam ||
    (isExam && examMinutes !== initialExamMinutes) ||
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
        queryClient.invalidateQueries({ queryKey: ["admin", "instructions"] }),
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

  // 章节号按已启用题型动态编号（「选择题型」恒为 1，选题区按显示顺序递增）
  let sectionCounter = 1
  const nextSectionNo = () => ++sectionCounter
  const readingNo = types.reading ? nextSectionNo() : null
  const repeatNo = types.repeat ? nextSectionNo() : null
  const qaNo = types.qa ? nextSectionNo() : null
  const instructionNo = types.instruction ? nextSectionNo() : null

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-secondary/40 px-5 py-4">
        <div>
          <p className="text-xs text-muted-foreground">
            {t({ zh: "学生当前练习", en: "Students are currently practicing" })}
          </p>
          <p className="mt-1 font-semibold">
            {hasLegacyReadingSelection
              ? t({
                  zh: "原分段练习 · 保留已发布题单",
                  en: "Legacy segment practice · published items preserved",
                })
              : hasItemAssignment
                ? t({
                    zh: `按题指派 · ${initialSelection.passages.length} 篇朗读 · ${initialSelection.sentences.length} 句复述 · ${currentQuestionCount(scenarios, initialSelection)} 道问答${initialSelection.instructions.length > 0 ? ` · ${initialSelection.instructions.length} 条说明` : ""}`,
                    en: `Item-based assignment · ${initialSelection.passages.length} read-aloud · ${initialSelection.sentences.length} repeat · ${currentQuestionCount(scenarios, initialSelection)} Q&A${initialSelection.instructions.length > 0 ? ` · ${initialSelection.instructions.length} instructions` : ""}`,
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
            {hasLegacyReadingSelection
              ? t({
                  zh: "下方选题已归回文章，重新发布后按整篇文章练习。",
                  en: "Selections below now refer to whole articles. Republish to practice complete articles.",
                })
              : hasItemAssignment || unitTitle
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
        <div className="min-w-0 space-y-6 rounded-2xl border bg-card p-4 sm:p-6">
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
                zh: "各题型互相独立：勾选后在下方为该题型挑选内容。",
                en: "The types are independent: check one, then pick its content below.",
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
            <PassagesSection
              sectionNo={readingNo ?? 0}
              passages={passages}
              selectedIds={selection.passages}
              onToggle={(id) =>
                setSelectionDirty((cur) => ({
                  ...cur,
                  passages: toggleInList(cur.passages, id),
                }))
              }
            />
          )}
          {types.repeat && (
            <SentencesSection
              sectionNo={repeatNo ?? 0}
              sentences={sentences}
              selectedIds={selection.sentences}
              onToggle={(id) =>
                setSelectionDirty((cur) => ({
                  ...cur,
                  sentences: toggleInList(cur.sentences, id),
                }))
              }
            />
          )}
          {types.qa && (
            <ScenariosSection
              sectionNo={qaNo ?? 0}
              scenarios={scenarios}
              selectedIds={selection.scenarioIds}
              selectedScenarios={selectedScenarios}
              onToggle={(id) =>
                setSelectionDirty((cur) => ({
                  ...cur,
                  scenarioIds: toggleInList(cur.scenarioIds, id),
                }))
              }
            />
          )}
          {types.instruction && (
            <InstructionsSection
              sectionNo={instructionNo ?? 0}
              instructions={instructions}
              selectedIds={selection.instructions}
              onToggle={(id) =>
                setSelectionDirty((cur) => ({
                  ...cur,
                  instructions: toggleInList(cur.instructions, id),
                }))
              }
              onAddCreated={(id) =>
                setSelectionDirty((cur) => ({
                  ...cur,
                  instructions: [...cur.instructions, id],
                }))
              }
              onRemoveDeleted={(id) =>
                setSelectionDirty((cur) => ({
                  ...cur,
                  instructions: cur.instructions.filter((x) => x !== id),
                }))
              }
              onDirty={() => {
                dirtyRef.current = true
              }}
            />
          )}
          {planItems.length > 0 && (
            <OrderSection
              planItems={planItems}
              passages={passages}
              sentences={sentences}
              instructions={instructions}
              scenarioQuestions={scenarioQuestions}
              onMove={moveItem}
            />
          )}
        </div>
        <PublishSidebar
          code={code}
          planCounts={planCounts}
          problems={problems}
          publishPending={publish.isPending}
          onPreview={() => setPreviewOpen(true)}
        />
      </div>
      <PublishHistory
        exerciseHistory={exerciseHistory}
        onViewHistory={onViewHistory}
      />
      <PreviewDialog
        code={code}
        open={previewOpen}
        onOpenChange={(open) => !publish.isPending && setPreviewOpen(open)}
        planItems={planItems}
        selectedPassages={selectedPassages}
        selectedSentences={selectedSentences}
        selectedInstructions={selectedInstructions}
        scenarioQuestions={scenarioQuestions}
        publishPending={publish.isPending}
        changed={changed}
        problemsCount={problems.length}
        onPublish={() => publish.mutate(false)}
      />
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
  return scenarios
    .filter((scenario) => selection.scenarioIds.includes(scenario.id))
    .reduce((count, scenario) => count + scenario.questions.length, 0)
}
