/**
 * 本地时区日期串 YYYY-MM-DD（导出文件名用）。
 *
 * 此前多处用 `new Date().toISOString().slice(0, 10)`：那是 UTC 日期，
 * 时区晚于 UTC 的地区（西半球）本地日期会差一天，导出的文件名带错日期。
 * 这里取本地年/月/日，纯本地字段拼接，无时区换算。
 */
export function localDateStamp(date: Date = new Date()): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, "0")
  const day = String(date.getDate()).padStart(2, "0")
  return `${year}-${month}-${day}`
}
