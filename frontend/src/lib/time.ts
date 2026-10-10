/** 练习页时间展示的统一格式化（录音计时/作答限时用 m:ss，整场考试用 mm:ss）。 */
export function formatSeconds(seconds: number): string {
  const whole = Math.floor(seconds)
  return `${String(Math.floor(whole / 60)).padStart(1, "0")}:${String(whole % 60).padStart(2, "0")}`
}

export function formatExamCountdown(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60)
  const s = totalSeconds % 60
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
}

/**
 * 日期时间展示的统一入口：跟随界面语言（zh → 2026/10/10 15:30:00，
 * en → 10/10/2026, 3:30:00 PM）。lang 从 useI18n() 取，禁止裸 toLocaleString
 * （浏览器区域设置会让同一页面在不同设备上格式漂移）。
 */
function toDate(value: string | number | Date): Date {
  return value instanceof Date ? value : new Date(value)
}

export function formatDateTime(
  value: string | number | Date,
  lang: "zh" | "en",
): string {
  return toDate(value).toLocaleString(lang === "zh" ? "zh-CN" : "en-US")
}

export function formatDate(
  value: string | number | Date,
  lang: "zh" | "en",
): string {
  return toDate(value).toLocaleDateString(lang === "zh" ? "zh-CN" : "en-US")
}

export function formatTime(
  value: string | number | Date,
  lang: "zh" | "en",
): string {
  return toDate(value).toLocaleTimeString(lang === "zh" ? "zh-CN" : "en-US")
}
