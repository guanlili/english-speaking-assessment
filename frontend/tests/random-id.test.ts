import assert from "node:assert/strict"
import test from "node:test"
import { randomId } from "../src/lib/random-id.ts"

// RFC 4122 v4：版本位固定 4，变体位固定 8/9/a/b
const UUID_V4 =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

const withCrypto = (value: unknown, fn: () => void) => {
  const original = globalThis.crypto
  Object.defineProperty(globalThis, "crypto", { configurable: true, value })
  try {
    fn()
  } finally {
    Object.defineProperty(globalThis, "crypto", {
      configurable: true,
      value: original,
    })
  }
}

test("randomId returns RFC 4122 v4 UUIDs", () => {
  for (let i = 0; i < 100; i += 1) {
    assert.match(randomId(), UUID_V4)
  }
  assert.notEqual(randomId(), randomId())
})

test("randomId stays a valid UUID when crypto.randomUUID is unavailable (HTTP deployment)", () => {
  // 安全上下文不成立时 randomUUID 是 undefined，但 getRandomValues 仍可用
  withCrypto(
    {
      getRandomValues: (bytes: Uint8Array) => {
        for (let i = 0; i < bytes.length; i += 1) bytes[i] = (i * 37 + 11) % 256
        return bytes
      },
    },
    () => assert.match(randomId(), UUID_V4),
  )
})

test("randomId stays a valid UUID without any Web Crypto (legacy fallback)", () => {
  withCrypto(undefined, () => assert.match(randomId(), UUID_V4))
})
