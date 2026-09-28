import type { PassageWithSentences, ScenarioOut } from "../client/types.gen"

export interface LessonTypes {
  reading: boolean
  repeat: boolean
  qa: boolean
}

/** Mirrors the current classroom delivery contract; never guess between multiple passages. */
export function inspectLesson(
  unitId: string,
  types: LessonTypes,
  passages: PassageWithSentences[],
  scenarios: ScenarioOut[],
) {
  const materials = passages.filter(
    (passage) => passage.unit_id === unitId && passage.is_active !== false,
  )
  const passage = materials.length === 1 ? materials[0] : undefined
  const scenario = passage
    ? scenarios.find((item) => item.is_active && item.topic === passage.topic)
    : undefined
  const problems: string[] = []
  if (!unitId) problems.push("请选择一组练习内容。")
  if (!types.reading && !types.repeat && !types.qa)
    problems.push("至少选择一种题型。")
  if (unitId && !materials.length)
    problems.push("这组内容还没有启用的材料，请先在题目库添加并归入此分组。")
  if (materials.length > 1)
    problems.push(
      "这组内容有多篇启用材料，学生端目前只取其中一篇。请整理为每组一篇后再发布。",
    )
  if (passage && types.repeat && !passage.sentences?.length)
    problems.push("尚未添加复述句，请到「听句复述」补充。")
  if (passage && types.qa) {
    const missing = ["A2", "B1", "B2"].filter(
      (band) => !scenario?.questions.some((question) => question.band === band),
    )
    if (missing.length)
      problems.push(
        `配套主题「${passage.topic}」缺少 ${missing.join(" / ")} 问答题。请补齐，确保不同档位学生都有题可答。`,
      )
  }
  return { passage, scenario, problems }
}
