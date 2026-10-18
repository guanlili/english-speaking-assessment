/** Local UI hint only; never renews the server's device-check timestamp. */
export const DEVICE_CHECK_TTL_MS = 2 * 60 * 60 * 1000

type DeviceCheckStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">

export function deviceCheckKey(
  userId: string | null | undefined,
  studentId: string | null | undefined,
  code: string,
): string | null {
  return userId && studentId && code
    ? `esa:device-check:${JSON.stringify([userId, studentId, code.toUpperCase()])}`
    : null
}

export function readDeviceCheck(
  key: string | null,
  now = Date.now(),
  storage?: DeviceCheckStorage,
): number | null {
  if (!key) return null
  try {
    const target = storage ?? window.sessionStorage
    const raw = target.getItem(key)
    const checkedAt = raw === null ? Number.NaN : Number(raw)
    if (
      Number.isFinite(checkedAt) &&
      checkedAt > 0 &&
      checkedAt <= now &&
      now - checkedAt < DEVICE_CHECK_TTL_MS
    )
      return checkedAt
    target.removeItem(key)
  } catch {
    // Storage unavailable: keep the normal device-check flow usable.
  }
  return null
}

export function saveDeviceCheck(
  key: string | null,
  checkedAt: number,
  storage?: DeviceCheckStorage,
): void {
  if (!key) return
  try {
    ;(storage ?? window.sessionStorage).setItem(key, String(checkedAt))
  } catch {
    // Remembering a check is optional; a passed test still remains passed here.
  }
}

export function clearDeviceCheck(
  key: string | null,
  storage?: DeviceCheckStorage,
): void {
  if (!key) return
  try {
    ;(storage ?? window.sessionStorage).removeItem(key)
  } catch {
    // The current page still requires a new check when storage is unavailable.
  }
}
