import { useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import type {
  InstructionPublic,
  PassageWithSentences,
  ScenarioOut,
  SentenceWithPassage,
} from "@/client"
import type { LessonSelection, LessonTypes } from "@/lib/lesson-readiness"
import { COMPOSER_PRESET_KEY } from "@/lib/questionImport"

export function useComposerPreset({
  passages,
  sentences,
  scenarios,
  instructions,
  setSelectionDirty,
  setTypesDirty,
  selectionKey,
}: {
  selectionKey: readonly unknown[]
  passages: PassageWithSentences[]
  sentences: SentenceWithPassage[]
  scenarios: ScenarioOut[]
  instructions: InstructionPublic[]
  setSelectionDirty: (
    next: LessonSelection | ((prev: LessonSelection) => LessonSelection),
  ) => void
  setTypesDirty: (
    next: LessonTypes | ((prev: LessonTypes) => LessonTypes),
  ) => void
}) {
  const queryClient = useQueryClient()
  // 题库批量导入「带入组卷」：一次性预选本批新建题目。分两步防「旧缓存
  // 丢预选」（评审 P2）：① 挂载发现交接键 → 刷新分页目录与所选题目详情
  // （staleTime 内的旧缓存不含刚导入的新题，直接消费会把新题过滤掉
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
        queryClient.invalidateQueries({ queryKey: selectionKey }),
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
    const allFresh =
      (queryClient.getQueryState(selectionKey)?.dataUpdatedAt ?? 0) > t0

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

  const continuePreset = () => {
    const raw = presetRawRef.current
    if (!raw) return discardPreset()
    try {
      consumePreset(
        JSON.parse(raw) as Parameters<typeof consumePreset>[0],
        new Set(presetMissing),
      )
    } catch {
      discardPreset()
    }
  }
  return {
    presetWaiting,
    presetMissing,
    presetBlocked,
    continuePreset,
    discardPreset,
  }
}
