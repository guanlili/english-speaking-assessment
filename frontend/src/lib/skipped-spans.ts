/** 按朗读顺序对齐转写，标出参考文本里被跳过的连续片段。 */

const TOKEN = /[a-z']+/g

export function tokenizeEnglish(text: string): string[] {
  return text.toLowerCase().match(TOKEN) ?? []
}

/** 转写为空时不标片段（静音建议另走）。最多 3 段，每段最多 8 个词。 */
export function skippedSpans(reference: string, transcript: string): string[] {
  const spoken = tokenizeEnglish(transcript)
  if (spoken.length === 0) return []
  const referenceTokens = tokenizeEnglish(reference)
  let cursor = 0
  let current: string[] = []
  const spans: string[][] = []
  const push = () => {
    if (current.length > 0) spans.push(current)
    current = []
  }
  for (const word of referenceTokens) {
    let found = -1
    for (let index = cursor; index < spoken.length; index += 1) {
      if (spoken[index] === word) {
        found = index
        break
      }
    }
    if (found === -1) {
      current.push(word)
      continue
    }
    push()
    cursor = found + 1
  }
  push()
  return spans.slice(0, 3).map((span) => span.slice(0, 8).join(" "))
}
