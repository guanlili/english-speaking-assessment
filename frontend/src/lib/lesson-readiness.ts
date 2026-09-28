import type { PassageWithSentences, ScenarioOut } from "../client/types.gen"

export interface LessonTypes {
  reading: boolean
  repeat: boolean
  qa: boolean
}

/** Mirrors the current classroom delivery contract: assigned rounds carry every
 * active passage of the group (long texts can be split into several reading items). */
export function inspectLesson(
  unitId: string,
  types: LessonTypes,
  passages: PassageWithSentences[],
  scenarios: ScenarioOut[],
) {
  const materials = passages.filter(
    (passage) => passage.unit_id === unitId && passage.is_active !== false,
  )
  // 锚点篇（组内第一篇）：承担问答主题配套；朗读题则每篇各自一道
  const passage = materials.length > 0 ? materials[0] : undefined
  const scenario = passage
    ? scenarios.find((item) => item.is_active && item.topic === passage.topic)
    : undefined
  const problems: string[] = []
  if (!unitId) problems.push("请选择一个单元。")
  if (!types.reading && !types.repeat && !types.qa)
    problems.push("至少选择一种题型。")
  if (unitId && !materials.length)
    problems.push("该单元还没有启用的篇目，请先在题目库添加篇目并归入此单元。")
  if (passage && types.repeat && !materials.some((m) => m.sentences?.length))
    problems.push("尚未添加复述句，请到「听句复述」补充。")
  if (passage && types.qa && !scenario?.questions.length)
    problems.push(
      `配套主题「${passage.topic}」还没有问答题，请到「模拟问答」为这个主题添加。`,
    )
  return { passage, materials, scenario, problems }
}
