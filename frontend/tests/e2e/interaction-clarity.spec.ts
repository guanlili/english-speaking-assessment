import { expect, type Page, test } from "@playwright/test"
import { wav } from "./utils/audio"

async function login(page: Page, role = "teacher") {
  await page.addInitScript((role) => {
    localStorage.setItem("access_token", "test-token")
    localStorage.setItem("esa:role", role)
    localStorage.setItem(
      "esa:student:CLARITY",
      JSON.stringify({
        id: "student",
        user_id: "user",
        display_name: "Student",
      }),
    )
  }, role)
}

async function mockBoard(page: Page, isExam = true) {
  await login(page)
  const article = {
    id: "article",
    slug: "article",
    title: "Our school",
    text: "We study together.",
    topic: "School",
    cefr_band: "B1",
    suggested_seconds: 10,
    is_active: true,
    sentences: [],
  }
  const exercise = {
    id: "version-2",
    version_no: 2,
    title: "New practice",
    status: "published",
    item_count: 1,
    is_exam: isExam,
    time_limit_minutes: isExam ? 45 : null,
  }
  const archived = {
    ...exercise,
    id: "version-1",
    version_no: 1,
    title: "Old practice",
    status: "archived",
    is_exam: false,
    time_limit_minutes: null,
  }
  const submissions: Record<string, unknown>[] = []
  const audioRequests: string[] = []
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path.endsWith("/users/me"))
      body = {
        id: "user",
        email: "teacher@example.com",
        role: "teacher",
        is_superuser: true,
        is_active: true,
      }
    else if (path.endsWith("/admin/passages")) body = [article]
    else if (path.endsWith("/CLARITY/board"))
      body = {
        classroom_code: "CLARITY",
        classroom_name: "Clarity class",
        class_size: 10,
        submitted_count: 1,
        completed_count: 0,
        pending_count: 0,
        engine: "mock",
        students: [],
        current_exercise: exercise,
        assigned_items: [{ type: "passage", id: article.id }],
      }
    else if (path.endsWith("/CLARITY/exercises")) body = [exercise, archived]
    else if (path.endsWith("/version-1/results"))
      body = [
        {
          student_id: "student",
          display_name: "First batch",
          done_count: 1,
          total_count: 1,
          has_pending: false,
          items: [
            {
              item_id: article.id,
              type: "passage",
              status: "done",
              overall: 80,
              attempt_id: "archived-attempt",
            },
          ],
        },
      ]
    else if (path.endsWith("/archived-attempt/audio")) {
      expect(route.request().headers().authorization).toBe("Bearer test-token")
      audioRequests.push(path)
      await route.fulfill({ contentType: "audio/wav", body: wav() })
      return
    } else if (path.endsWith("/CLARITY/assignment")) {
      const data = route.request().postDataJSON() as Record<string, unknown>
      submissions.push(data)
      exercise.is_exam = Boolean(data.is_exam)
      exercise.time_limit_minutes = exercise.is_exam
        ? Number(data.time_limit_minutes)
        : null
      body = exercise
    }
    await route.fulfill({ json: body })
  })
  await page.goto("/t/CLARITY")
  return { submissions, audioRequests }
}

async function noOverflow(page: Page) {
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1)
}

for (const width of [390, 820, 1180]) {
  test(`version results, accurate count label and archived recording at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 })
    const { audioRequests } = await mockBoard(page)
    await page.getByRole("tab", { name: "学生结果" }).click()
    await expect(page.getByText("已有作答", { exact: true })).toBeVisible()
    await expect(page.getByText("至少提交一道题")).toBeVisible()
    await expect(page.getByText("今日 · v2 · New practice")).toBeVisible()
    await expect(page.getByText("今日完成", { exact: true })).toHaveCount(0)
    await page.getByRole("button", { name: "查看历史版本结果" }).click()
    await expect(page.getByRole("button", { name: "查看结果" })).toHaveCount(2)
    await page.getByRole("tab", { name: "练习安排" }).click()
    await page.getByText("发布版本（2 个版本）", { exact: true }).click()
    const archivedRow = page
      .getByText("v1 · Old practice · 1 道题", { exact: true })
      .locator("..")
      .getByRole("button", { name: "查看该版结果" })
    await archivedRow.click()
    await expect(page.getByRole("tab", { name: "发布历史" })).toHaveAttribute(
      "data-state",
      "active",
    )
    await expect(
      page.getByText("v1 · Old practice", { exact: true }),
    ).toBeVisible()
    await page
      .getByRole("button", { name: "回听 First batch 第1题录音" })
      .click()
    const audio = page.locator("audio")
    await expect(audio).toHaveAttribute("src", /^blob:/)
    await audio.evaluate((el: HTMLAudioElement) => el.play())
    await expect
      .poll(() => audio.evaluate((el: HTMLAudioElement) => el.currentTime))
      .toBeGreaterThan(0)
    expect(audioRequests).toEqual(["/api/v1/attempts/archived-attempt/audio"])
    await audio.evaluate((el) => {
      ;(window as unknown as { oldAudio: HTMLAudioElement }).oldAudio =
        el as HTMLAudioElement
    })
    await page.getByRole("button", { name: "收起录音" }).click()
    expect(
      await page.evaluate(
        () =>
          (window as unknown as { oldAudio: HTMLAudioElement }).oldAudio.paused,
      ),
    ).toBe(true)
    await noOverflow(page)
  })
}

for (const change of ["disable", "duration", "enable"]) {
  test(`exam settings reflect the published version and allow ${change} only`, async ({
    page,
  }) => {
    const { submissions } = await mockBoard(page, change !== "enable")
    const exam = page.getByRole("checkbox", { name: "作为模考发布" })
    if (change !== "enable") {
      await expect(exam).toBeChecked()
      await expect(
        page.getByRole("spinbutton", { name: "限时（分钟，5–240）" }),
      ).toHaveValue("45")
    }
    await page.getByRole("button", { name: "预览练习" }).click()
    await expect(
      page.getByRole("button", { name: "与当前发布一致" }),
    ).toBeDisabled()
    await page.getByRole("button", { name: "返回修改" }).click()
    if (change === "duration")
      await page
        .getByRole("spinbutton", { name: "限时（分钟，5–240）" })
        .fill("60")
    else await exam.click()
    await page.getByRole("button", { name: "预览练习" }).click()
    await page.getByRole("button", { name: "确认发布到课堂" }).click()
    await expect.poll(() => submissions.length).toBe(1)
    expect(Boolean(submissions[0].is_exam)).toBe(change !== "disable")
    if (change !== "disable")
      expect(submissions[0].time_limit_minutes).toBe(
        change === "duration" ? 60 : 30,
      )
  })
}

test("invalid exam duration explains why preview is unavailable", async ({
  page,
}) => {
  await mockBoard(page)
  await page.getByRole("spinbutton", { name: "限时（分钟，5–240）" }).fill("1")
  await expect(
    page.getByText("模考限时须为 5–240 分钟的整数", { exact: true }),
  ).toBeVisible()
  await expect(page.getByRole("button", { name: "预览练习" })).toBeDisabled()
})

async function mockListening(
  page: Page,
  failAudio = false,
  failCount = false,
  reading = false,
) {
  await login(page, "student")
  let listens = 0
  let release: (() => void) | undefined
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path.endsWith("/users/me"))
      body = {
        id: "user",
        role: "student",
        is_active: true,
        is_superuser: false,
      }
    else if (path.endsWith("/CLARITY/today"))
      body = {
        session_id: "session",
        classroom_code: "CLARITY",
        band: "B1",
        attempts: [],
        items: [
          {
            id: "sentence",
            type: reading ? "passage" : "repeat",
            text: "Welcome to our city",
            suggested_seconds: 10,
            replay_limit: 3,
            listen_used: 0,
            audio_url: reading ? null : "/api/v1/audio/content/sentence.wav",
          },
        ],
      }
    else if (path.endsWith("/CLARITY/listens")) {
      listens++
      if (failCount) {
        await route.fulfill({
          status: 422,
          json: { detail: "本题作答时间已结束或尚未开始" },
        })
        return
      }
      if (!failAudio)
        await new Promise<void>((resolve) => {
          release = resolve
        })
      body = { listen_used: listens, replay_limit: 3 }
    } else if (path.endsWith("/sentence.wav")) {
      await route.fulfill(
        failAudio ? { status: 404 } : { contentType: "audio/wav", body: wav() },
      )
      return
    }
    await route.fulfill({ json: body })
  })
  await page.goto("/p/CLARITY")
  await expect(
    page.getByRole("region", { name: "Notifications alt+T" }),
  ).toBeAttached()
  return { listens: () => listens, release: () => release?.() }
}

test("repeat audio prevents extra counts while loading or playing", async ({
  page,
}) => {
  const state = await mockListening(page)
  await page.getByRole("button", { name: "听示范", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "正在加载…", exact: true }),
  ).toBeDisabled()
  await expect.poll(state.listens).toBe(1)
  state.release()
  await expect(
    page.getByRole("button", { name: "正在播放…", exact: true }),
  ).toBeDisabled()
  await expect(page.getByText("还可重听 2 次", { exact: true })).toBeVisible()
  expect(state.listens()).toBe(1)
  await expect(
    page.getByRole("button", { name: "听示范", exact: true }),
  ).toBeEnabled({ timeout: 10_000 })
})

test("repeat playback errors are visible and do not leave the button stuck", async ({
  page,
}) => {
  await mockListening(page, true)
  await page.getByRole("button", { name: "听示范", exact: true }).click()
  await expect(
    page.getByText("音频播放失败，请检查网络或设备声音设置", { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "听示范", exact: true }),
  ).toBeEnabled()
})

test("a timing rejection is not mislabeled as exhausted replays", async ({
  page,
}) => {
  await mockListening(page, false, true)
  await page.getByRole("button", { name: "听示范", exact: true }).click()
  await expect(
    page.getByText("本题作答时间已结束或尚未开始", { exact: true }),
  ).toBeVisible()
  await expect(page.getByText("还可重听 3 次", { exact: true })).toBeVisible()
  await expect(
    page.getByRole("button", { name: "听示范", exact: true }),
  ).toBeEnabled()
})

test("device speech is clearly labeled and unsupported playback shows feedback", async ({
  page,
}) => {
  await page.addInitScript(() =>
    Object.defineProperty(window, "speechSynthesis", {
      value: undefined,
      configurable: true,
    }),
  )
  await mockListening(page, false, false, true)
  await expect(page.getByText("设备合成语音", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "听示范", exact: true }).click()
  await expect(
    page.getByText("音频播放失败，请检查网络或设备声音设置", { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "听示范", exact: true }),
  ).toBeEnabled()
})
