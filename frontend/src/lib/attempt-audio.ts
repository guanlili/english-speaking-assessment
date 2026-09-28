const API_BASE = import.meta.env.VITE_API_URL ?? ""

/**
 * 录音回放（学生/教师统一 JWT）：token 只能走 Authorization 头
 * （不进 URL、不进访问日志），先取回字节再交给 <audio>。
 */
export function attemptAudioUrl(attemptId: string): string {
  return `${API_BASE}/api/v1/attempts/${attemptId}/audio`
}

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
