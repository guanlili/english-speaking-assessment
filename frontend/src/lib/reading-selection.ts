import type {
  AssignmentItemIn,
  PassageWithSentences,
} from "../client/types.gen"

/** 旧版分段题在重新组卷时归回原文章；已发布快照不改变。 */
export function normalizeReadingSelection(
  items: AssignmentItemIn[],
  passages: Pick<PassageWithSentences, "id" | "reading_child_ids">[],
): AssignmentItemIn[] {
  const parents = new Map(
    passages.flatMap((passage) =>
      (passage.reading_child_ids ?? []).map(
        (childId) => [childId, passage.id] as const,
      ),
    ),
  )
  const seen = new Set<string>()
  return items.flatMap((item) => {
    if (item.type !== "passage") return [item]
    const id = parents.get(item.id) ?? item.id
    if (seen.has(id)) return []
    seen.add(id)
    return [{ ...item, id }]
  })
}
