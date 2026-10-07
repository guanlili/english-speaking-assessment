/** 老题单缺少作答秒数时沿用原有 60 秒兜底；题库允许的最长考试回答为 300 秒。 */
export const DEFAULT_RECORD_SECONDS = 60
export const MAX_RECORD_SECONDS = 300

export function resolveRecordLimitSeconds(
  seconds: number | null | undefined,
): number {
  if (
    seconds === null ||
    seconds === undefined ||
    !Number.isFinite(seconds) ||
    seconds < 1
  ) {
    return DEFAULT_RECORD_SECONDS
  }
  return Math.min(Math.floor(seconds), MAX_RECORD_SECONDS)
}
