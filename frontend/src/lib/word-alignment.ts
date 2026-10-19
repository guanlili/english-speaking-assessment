/**
 * 词级对齐渲染的纯函数工具。
 *
 * 偏移单位契约：后端对齐偏移按 Unicode 码点（re 的 start/end），JS 的
 * string.slice 按 UTF-16 码元计数，题目含非 BMP 字符（如 🐾）时会错位，
 * 因此间隔/尾部切片统一走码点数组。
 */

/** 按 Unicode 码点切片（非 BMP 字符按 1 个码点计），与后端 re 偏移对齐。 */
export function sliceByCodepoints(
  text: string,
  start: number,
  end?: number,
): string {
  const chars = Array.from(text)
  if (end === undefined) return chars.slice(start).join("")
  return chars.slice(start, end).join("")
}
