import { expect, type Page, test } from "@playwright/test"

import { wav } from "./utils/audio"

async function mockBank(page: Page, lang = "zh") {
  await page.addInitScript((lang) => {
    localStorage.setItem("access_token", "test-token")
    localStorage.setItem("esa:role", "teacher")
    localStorage.setItem("esa:lang", lang)
  }, lang)
  const sentence = {
    id: "00000000-0000-4000-8000-000000000002",
    text: "Welcome to our city",
    suggested_seconds: 10,
    order_index: 0,
    replay_limit: 1,
    audio_url: null as string | null,
  }
  const article = {
    id: "00000000-0000-4000-8000-000000000001",
    slug: "our-city",
    title: "Our city",
    text: sentence.text,
    cefr_band: "B1",
    topic: "City",
    is_active: true,
    suggested_seconds: 45,
    audio_url: "/api/v1/audio/content/article.wav",
    sentences: [sentence],
  }
  let generation = 0
  let failAudio = false
  const requests: string[] = []
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path.includes("/audio/content/")) {
      requests.push(path)
      await route.fulfill(
        failAudio ? { status: 404 } : { contentType: "audio/wav", body: wav() },
      )
      return
    }
    if (path.endsWith("/users/me"))
      body = {
        id: "teacher",
        email: "teacher@example.com",
        role: "teacher",
        is_active: true,
        is_superuser: true,
      }
    else if (path.endsWith("/admin/passages")) body = [article]
    else if (path.endsWith("/admin/audio/tts")) {
      generation++
      body = { audio_url: `/api/v1/audio/content/generated-${generation}.wav` }
    } else if (path.endsWith("/admin/audio/upload"))
      body = { audio_url: "/api/v1/audio/content/uploaded.wav" }
    else if (path.endsWith(`/admin/sentences/${sentence.id}`)) {
      Object.assign(sentence, route.request().postDataJSON())
      body = sentence
    }
    await route.fulfill({ json: body })
  })
  await page.goto("/create")
  // The app lazily mounts its notification container after the first render.
  await expect(
    page.getByRole("region", { name: "Notifications alt+T" }),
  ).toBeAttached()
  const card = page.getByTestId(`passage-${article.id}`)
  await card.getByRole("button", { name: article.title, exact: true }).click()
  const row = card.getByRole("listitem").filter({ hasText: sentence.text })
  return {
    card,
    row,
    requests,
    setFailAudio: (value: boolean) => {
      failAudio = value
    },
  }
}

for (const width of [390, 820, 1180]) {
  test(`generated sentence audio plays, stops and ends at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 })
    const { row, requests } = await mockBank(page)
    await expect(row.getByRole("button", { name: "试听标准音" })).toHaveCount(0)
    await row
      .getByRole("button", {
        name: "AI 生成标准音",
        exact: true,
      })
      .click()
    const preview = row.getByRole("button", { name: "试听标准音", exact: true })
    await preview.click()
    const audio = row.locator("audio")
    await expect
      .poll(() => audio.evaluate((el: HTMLAudioElement) => el.currentTime))
      .toBeGreaterThan(0)
    expect(requests).toContain("/api/v1/audio/content/generated-1.wav")
    await row.getByRole("button", { name: "停止试听" }).click()
    await expect
      .poll(() => audio.evaluate((el: HTMLAudioElement) => el.paused))
      .toBe(true)
    await preview.click()
    await expect(row.getByRole("button", { name: "停止试听" })).toBeVisible()
    await expect(preview).toBeVisible({ timeout: 10_000 })
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      ),
    ).toBeLessThanOrEqual(1)
  })
}

test("article preview leaves its card expanded; collapse stops sentence audio", async ({
  page,
}) => {
  const { card, row } = await mockBank(page)
  await card.getByRole("button", { name: "试听标准音", exact: true }).click()
  await expect(row).toBeVisible()
  await card.getByRole("button", { name: "停止试听" }).click()
  await row
    .getByRole("button", {
      name: "AI 生成标准音",
      exact: true,
    })
    .click()
  await row.getByRole("button", { name: "试听标准音" }).click()
  await row.locator("audio").evaluate((el) => {
    ;(window as unknown as { previewAudio: HTMLAudioElement }).previewAudio =
      el as HTMLAudioElement
  })
  await card.getByRole("button", { name: "Our city", exact: true }).click()
  await expect(row).toHaveCount(0)
  expect(
    await page.evaluate(
      () =>
        (window as unknown as { previewAudio: HTMLAudioElement }).previewAudio
          .paused,
    ),
  ).toBe(true)
})

test("upload, regenerate and clear update the preview and stop the old audio", async ({
  page,
}) => {
  const { row, requests } = await mockBank(page)
  await row.locator('input[type="file"]').setInputFiles({
    name: "teacher.wav",
    mimeType: "audio/wav",
    buffer: wav(),
  })
  await row.getByRole("button", { name: "试听标准音" }).click()
  await expect
    .poll(() =>
      row.locator("audio").evaluate((el: HTMLAudioElement) => el.currentTime),
    )
    .toBeGreaterThan(0)
  expect(requests).toContain("/api/v1/audio/content/uploaded.wav")
  await row.locator("audio").evaluate((el) => {
    ;(window as unknown as { previewAudio: HTMLAudioElement }).previewAudio =
      el as HTMLAudioElement
  })
  await row
    .getByRole("button", {
      name: "AI 生成标准音",
      exact: true,
    })
    .click()
  await expect(row.locator("audio")).toHaveAttribute(
    "src",
    "/api/v1/audio/content/generated-1.wav",
  )
  expect(
    await page.evaluate(
      () =>
        (window as unknown as { previewAudio: HTMLAudioElement }).previewAudio
          .paused,
    ),
  ).toBe(true)
  await row.getByRole("button", { name: "试听标准音" }).click()
  await row.getByRole("button", { name: "清除标准音", exact: true }).click()
  await expect(row.locator("audio")).toHaveCount(0)
  await expect(row.getByRole("button", { name: "试听标准音" })).toHaveCount(0)
})

test("failed audio shows an English error and can be retried", async ({
  page,
}) => {
  const { row, setFailAudio } = await mockBank(page, "en")
  await row
    .getByRole("button", {
      name: "Generate AI audio",
      exact: true,
    })
    .click()
  await expect(page.getByText("Audio generated", { exact: true })).toBeVisible()
  setFailAudio(true)
  await row.getByRole("button", { name: "Preview audio" }).click()
  await expect(
    page.getByText("Audio playback failed. Retry or regenerate the audio.", {
      exact: true,
    }),
  ).toBeVisible()
  await expect(row.getByRole("button", { name: "Preview audio" })).toBeVisible()
  setFailAudio(false)
  await row.getByRole("button", { name: "Preview audio" }).click()
  await expect
    .poll(() =>
      row.locator("audio").evaluate((el: HTMLAudioElement) => el.currentTime),
    )
    .toBeGreaterThan(0)
})
