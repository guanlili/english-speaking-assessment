import { expect, test } from "@playwright/test"

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    class Recorder {
      static isTypeSupported() {
        return true
      }
      mimeType = "audio/webm"
      state = "inactive"
      onstart: (() => void) | null = null
      onstop: (() => void) | null = null
      ondataavailable: ((event: { data: Blob }) => void) | null = null
      start() {
        this.state = "recording"
        ;(window as unknown as { recorders: Recorder[] }).recorders.push(this)
      }
      stop() {
        this.state = "inactive"
        queueMicrotask(() => this.onstop?.())
      }
      chunk(text: string) {
        this.ondataavailable?.({ data: new Blob([text]) })
      }
    }
    Object.assign(window, {
      recorders: [],
      trackListeners: 0,
      MediaRecorder: Recorder,
    })
    Object.defineProperty(navigator, "mediaDevices", {
      value: {
        getUserMedia: async () => {
          const counters = window as unknown as { trackListeners: number }
          const track = {
            readyState: "live",
            stop() {
              this.readyState = "ended"
            },
            addEventListener() {
              counters.trackListeners++
            },
            removeEventListener() {
              counters.trackListeners--
            },
          }
          return { getAudioTracks: () => [track], getTracks: () => [track] }
        },
      },
      configurable: true,
    })
  })
  await page.goto("http://127.0.0.1:5176/?recorder")
})

test("@webkit timed out recorder cannot announce a late start", async ({
  page,
}) => {
  await page.clock.install()
  await page.getByRole("button", { name: "Start", exact: true }).click()
  await page.waitForFunction(
    () =>
      (window as unknown as { recorders: unknown[] }).recorders.length === 1,
  )
  await page.clock.runFor(10_100)
  await expect(page.getByRole("alert")).not.toBeEmpty()
  await page.evaluate(() => {
    const recorder = (
      window as unknown as { recorders: Array<{ onstart: () => void }> }
    ).recorders[0]
    recorder.onstart()
  })
  await expect(page.getByTestId("status")).toHaveText("idle")
  await expect(page.getByTestId("starts")).toHaveText("0")
})

test("@webkit stale data after reset cannot contaminate the new recording", async ({
  page,
}) => {
  await page.clock.install()
  const start = page.getByRole("button", { name: "Start", exact: true })
  await start.click()
  await page.waitForFunction(
    () =>
      (window as unknown as { recorders: unknown[] }).recorders.length === 1,
  )
  await page.evaluate(() =>
    (
      window as unknown as { recorders: Array<{ onstart: () => void }> }
    ).recorders[0].onstart(),
  )
  await page.getByRole("button", { name: "Reset", exact: true }).click()
  await start.click()
  await page.waitForFunction(
    () =>
      (window as unknown as { recorders: unknown[] }).recorders.length === 2,
  )
  await page.evaluate(() => {
    const recorders = (
      window as unknown as {
        recorders: Array<{ onstart: () => void; chunk: (text: string) => void }>
      }
    ).recorders
    recorders[1].onstart()
    recorders[1].chunk("new")
    recorders[0].chunk("OLD")
  })
  await page.clock.runFor(1_100)
  await page.getByRole("button", { name: "Stop", exact: true }).click()
  await expect(page.getByTestId("result")).toHaveText("new")
  expect(
    await page.evaluate(
      () => (window as unknown as { trackListeners: number }).trackListeners,
    ),
  ).toBe(0)
})
