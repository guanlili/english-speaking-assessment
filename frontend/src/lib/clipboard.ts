/** 统一剪贴板写入：成功返回 true；失败记录日志并返回 false，提示交给调用方。 */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch (err) {
    console.error("Failed to copy to clipboard:", err)
    return false
  }
}
