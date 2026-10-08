import type {
  InstructionPublic,
  ScenarioOut,
  SentenceWithPassage,
} from "../client/types.gen"
import type { BiString } from "./bi.ts"

export interface LessonTypes {
  reading: boolean
  repeat: boolean
  qa: boolean
  /** 题目说明（第四题型）：可穿插在题与题之间的引导页 */
  instruction: boolean
}

export interface LessonSelection {
  passages: string[]
  sentences: string[]
  scenarioIds: string[]
  /** 选中的题目说明 id */
  instructions: string[]
}

export interface LessonData {
  sentences: SentenceWithPassage[]
  scenarios: ScenarioOut[]
  instructions: InstructionPublic[]
}

/** 按题选题的发布校验：各题型互相独立，勾选了哪类就要求选中该类内容。
 *  题目说明无作答、不能单独成卷；问题列表为 BiString，渲染端用 useI18n().t() 取当前语言。 */
export function inspectSelection(
  types: LessonTypes,
  picked: LessonSelection,
  data: LessonData,
) {
  const scenarios = picked.scenarioIds.map((id) =>
    data.scenarios.find((scenario) => scenario.id === id),
  )
  const problems: BiString[] = []
  if (!types.reading && !types.repeat && !types.qa)
    problems.push({
      zh: "至少选择一种可作答的题型（题目说明不能单独作为练习内容）。",
      en: "Select at least one answerable question type — instructions alone can't form a lesson.",
    })
  if (types.reading && picked.passages.length === 0)
    problems.push({
      zh: "勾选了文章朗读，请在题目库的朗读篇目里选择内容。",
      en: "Read Aloud is checked — pick passages in the Question Bank.",
    })
  if (types.repeat && picked.sentences.length === 0)
    problems.push({
      zh: "勾选了听句复述，请选择要发布的复述句。",
      en: "Listen & Repeat is checked — select sentences to publish.",
    })
  if (
    types.qa &&
    (scenarios.length === 0 ||
      scenarios.some(
        (scenario) => !scenario?.is_active || scenario.questions.length === 0,
      ))
  )
    problems.push({
      zh: "勾选了情景问答，请选择至少一个启用且有题目的问答主题。",
      en: "Scenario Q&A is checked — pick at least one active topic with questions.",
    })
  if (types.instruction && picked.instructions.length === 0)
    problems.push({
      zh: "勾选了题目说明，请选择或新建一条说明文字。",
      en: "Instructions are checked — pick or create an instruction text.",
    })
  return {
    scenarios: scenarios.filter((scenario) => scenario !== undefined),
    problems,
  }
}
