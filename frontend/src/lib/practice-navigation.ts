/** 从当前题之后寻找未完成题；后面都完成时回头找前面的未完成题。 */
export function nextUnansweredIndex(
  itemIds: string[],
  currentIndex: number,
  completedIds: ReadonlySet<string>,
): number {
  for (let offset = 1; offset < itemIds.length; offset++) {
    const index = (currentIndex + offset) % itemIds.length
    if (!completedIds.has(itemIds[index])) return index
  }
  return -1
}
