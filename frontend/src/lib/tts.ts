/**
 * 浏览器 TTS 播放（英文）。
 *
 * 各页面"听示范/朗读/测试扬声器"的公共部分收敛于此：
 * 取消在播语音 → 构造英文 utterance（可选语速、英文声音）→ speak。
 * 返回 utterance 供调用方继续挂回调；不支持合成时返回 null。
 */
export function speakEnglish(
  text: string,
  opts: { rate?: number; onEnd?: () => void; onError?: () => void } = {},
): SpeechSynthesisUtterance | null {
  const synth = window.speechSynthesis
  if (!synth) return null
  synth.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = "en-US"
  if (opts.rate !== undefined) utterance.rate = opts.rate
  const voice = synth.getVoices().find((v) => v.lang.startsWith("en"))
  if (voice) utterance.voice = voice
  if (opts.onEnd) utterance.onend = () => opts.onEnd?.()
  if (opts.onError) utterance.onerror = () => opts.onError?.()
  synth.speak(utterance)
  return utterance
}

/** 示范语速选项（朗读与复述的"听示范"共用，保证两端一致）。 */
export const TTS_RATE_OPTIONS = [
  { value: "0.5", label: "最慢 0.5×" },
  { value: "0.8", label: "慢速 0.8×" },
  { value: "1", label: "正常 1.0×" },
] as const
