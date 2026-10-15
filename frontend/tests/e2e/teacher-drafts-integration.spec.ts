import { expect, test } from "@playwright/test"

/** Real API: persistence, history reuse, explicit publish, atomic draft cleanup. */
test("teacher draft survives reload and history copies to another class before publishing", async ({
  page,
}) => {
  const demo = await page.request.post("/api/v1/login/demo")
  expect(demo.ok()).toBeTruthy()
  const { access_token: token } = (await demo.json()) as {
    access_token: string
  }
  const headers = { Authorization: `Bearer ${token}` }
  const codes: string[] = []
  try {
    for (let i = 0; i < 2; i++) {
      const created = await page.request.post("/api/v1/classes", {
        headers,
        data: { class_size: 10 },
      })
      expect(created.ok()).toBeTruthy()
      codes.push(((await created.json()) as { code: string }).code)
    }
    const [source, target] = codes
    const bank = await page.request.get("/api/v1/admin/passages?limit=1", {
      headers,
    })
    const {
      data: [passage],
    } = (await bank.json()) as { data: { id: string }[] }
    expect(passage).toBeTruthy()
    const publish = await page.request.put(
      `/api/v1/classes/${source}/assignment`,
      {
        headers,
        data: {
          title: "Original live practice",
          items: [{ type: "passage", id: passage.id }],
        },
      },
    )
    expect(publish.ok()).toBeTruthy()
    await page.addInitScript((token) => {
      localStorage.setItem("access_token", token)
      localStorage.setItem("esa:role", "admin")
      localStorage.setItem("esa:lang", "zh")
    }, token)
    await page.goto(`/t/${source}`)
    const input = page.getByPlaceholder("例如：第 3 周｜旅行主题口语练习")
    const saved = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/classes/${source}/composer-draft`) &&
        response.request().method() === "PUT" &&
        response.ok(),
    )
    await input.fill("Live saved draft")
    await saved
    await page.reload()
    await expect(input).toHaveValue("Live saved draft")
    await page.getByRole("tab", { name: "发布历史" }).click()
    await page.getByRole("button", { name: "复制练习", exact: true }).click()
    const dialog = page.getByRole("dialog")
    await dialog.getByRole("combobox").selectOption(target)
    await dialog
      .getByRole("button", { name: "复制到草稿", exact: true })
      .click()
    await expect(page).toHaveURL(new RegExp(`/t/${target}`))
    await expect(input).toHaveValue("Original live practice")
    const before = await page.request.get(`/api/v1/classes/${target}/board`, {
      headers,
    })
    expect(
      ((await before.json()) as { current_exercise: unknown }).current_exercise,
    ).toBeNull()
    await page.getByRole("button", { name: "预览练习", exact: true }).click()
    await page
      .getByRole("button", { name: "确认发布到课堂", exact: true })
      .click()
    await expect(
      page.getByText("本次课堂练习已发布", { exact: true }),
    ).toBeVisible()
    const after = await page.request.get(`/api/v1/classes/${target}/board`, {
      headers,
    })
    expect(
      ((await after.json()) as { current_exercise: unknown }).current_exercise,
    ).not.toBeNull()
    const draft = await page.request.get(
      `/api/v1/classes/${target}/composer-draft`,
      { headers },
    )
    expect(await draft.json()).toBeNull()
    const sourceDraft = await page.request.get(
      `/api/v1/classes/${source}/composer-draft`,
      { headers },
    )
    expect(
      ((await sourceDraft.json()) as { state: { title: string } }).state.title,
    ).toBe("Live saved draft")
  } finally {
    for (const code of codes)
      await page.request.delete(`/api/v1/classes/${code}?delete_history=true`, {
        headers,
      })
  }
})
