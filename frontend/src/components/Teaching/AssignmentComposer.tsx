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
import { COMPOSER_PRESET_KEY } from "@/lib/questionImport"
import { normalizeReadingSelection } from "@/lib/reading-selection"
import { TERMS } from "@/lib/terms"
import { extractErrorMessage } from "@/utils"

/** 预选刷新涉及的全部题库查询键（成功判据逐个核对 dataUpdatedAt） */
const PRESET_QUERY_KEYS = [
  ["admin", "passages"],
  ["admin", "sentences"],
  ["admin", "scenarios"],
  ["admin", "instructions"],
] as const

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
    if (
      !(
        passagesQuery.data &&
        sentencesQuery.data &&
        scenariosQuery.data &&
        instructionsQuery.data
      )
    )
      // 有缓存数据时后台刷新失败不应整块报错（离线时组卷要能用缓存渲染，
      // 「带入组卷」预选的暂缓提示在表单内给出）；完全无数据才走错误态
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
  ) {
    // 题库刷新悬挂期间 ComposerForm 尚未挂载（预选等待条在表单内）——
    // 有「带入组卷」交接键时把等待提示提到这一层，老师不会无提示干等
    const hasPreset = Boolean(sessionStorage.getItem(COMPOSER_PRESET_KEY))
    return (
      <div className="space-y-3">
        {hasPreset && (
          <p className="rounded-xl bg-secondary/70 p-3 text-sm text-muted-foreground">
            {t({
              zh: "正在刷新题库并带入本批题目…（网络较慢时请稍候）",
              en: "Refreshing the question bank and pre-selecting this batch… (may take a moment on slow networks)",
            })}
          </p>
        )}
        <p className="rounded-2xl border p-6 text-muted-foreground">
          {t({
            zh: "正在加载可用练习…",
            en: "Loading available practice…",
          })}
        </p>
      </div>
    )
  }

  // passages/scenarios 列表接口已改分页信封（limit=None 全量，组卷不变）。
  // ?? [] 兜底：信封缺失（旧 mock/旧缓存）时退化为空列表，不崩 ErrorBoundary。
  const passages = passagesQuery.data?.data ?? []
  const sentences = sentencesQuery.data ?? []
  const scenarios = scenariosQuery.data?.data ?? []
  const instructions = instructionsQuery.data ?? []

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
  // 回显按题目级恢复：已发布只含主题部分题目时，白名单=那些题（否则空
  // 白名单代表「主题全部题」，重新进入会把同主题旧题混进题单（评审 P2）
  const currentScenarioQuestions = scenarios
    .filter((s) => currentScenarioIds.includes(s.id))
    .flatMap((s) => s.questions.map((q) => q.id))
  const partialQuestions =
    currentQuestionIds.size > 0 &&
    currentScenarioQuestions.some((id) => !currentQuestionIds.has(id))
  const initialSelection: LessonSelection = {
    passages: currentPassages,
    sentences: currentSentences,
    scenarioIds: currentScenarioIds,
    instructions: currentInstructionIds,
    questions: partialQuestions ? [...currentQuestionIds] : [],
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

  // 题库批量导入「带入组卷」：一次性预选本批新建题目。分两步防「旧缓存
  // 丢预选」（评审 P2）：① 挂载发现交接键 → invalidate 四个题库查询强制
  // 刷新（staleTime 内的旧缓存不含刚导入的新题，直接消费会把新题过滤掉
  // 并删掉交接数据）；② 待本批 ID 全部可解析（或刷新完成后仍缺失）才消费。
  // 问答按题目白名单带入（selection.questions），不整主题展开混入旧题。
  const presetDoneRef = useRef(false)
  const [presetRefreshed, setPresetRefreshed] = useState(false)
  const [presetBlocked, setPresetBlocked] = useState(false)
  /** 刷新成功后仍缺失的题目 id（已被删除等）：等老师确认继续用有效题或取消 */
  const [presetMissing, setPresetMissing] = useState<string[]>([])
  /** 刷新进行中（含网络悬挂）：给老师可见的等待提示，落地后转入终态 */
  const [presetWaiting, setPresetWaiting] = useState(false)
  /** invalidate 起始时刻：刷新成功的判据是 dataUpdatedAt 晚于它（区分
   * 「请求失败/离线」与「刷新成功但题目确实不在了」，评审 P2） */
  const presetInvalidatedAtRef = useRef(0)
  const presetRawRef = useRef<string | null>(null)
  // biome-ignore lint/correctness/useExhaustiveDependencies: 仅挂载时探测交接键并触发一次刷新
  useEffect(() => {
    const raw = sessionStorage.getItem(COMPOSER_PRESET_KEY)
    if (raw) {
      presetRawRef.current = raw
      setPresetWaiting(true)
      presetInvalidatedAtRef.current = Date.now()
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ["admin", "passages"] }),
        queryClient.invalidateQueries({ queryKey: ["admin", "sentences"] }),
        queryClient.invalidateQueries({ queryKey: ["admin", "scenarios"] }),
        queryClient.invalidateQueries({ queryKey: ["admin", "instructions"] }),
      ]).then(() => setPresetRefreshed(true))
    }
  }, [])
  // biome-ignore lint/correctness/useExhaustiveDependencies: 一次性消费——依赖里只需数据数组与刷新标记；setter 为组件内稳定语义函数
  useEffect(() => {
    if (presetDoneRef.current) {
      return
    }
    const raw = sessionStorage.getItem(COMPOSER_PRESET_KEY)
    if (!raw) {
      return
    }
    let preset: {
      passages?: string[]
      sentences?: string[]
      questions?: string[]
      instructions?: string[]
    }
    try {
      preset = JSON.parse(raw) as typeof preset
    } catch {
      sessionStorage.removeItem(COMPOSER_PRESET_KEY)
      presetDoneRef.current = true
      return
    }
    const allPresetIds = [
      ...(preset.passages ?? []),
      ...(preset.sentences ?? []),
      ...(preset.questions ?? []),
      ...(preset.instructions ?? []),
    ]
    const knownIds = new Set<string>(
      [
        ...passages.map((item) => item.id),
        ...sentences.map((item) => item.id),
        ...instructions.map((item) => item.id),
        ...scenarios.flatMap((scenario) => scenario.questions.map((q) => q.id)),
      ].filter((id): id is string => Boolean(id)),
    )
    // 等 invalidate 落地再判定——id 在**过期缓存**里可解析不代表题还在
    // （导入后缓存刷新前可能已被删除，评审 P2）
    if (!presetRefreshed) {
      return
    }
    const missing = allPresetIds.filter((id) => !knownIds.has(id))
    // invalidate 完成 ≠ 刷新成功：全部查询拿到新数据（dataUpdatedAt 晚于
    // t0）时，仍缺失 = 题目确实不在了 → 老师确认（继续用有效题/取消）；
    // 刷新失败（离线）则回落到现有缓存判定——全部 id 在缓存可解析（只是
    // 可能偏旧）时照常消费，否则暂缓待重试
    const t0 = presetInvalidatedAtRef.current
    const allFresh = PRESET_QUERY_KEYS.every((key) => {
      const state = queryClient.getQueryState(key)
      return (state?.dataUpdatedAt ?? 0) > t0
    })
    if (missing.length === 0) {
      consumePreset(preset)
      return
    }
    if (allFresh) {
      setPresetMissing(missing)
      setPresetWaiting(false)
      return
    }
    setPresetBlocked(true)
    setPresetWaiting(false)
  }, [passages, sentences, scenarios, instructions, presetRefreshed])

  /** 消费交接预选（dropIds = 老师确认放弃的缺失项，正常路径为空集） */
  const consumePreset = (
    preset: {
      passages?: string[]
      sentences?: string[]
      questions?: string[]
      instructions?: string[]
    },
    dropIds: Set<string> = new Set(),
  ) => {
    sessionStorage.removeItem(COMPOSER_PRESET_KEY)
    presetRawRef.current = null
    presetDoneRef.current = true
    setPresetBlocked(false)
    setPresetMissing([])
    setPresetWaiting(false)
    const keep = (id: string) => !dropIds.has(id)
    const presetScenarioIds = new Set<string>()
    const validQuestions: string[] = []
    for (const scenario of scenarios) {
      for (const q of scenario.questions) {
        if (preset.questions?.includes(q.id) && keep(q.id)) {
          presetScenarioIds.add(scenario.id)
          validQuestions.push(q.id)
        }
      }
    }
    const validPassages = (preset.passages ?? []).filter(
      (id) => keep(id) && passages.some((p) => p.id === id),
    )
    const validSentences = (preset.sentences ?? []).filter(
      (id) => keep(id) && sentences.some((s_) => s_.id === id),
    )
    const validInstructions = (preset.instructions ?? []).filter(
      (id) => keep(id) && instructions.some((i) => i.id === id),
    )
    setSelectionDirty((prev) => ({
      passages: [...new Set([...prev.passages, ...validPassages])],
      sentences: [...new Set([...prev.sentences, ...validSentences])],
      scenarioIds: [...new Set([...prev.scenarioIds, ...presetScenarioIds])],
      instructions: [...new Set([...prev.instructions, ...validInstructions])],
      questions: [...new Set([...prev.questions, ...validQuestions])],
    }))
    setTypesDirty((prev) => ({
      ...prev,
      reading: prev.reading || validPassages.length > 0,
      repeat: prev.repeat || validSentences.length > 0,
      qa: prev.qa || presetScenarioIds.size > 0,
      instruction: prev.instruction || validInstructions.length > 0,
    }))
  }

  /** 取消带入：丢弃交接键（缺失确认的「取消」路径） */
  const discardPreset = () => {
    sessionStorage.removeItem(COMPOSER_PRESET_KEY)
    presetRawRef.current = null
    presetDoneRef.current = true
    setPresetBlocked(false)
    setPresetMissing([])
    setPresetWaiting(false)
  }

  // 题目级白名单（批量导入带入组卷时非空）：只出白名单内的问答题，
  // 避免勾选主题就混入同主题全部旧题。须先于就绪校验计算（空题单校验）
  const scenarioQuestions = scenarios
    .filter((scenario) => selection.scenarioIds.includes(scenario.id))
    .flatMap((scenario) => scenario.questions)
  const filteredScenarioQuestions =
    selection.questions.length > 0
      ? scenarioQuestions.filter((q) => selection.questions.includes(q.id))
      : scenarioQuestions
  const { scenarios: selectedScenarios, problems: selectionProblems } =
    inspectSelection(types, selection, {
      sentences,
      scenarios,
      instructions,
    })
  const qaEffectiveEmpty =
    types.qa &&
    selection.scenarioIds.length > 0 &&
    filteredScenarioQuestions.length === 0
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
      : [
          ...selectionProblems,
          ...(qaEffectiveEmpty
            ? [
                {
                  zh: "情景问答的最终题单为空：题单白名单里没有当前所选主题的题目。请重新勾选主题，或点「改为出主题全部题目」。",
                  en: "The final Q&A list is empty: the batch filter has no questions under the selected topics. Re-check topics or include all topic questions.",
                },
              ]
            : []),
        ]

  const selectedPassages = passages.filter((p) =>
    selection.passages.includes(p.id ?? ""),
  )
  const selectedSentences = sentences.filter((s) =>
    selection.sentences.includes(s.id ?? ""),
  )
  const selectedInstructions = instructions.filter((i) =>
    selection.instructions.includes(i.id),
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
        ? filteredScenarioQuestions.map((q) => ({ type: "question", id: q.id }))
        : [],
      types.instruction
        ? selection.instructions.map((id) => ({ type: "instruction", id }))
        : [],
    )
    return reconcileAssignmentOrder(available, orderedKeys)
  }, [types, selection, filteredScenarioQuestions, orderedKeys])

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
                ? {
                    is_exam: true,
                    automated_exam: true,
                    time_limit_minutes: examMinutes,
                  }
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
    onError: (err) => toast.error(extractErrorMessage(err)),
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
          {presetWaiting && (
            <p className="rounded-xl bg-secondary/70 p-3 text-sm text-muted-foreground">
              {t({
                zh: "正在刷新题库并带入本批题目…（网络较慢时请稍候）",
                en: "Refreshing the question bank and pre-selecting this batch… (may take a moment on slow networks)",
              })}
            </p>
          )}
          {presetMissing.length > 0 && !presetDoneRef.current && (
            <div className="space-y-2 rounded-xl bg-amber-100 p-3 text-sm text-amber-900 dark:bg-amber-900/40 dark:text-amber-200">
              <p>
                {t({
                  zh: `「带入组卷」的 ${presetMissing.length} 道题已不在题库（可能被删除），无法带入。`,
                  en: `${presetMissing.length} item(s) from the imported batch are no longer in the bank (possibly deleted) and can't be pre-selected.`,
                })}
              </p>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  className="min-h-11"
                  onClick={() => {
                    const raw = presetRawRef.current
                    if (!raw) {
                      discardPreset()
                      return
                    }
                    try {
                      consumePreset(
                        JSON.parse(raw) as Parameters<typeof consumePreset>[0],
                        new Set(presetMissing),
                      )
                    } catch {
                      discardPreset()
                    }
                  }}
                >
                  {t({
                    zh: "继续带入其余题目",
                    en: "Pre-select the rest",
                  })}
                </Button>
                <Button
                  variant="outline"
                  className="min-h-11"
                  onClick={discardPreset}
                >
                  {t({ zh: "取消带入", en: "Discard batch" })}
                </Button>
              </div>
            </div>
          )}
          {presetBlocked && (
            <p className="rounded-xl bg-amber-100 p-3 text-sm text-amber-900 dark:bg-amber-900/40 dark:text-amber-200">
              {t({
                zh: "题库数据刷新失败，「带入组卷」的本批题目暂未选中（不会丢）。请检查网络后离开再进入本页，会自动重试带入。",
                en: "Failed to refresh the question bank, so the imported batch hasn't been pre-selected (it's kept). Check the network and re-enter this page to retry.",
              })}
            </p>
          )}
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
          {types.qa && selection.questions.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 rounded-xl bg-secondary/60 p-2 text-sm">
              <span>
                {t({
                  zh: `已按「带入组卷」只出本批新建题（${filteredScenarioQuestions.length}/${scenarioQuestions.length} 题）`,
                  en: `Batch filter on: ${filteredScenarioQuestions.length} of ${scenarioQuestions.length} questions`,
                })}
              </span>
              <Button
                variant="outline"
                className="h-9"
                onClick={() =>
                  setSelectionDirty((cur) => ({ ...cur, questions: [] }))
                }
              >
                {t({
                  zh: "改为出主题全部题目",
                  en: "Include all topic questions",
                })}
              </Button>
            </div>
          )}
          {types.qa && (
            <ScenariosSection
              sectionNo={qaNo ?? 0}
              scenarios={scenarios}
              selectedIds={selection.scenarioIds}
              selectedScenarios={selectedScenarios}
              onToggle={(id) =>
                setSelectionDirty((cur) => {
                  const unchecking = cur.scenarioIds.includes(id)
                  const topicQuestions = (
                    scenarios.find((s) => s.id === id)?.questions ?? []
                  ).map((q) => q.id)
                  if (unchecking) {
                    return {
                      ...cur,
                      scenarioIds: toggleInList(cur.scenarioIds, id),
                      // 取消的主题不再出题：白名单同步剪掉它的题，避免
                      // 「白名单只剩未选主题的题」把最终题单掏空
                      questions: cur.questions.filter(
                        (qid) => !topicQuestions.includes(qid),
                      ),
                    }
                  }
                  // 新勾主题：白名单非空（逐题模式）时并入该主题全部题——
                  // 只加 scenarioIds 不扩白名单会漏掉新主题的题（评审 P2）
                  const merging = cur.questions.length > 0
                  return {
                    ...cur,
                    scenarioIds: toggleInList(cur.scenarioIds, id),
                    questions: merging
                      ? [...new Set([...cur.questions, ...topicQuestions])]
                      : cur.questions,
                  }
                })
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
    .reduce(
      (count, scenario) =>
        count +
        (selection.questions.length > 0
          ? scenario.questions.filter((q) => selection.questions.includes(q.id))
              .length
          : scenario.questions.length),
      0,
    )
}
