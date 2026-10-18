import assert from "node:assert/strict"
import test from "node:test"
import {
  clearDeviceCheck,
  DEVICE_CHECK_TTL_MS,
  deviceCheckKey,
  readDeviceCheck,
  saveDeviceCheck,
} from "../src/lib/device-preflight.ts"

function memoryStorage() {
  const data = new Map<string, string>()
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => {
      data.set(key, value)
    },
    removeItem: (key: string) => {
      data.delete(key)
    },
  }
}
const now = 1800000000000

test("recent checks are scoped to account, student and classroom; timestamps never renew", () => {
  const storage = memoryStorage()
  const key = deviceCheckKey("alice", "student-a", "COACH")
  saveDeviceCheck(key, now, storage)
  assert.equal(
    readDeviceCheck(
      deviceCheckKey("alice", "student-a", "coach"),
      now + 1000,
      storage,
    ),
    now,
  )
  for (const other of [
    deviceCheckKey("bob", "student-a", "COACH"),
    deviceCheckKey("alice", "student-b", "COACH"),
    deviceCheckKey("alice", "student-a", "OTHER"),
  ]) {
    assert.equal(readDeviceCheck(other, now + 1000, storage), null)
  }
  assert.equal(
    readDeviceCheck(key, now + DEVICE_CHECK_TTL_MS - 1, storage),
    now,
  )
  assert.equal(readDeviceCheck(key, now + DEVICE_CHECK_TTL_MS, storage), null)
  assert.equal(storage.getItem(key!), null)
})

test("invalid, future and expired timestamps require a new check", () => {
  const storage = memoryStorage()
  const key = deviceCheckKey("alice", "student-a", "COACH")!
  for (const value of [
    "",
    "corrupt",
    "NaN",
    "Infinity",
    "0",
    "-1",
    String(now + 1),
    String(now - DEVICE_CHECK_TTL_MS),
  ]) {
    storage.setItem(key, value)
    assert.equal(readDeviceCheck(key, now, storage), null)
    assert.equal(storage.getItem(key), null)
  }
})

test("rechecking invalidates a previously passed check", () => {
  const storage = memoryStorage()
  const key = deviceCheckKey("alice", "student-a", "COACH")
  saveDeviceCheck(key, now, storage)
  clearDeviceCheck(key, storage)
  assert.equal(readDeviceCheck(key, now, storage), null)
})

test("missing identity and unavailable storage never prevent device testing", () => {
  const storage = {
    getItem: () => {
      throw new Error("unavailable")
    },
    setItem: () => {
      throw new Error("quota")
    },
    removeItem: () => {
      throw new Error("unavailable")
    },
  }
  assert.equal(deviceCheckKey(null, "student", "COACH"), null)
  assert.equal(deviceCheckKey("user", null, "COACH"), null)
  const key = deviceCheckKey("user", "student", "COACH")
  assert.equal(readDeviceCheck(key, now, storage), null)
  assert.doesNotThrow(() => saveDeviceCheck(key, now, storage))
  assert.doesNotThrow(() => clearDeviceCheck(key, storage))
  assert.equal(readDeviceCheck(null, now, storage), null)
})
