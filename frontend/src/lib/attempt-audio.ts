const API_BASE = import.meta.env.VITE_API_URL ?? ""

/**
 * 学生回放：把入班凭证放 query（<audio src> 发不出 Authorization 头）。
 * token 是 HMAC 签名 + 过期时间，只对本人有效。
 */
export function attemptAudioUrl(
  attemptId: string,
  studentToken?: string | null,
): string {
  const base = `${API_BASE}/api/v1/attempts/${attemptId}/audio`
  return studentToken
    ? `${base}?token=${encodeURIComponent(studentToken)}`
    : base
}

/**
 * 教师回放：JWT 只能走 Authorization 头（不进 URL、不进访问日志），
 * 所以先取回字节再交给 <audio>，返回 objectURL。
 */
export async function fetchAudioObjectUrl(attemptId: string): Promise<string> {
  // 与 OpenAPI.TOKEN 同源（main.tsx 写入 localStorage），fetch 才能带 Authorization 头
  const token = localStorage.getItem("access_token") || ""
  const res = await fetch(attemptAudioUrl(attemptId), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) {
    throw new Error(`录音加载失败（${res.status}）`)
  }
  return URL.createObjectURL(await res.blob())
}
