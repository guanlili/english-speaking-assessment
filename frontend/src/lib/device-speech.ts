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
