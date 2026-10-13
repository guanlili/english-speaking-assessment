import { readFile } from "node:fs/promises"
import { expect, type Page, test } from "@playwright/test"
import { wav } from "./utils/audio"

async function mockTeacher(
  page: Page,
  width = 820,
  failInitially = false,
  host = false,
) {
  await page.setViewportSize({ width, height: 900 })
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "test-token")
    localStorage.setItem("esa:role", "teacher")
  })
  const state = { fail: failInitially, requests: 0 }
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith("/audio")) {
      state.requests++
      expect(route.request().headers().authorization).toBe("Bearer test-token")
      await route.fulfill(
        state.fail
          ? { status: 503 }
          : { contentType: "audio/wav", body: wav() },
      )
      return
    }
    const item = {
      item_id: "question",
      type: "question",
      status: "done",
      overall: 80,
      attempt_id: "saved-attempt",
    }
    let body: unknown = []
    if (path.endsWith("/users/me"))
      body = { id: "teacher", role: "teacher", is_active: true }
    else if (path.endsWith("/board"))
      body = {
        classroom_code: "PLAY",
        classroom_name: "Playback class",
        class_size: 10,
        submitted_count: 1,
        completed_count: 1,
        pending_count: 0,
        engine: "ark",
        items: [item],
        students: [
          {
            student_id: "student",
            display_name: "Alice",
            done_count: 1,
            total_count: 1,
            has_pending: false,
            round_status: "all_done",
            items: [item],
          },
        ],
      }
    else if (path.endsWith("/attempts/saved-attempt"))
      body = {
        id: "saved-attempt",
        item_type: "question",
        item_id: "question",
        status: "done",
        overall: 80,
        engine: "ark",
        duration_s: 4,
        item_text: "Saved question",
        advice: ["Saved rule advice"],
      }
    await route.fulfill({ json: body })
  })
  if (host) {
    await page.goto("http://127.0.0.1:5176")
    return state
  }
  await page.goto("/t/PLAY")
  await page.getByRole("tab", { name: "学生结果", exact: true }).click()
  await page
    .getByRole("button", { name: "展开 Alice 的详情", exact: true })
    .click()
  return state
}

test("@webkit simultaneous players own separate live audio URLs", async ({
  page,
}) => {
  const state = await mockTeacher(page, 820, false, true)
  const original = page.getByTestId("primary-player").locator("audio")
  await expect(original).toHaveAttribute("src", /^blob:/)
  const firstUrl = await original.getAttribute("src")
  await page
    .getByRole("button", { name: "Mount second player", exact: true })
    .click()
  const second = page.getByTestId("second-player").locator("audio")
  await expect(second).toHaveAttribute("src", /^blob:/)
  const secondUrl = await second.getAttribute("src")
  expect(secondUrl).not.toBe(firstUrl)
  // Both genuine AttemptAudio instances share one QueryClient and cached Blob.
  expect(state.requests).toBe(1)
  await page
    .getByRole("button", { name: "Unmount second player", exact: true })
    .click()
  expect(
    await original.evaluate(
      async (audio: HTMLAudioElement) => (await fetch(audio.src)).ok,
    ),
  ).toBe(true)
  expect(
    await page.evaluate(async (url) => {
      try {
        await fetch(url!)
        return false
      } catch {
        return true
      }
    }, secondUrl),
  ).toBe(true)
  await page
    .getByTestId("primary-player")
    .getByRole("button", { name: "播放录音", exact: true })
    .click()
  await expect
    .poll(() =>
      original.evaluate((audio: HTMLAudioElement) => audio.currentTime),
    )
    .toBeGreaterThan(0)
})

for (const width of [390, 820, 1180]) {
  test(`@webkit first click plays an audible recording and keeps timeline at ${width}px`, async ({
    page,
  }) => {
    await mockTeacher(page, width)
    await page.getByRole("button", { name: "详细反馈", exact: true }).click()
    const dialog = page.getByRole("dialog")
    const audio = dialog.locator("audio")
    const progress = dialog.getByRole("slider", { name: "录音播放进度" })
    await expect(progress).toBeVisible()
    await expect(progress).toBeEnabled()
    await dialog.getByRole("button", { name: "播放录音", exact: true }).click()
    await expect
      .poll(() =>
        audio.evaluate((element: HTMLAudioElement) => element.currentTime),
      )
      .toBeGreaterThan(0)
    await expect
      .poll(() => progress.inputValue().then(Number))
      .toBeGreaterThan(0)
    expect(
      await audio.evaluate((element: HTMLAudioElement) => ({
        muted: element.muted,
        volume: element.volume,
        error: element.error?.code,
      })),
    ).toEqual({ muted: false, volume: 1, error: undefined })
    // Measure decoded non-silent samples, rather than only a moving timer.
    const energy = await audio.evaluate(async (element: HTMLAudioElement) => {
      const context = new AudioContext()
      const source = context.createMediaElementSource(element)
      const analyser = context.createAnalyser()
      source.connect(analyser)
      analyser.connect(context.destination)
      await context.resume()
      let peak = 0
      for (let count = 0; count < 30 && peak <= 0.001; count++) {
        await new Promise((resolve) => setTimeout(resolve, 30))
        const samples = new Float32Array(analyser.fftSize)
        analyser.getFloatTimeDomainData(samples)
        peak = Math.max(...samples.map(Math.abs))
      }
      await context.close()
      return peak
    })
    expect(energy).toBeGreaterThan(0.001)
    await dialog.getByRole("button", { name: "暂停录音", exact: true }).click()
    await expect(progress).toBeVisible()
    await progress.fill("2")
    await expect
      .poll(() =>
        audio.evaluate((element: HTMLAudioElement) => element.currentTime),
      )
      .toBeGreaterThanOrEqual(1.9)
    expect((await progress.boundingBox())?.height).toBeGreaterThanOrEqual(44)
    if (width === 390)
      await page.screenshot({ path: "/tmp/attempt-audio-390.png" })
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true)
  })
}

test("@webkit reopening plays on the first click", async ({ page }) => {
  const state = await mockTeacher(page)
  await page.getByRole("button", { name: "详细反馈", exact: true }).click()
  const dialog = page.getByRole("dialog")
  const firstUrl = await dialog.locator("audio").getAttribute("src")
  await expect(
    dialog.getByRole("button", { name: "播放录音", exact: true }),
  ).toBeEnabled()
  await page.getByRole("button", { name: "关闭", exact: true }).click()
  await page.getByRole("button", { name: "详细反馈", exact: true }).click()
  await expect(
    dialog.getByRole("button", { name: "播放录音", exact: true }),
  ).toBeEnabled()
  expect(await dialog.locator("audio").getAttribute("src")).not.toBe(firstUrl)
  await dialog.getByRole("button", { name: "播放录音", exact: true }).click()
  await expect
    .poll(() =>
      dialog
        .locator("audio")
        .evaluate((element: HTMLAudioElement) => element.currentTime),
    )
    .toBeGreaterThan(0)
  expect(state.requests).toBeGreaterThan(0)
})

test("@webkit audio download failures recover with reload", async ({
  page,
}) => {
  const state = await mockTeacher(page, 820, true)
  await page.getByRole("button", { name: "详细反馈", exact: true }).click()
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByRole("alert")).toContainText("录音加载失败")
  state.fail = false
  await dialog
    .getByRole("button", { name: "重新加载录音", exact: true })
    .click()
  await expect(
    dialog.getByRole("button", { name: "播放录音", exact: true }),
  ).toBeEnabled()
  await dialog.getByRole("button", { name: "播放录音", exact: true }).click()
  await expect
    .poll(() =>
      dialog
        .locator("audio")
        .evaluate((element: HTMLAudioElement) => element.currentTime),
    )
    .toBeGreaterThan(0)
})

test("@webkit timeline remains usable when container duration is missing", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(HTMLMediaElement.prototype, "duration", {
      configurable: true,
      get() {
        return Infinity
      },
    })
  })
  await mockTeacher(page, 820, false, true)
  // No supplied duration: decode the bytes, without seeking.
  const progress = page.getByRole("slider", { name: "录音播放进度" })
  await expect(progress).toBeEnabled()
  await expect
    .poll(async () => Number(await progress.getAttribute("max")))
    .toBeCloseTo(4, 2)
  expect(
    await page
      .locator("audio")
      .evaluate((element: HTMLAudioElement) => element.currentTime),
  ).toBe(0)
  await page.getByRole("button", { name: "播放录音", exact: true }).click()
  await expect.poll(() => progress.inputValue().then(Number)).toBeGreaterThan(0)
})

for (const forceFallback of [false, true]) {
  test(`@webkit recorded audio starts without seeking (fixture fallback: ${forceFallback})`, async ({
    page,
  }) => {
    if (forceFallback)
      await page.addInitScript(() => {
        Object.defineProperty(window, "MediaRecorder", {
          value: undefined,
          configurable: true,
        })
      })
    await mockTeacher(page, 820, false, true)
    const canRecord = await page.evaluate(
      () => typeof MediaRecorder !== "undefined",
    )
    // Linux WebKit may decode recordings but cannot create them. Exercise playback regardless.
    const recording = canRecord
      ? await page.evaluate(async () => {
          const context = new AudioContext()
          await context.resume()
          const oscillator = context.createOscillator()
          const destination = context.createMediaStreamDestination()
          oscillator.connect(destination)
          oscillator.start()
          const mimeType = ["audio/webm;codecs=opus", "audio/mp4"].find(
            (mime) => MediaRecorder.isTypeSupported(mime),
          )
          const recorder = new MediaRecorder(
            destination.stream,
            mimeType ? { mimeType } : undefined,
          )
          const chunks: Blob[] = []
          const finished = new Promise<Blob>((resolve) => {
            recorder.ondataavailable = (event) => chunks.push(event.data)
            recorder.onstop = () =>
              resolve(new Blob(chunks, { type: recorder.mimeType }))
          })
          recorder.start(100)
          await new Promise((resolve) => setTimeout(resolve, 1500))
          recorder.stop()
          const blob = await finished
          oscillator.stop()
          destination.stream.getTracks().forEach((track) => {
            track.stop()
          })
          await context.close()
          return {
            bytes: Array.from(new Uint8Array(await blob.arrayBuffer())),
            mime: blob.type,
          }
        })
      : {
          bytes: await readFile(
            new URL("../fixtures/recorded-tone.wav", import.meta.url),
          ),
          mime: "audio/wav",
        }
    await page.route("**/attempts/saved-attempt/audio", (route) =>
      route.fulfill({
        contentType: recording.mime,
        body: Buffer.from(recording.bytes),
      }),
    )
    // Reload creates a fresh QueryClient, so the recording replaces the initial WAV.
    await page.reload()
    await expect(
      page.getByRole("button", { name: "播放录音", exact: true }),
    ).toBeEnabled()
    const audio = page.locator("audio")
    expect(
      await audio.evaluate((element: HTMLAudioElement) => element.currentTime),
    ).toBe(0)
    // End-to-end clock checks run muted so parallel headless WebKit pages do
    // not contend for the system audio device; audibility is measured above.
    await audio.evaluate((element: HTMLAudioElement) => {
      element.muted = true
    })
    await page.getByRole("button", { name: "播放录音", exact: true }).click()
    await expect
      .poll(() =>
        audio.evaluate((element: HTMLAudioElement) => element.currentTime),
      )
      .toBeGreaterThan(0)
    await expect
      .poll(
        () => audio.evaluate((element: HTMLAudioElement) => element.ended),
        { timeout: 10000 },
      )
      .toBe(true)
    await page.getByRole("button", { name: "播放录音", exact: true }).click()
    await expect
      .poll(() =>
        audio.evaluate((element: HTMLAudioElement) => element.currentTime),
      )
      .toBeGreaterThan(0)
    await expect(
      page.getByRole("slider", { name: "录音播放进度" }),
    ).toBeEnabled()
    await expect
      .poll(() => page.getByRole("slider").inputValue().then(Number))
      .toBeGreaterThan(0)
  })
}

test("@webkit rejected playback shows a retry without pretending to play", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const play = HTMLMediaElement.prototype.play
    HTMLMediaElement.prototype.play = function () {
      if (!(window as unknown as { allowPlay?: boolean }).allowPlay) {
        return Promise.reject(
          new DOMException("Playback blocked", "NotAllowedError"),
        )
      }
      return play.call(this)
    }
  })
  await mockTeacher(page, 820, false, true)
  const button = page.getByRole("button", { name: "播放录音", exact: true })
  await expect(button).toBeEnabled()
  await button.click()
  await expect(page.getByRole("alert")).toContainText("录音播放失败")
  await expect(button).toHaveAttribute("aria-pressed", "false")
  await page.evaluate(() => {
    ;(window as unknown as { allowPlay?: boolean }).allowPlay = true
  })
  await button.click()
  await expect
    .poll(() =>
      page
        .locator("audio")
        .evaluate((element: HTMLAudioElement) => element.currentTime),
    )
    .toBeGreaterThan(0)
  await expect(
    page.getByRole("button", { name: "暂停录音", exact: true }),
  ).toHaveAttribute("aria-pressed", "true")
})
