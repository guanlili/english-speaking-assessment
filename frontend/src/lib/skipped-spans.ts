/** 按朗读顺序对齐转写，标出参考文本里被跳过的连续片段。 */

function normalizeForAlignment(text: string): string {
  return text.replace(/[’‘]/g, "'").replace(/[“”]/g, '"').toLowerCase()
}

/** 只用于漏词展示。词内撇号保留，包围引号不进词。不参与评分。 */
export function tokenizeEnglish(text: string): string[] {
  return normalizeForAlignment(text).match(/[a-z]+(?:'[a-z]+)*/g) ?? []
}

function alignReference(reference: string[], spoken: string[]): boolean[] {
  const rows = reference.length
  const cols = spoken.length
  const cost: number[][] = Array.from({ length: rows + 1 }, () =>
    Array<number>(cols + 1).fill(0),
  )
  for (let i = 0; i <= rows; i += 1) cost[i][0] = i
  for (let j = 0; j <= cols; j += 1) cost[0][j] = j
  for (let i = 1; i <= rows; i += 1) {
    for (let j = 1; j <= cols; j += 1) {
      const match =
        cost[i - 1][j - 1] + (reference[i - 1] === spoken[j - 1] ? 0 : 2)
      cost[i][j] = Math.min(match, cost[i - 1][j] + 1, cost[i][j - 1] + 1)
    }
  }
  const matched = Array<boolean>(rows).fill(false)
  let i = rows
  let j = cols
  while (i > 0 && j > 0) {
    const same = reference[i - 1] === spoken[j - 1]
    if (cost[i][j] === cost[i - 1][j - 1] + (same ? 0 : 2)) {
      if (same) matched[i - 1] = true
      i -= 1
      j -= 1
    } else if (cost[i][j] === cost[i - 1][j] + 1) {
      i -= 1
    } else {
      j -= 1
    }
  }
  return matched
}

/** 转写为空时不标片段（静音建议另走）。最多 3 段，每段最多 8 个词。 */
export function skippedSpans(reference: string, transcript: string): string[] {
  const spoken = tokenizeEnglish(transcript)
  if (spoken.length === 0) return []
  const referenceTokens = tokenizeEnglish(reference)
  const matched = alignReference(referenceTokens, spoken)
  const spans: string[][] = []
  let current: string[] = []
  for (let index = 0; index < referenceTokens.length; index += 1) {
    if (matched[index]) {
      if (current.length > 0) spans.push(current)
      current = []
    } else {
      current.push(referenceTokens[index])
    }
  }
  if (current.length > 0) spans.push(current)
  return spans.slice(0, 3).map((span) => span.slice(0, 8).join(" "))
}
