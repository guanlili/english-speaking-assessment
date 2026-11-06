import { useQuery } from "@tanstack/react-query"
import {
  type AssignmentInfo,
  type AssignmentItemIn,
  ClassesService,
  type ClassroomExercisePublic,
} from "@/client"
import { Button } from "@/components/ui/button"
import { useComposerLibrary } from "@/hooks/useComposerLibrary"
import { useI18n } from "@/lib/i18n"
import type { LessonSelection, LessonTypes } from "@/lib/lesson-readiness"
import { COMPOSER_PRESET_KEY } from "@/lib/questionImport"
import { normalizeReadingSelection } from "@/lib/reading-selection"
import { ComposerForm } from "./AssignmentComposer/ComposerForm"

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
  const draftQuery = useQuery({
    queryKey: ["teacher", "composer-draft", code],
    queryFn: () => ClassesService.readComposerDraft({ code }),
    refetchOnWindowFocus: false,
    retry: 1,
  })
  const draft = draftQuery.data?.state ? draftQuery.data : null
  const draftRefs = draft
    ? [
        ...draft.state.selection.passages.map((id) => ({
          type: "passage",
          id,
        })),
        ...draft.state.selection.sentences.map((id) => ({
          type: "repeat",
          id,
        })),
        ...draft.state.selection.scenarioIds.map((id) => ({
          type: "scenario",
          id,
        })),
        ...draft.state.selection.questions.map((id) => ({
          type: "question",
          id,
        })),
        ...draft.state.selection.instructions.map((id) => ({
          type: "instruction",
          id,
        })),
      ]
    : []
  const library = useComposerLibrary([...(assignedItems ?? []), ...draftRefs])
  const exercisesQuery = useQuery({
    queryKey: ["teacher", "exercises", code],
    queryFn: () => ClassesService.listClassroomExercises({ code }),
  })

  if (library.failed || draftQuery.isError)
    return (
      <div className="space-y-3 rounded-2xl border p-6">
        <p>
          {t({
            zh: "练习内容加载失败。",
            en: "Failed to load practice content.",
          })}
        </p>
        <Button
          variant="outline"
          onClick={() => {
            library.retry()
            void draftQuery.refetch()
          }}
        >
          {t({ zh: "重新加载", en: "Reload" })}
        </Button>
      </div>
    )
  if (library.pending || draftQuery.isPending)
    return (
      <p className="rounded-2xl border p-6 text-muted-foreground">
        {t({
          zh: sessionStorage.getItem(COMPOSER_PRESET_KEY)
            ? "正在刷新题库并带入本批题目…（网络较慢时请稍候）"
            : "正在加载可用练习…",
          en: sessionStorage.getItem(COMPOSER_PRESET_KEY)
            ? "Refreshing the question bank and pre-selecting this batch… (may take a moment on slow networks)"
            : "Loading available practice…",
        })}
      </p>
    )
  const { passages, sentences, scenarios, instructions } = library.data

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
      key={code}
      library={library}
      draft={draft}
      draftAvailable={!draftQuery.isError}
      currentExerciseId={currentExercise?.id ?? null}
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
