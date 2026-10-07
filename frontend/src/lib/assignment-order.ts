import type { AssignmentItemIn } from "@/client"

export function assignmentItemKey(item: AssignmentItemIn): string {
  return `${item.type}:${item.id}`
}

/** 朗读篇目先行；复述句与问答题默认交替出现。 */
export function defaultAssignmentOrder(
  passages: AssignmentItemIn[],
  sentences: AssignmentItemIn[],
  questions: AssignmentItemIn[],
): AssignmentItemIn[] {
  const result = [...passages]
  for (
    let index = 0;
    index < Math.max(sentences.length, questions.length);
    index++
  ) {
    if (sentences[index]) result.push(sentences[index])
    if (questions[index]) result.push(questions[index])
  }
  return result
}

/** 已手动排序的题保留位置；新勾选题按默认顺序补到末尾。 */
export function reconcileAssignmentOrder(
  available: AssignmentItemIn[],
  orderedKeys: string[] | null,
): AssignmentItemIn[] {
  if (orderedKeys === null) return available
  const byKey = new Map(
    available.map((item) => [assignmentItemKey(item), item]),
  )
  const ordered = orderedKeys.flatMap((key) => {
    const item = byKey.get(key)
    if (!item) return []
    byKey.delete(key)
    return [item]
  })
  return [...ordered, ...byKey.values()]
}

export function moveAssignmentItem(
  items: AssignmentItemIn[],
  index: number,
  direction: -1 | 1,
): AssignmentItemIn[] {
  const target = index + direction
  if (target < 0 || target >= items.length) return items
  const result = [...items]
  ;[result[index], result[target]] = [result[target], result[index]]
  return result
}
