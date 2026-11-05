/**
 * 生成 UUID v4 字符串（服务端 request_id / 幂等键都是 UUID 类型）。
 *
 * crypto.randomUUID 只在安全上下文（HTTPS / localhost）可用；纯 HTTP 部署
 * （内网、本地调试、反向代理漏配 TLS）下它是 undefined。以前的降级值是
 * `Date.now().toString(36)-随机串`，不是合法 UUID，提交时会直接 422。
 * getRandomValues 不受安全上下文限制，用它按 RFC 4122 拼 v4。
 */
export function randomId(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID()
  }
  const bytes = new Uint8Array(16)
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.getRandomValues === "function"
  ) {
    crypto.getRandomValues(bytes)
  } else {
    // 极端兜底（无 Web Crypto 的旧环境）：Math.random 不加密安全，但格式合法
    for (let i = 0; i < bytes.length; i += 1) {
      bytes[i] = Math.floor(Math.random() * 256)
    }
  }
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40 // version 4
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80 // variant 10xx
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20),
  ].join("-")
}
