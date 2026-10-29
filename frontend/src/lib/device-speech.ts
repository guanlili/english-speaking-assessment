/** 发布预览：哪些题没有标准音，学生端会改用设备合成语音。 */

export type DeviceSpeechItem = {
  type: string
  label: string
  audioUrl?: string | null
}

const LISTENED_TYPES = new Set(["passage", "repeat", "question"])

export function itemsUsingDeviceSpeech(
  items: DeviceSpeechItem[],
): DeviceSpeechItem[] {
  return items.filter((item) => LISTENED_TYPES.has(item.type) && !item.audioUrl)
}

/** 拆成两句及以上时按句检查配音：句子级配音表命中则视为有标准音。 */
export function passageSpeechItems(passage: {
  title: string
  audioUrl?: string | null
  readingSplit?: boolean
  segments?: string[] | null
  sentenceAudio?: Record<string, string> | null
}): DeviceSpeechItem[] {
  const segments =
    passage.readingSplit && (passage.segments?.length ?? 0) >= 2
      ? (passage.segments ?? [])
      : []
  if (segments.length >= 2) {
    return segments.map((sentence) => ({
      type: "passage",
      label: sentence.replace(/\s+/g, " ").trim().slice(0, 60),
      audioUrl: passage.sentenceAudio?.[sentence] ?? null,
    }))
  }
  return [
    {
      type: "passage",
      label: passage.title,
      audioUrl: passage.audioUrl,
    },
  ]
}
