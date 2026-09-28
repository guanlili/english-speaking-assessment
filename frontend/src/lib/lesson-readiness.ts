import type { ScenarioOut, SentenceWithPassage } from "../client/types.gen"

export interface LessonTypes {
  reading: boolean
  repeat: boolean
  qa: boolean
}

export interface LessonSelection {
  passages: string[]
  sentences: string[]
  scenarioId: string | null
}

export interface LessonData {
  sentences: SentenceWithPassage[]
  scenarios: ScenarioOut[]
}

/** 按题选题的发布校验：三种题型互相独立，勾选了哪类就要求选中该类内容。 */
export function inspectSelection(
  types: LessonTypes,
  picked: LessonSelection,
  data: LessonData,
) {
  const scenario = picked.scenarioId
    ? data.scenarios.find((s) => s.id === picked.scenarioId)
    : undefined
  const problems: string[] = []
  if (!types.reading && !types.repeat && !types.qa)
    problems.push("至少选择一种题型。")
  if (types.reading && picked.passages.length === 0)
    problems.push("勾选了文章朗读，请在题目库的朗读篇目里选择内容。")
  if (types.repeat && picked.sentences.length === 0)
    problems.push("勾选了听句复述，请选择要发布的复述句。")
  if (types.qa && (!scenario || scenario.questions.length === 0))
    problems.push("勾选了模拟问答，请选择一个有题目的问答主题。")
  return { scenario, problems }
}
