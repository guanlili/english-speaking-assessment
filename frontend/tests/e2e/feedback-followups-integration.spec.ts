import { expect, test } from "@playwright/test"
import { wav } from "./utils/audio"

/** Real API, two accounts: teacher feedback -> selected task -> student submission. */
test("teacher feedback reaches its student and targeted practice leaves original results intact", async ({
  page,
  browser,
}) => {
  test.setTimeout(90_000)
  const demo = await page.request.post("/api/v1/login/demo")
  expect(demo.ok()).toBeTruthy()
  const adminToken = ((await demo.json()) as { access_token: string })
    .access_token
  const adminHeaders = { Authorization: `Bearer ${adminToken}` }
  const classroom = await page.request.post("/api/v1/classes", {
    headers: adminHeaders,
    data: { class_size: 10 },
  })
  const { code } = (await classroom.json()) as { code: string }
  const accounts: { id: string; studentId: string; token: string }[] = []
  let passageId: string | undefined
  let studentContext: Awaited<ReturnType<typeof browser.newContext>> | undefined
  try {
    for (const name of ["Alice", "Ben"]) {
      const username = `followup-${name}-${Date.now()}`
      const created = await page.request.post("/api/v1/users/", {
        headers: adminHeaders,
        data: {
          username,
          full_name: name,
          password: "Followup-pass-1234",
          role: "student",
        },
      })
      expect(created.ok()).toBeTruthy()
      const user = (await created.json()) as { id: string }
      const login = await page.request.post("/api/v1/login/access-token", {
        form: { username, password: "Followup-pass-1234" },
      })
      const token = ((await login.json()) as { access_token: string })
        .access_token
      const joined = await page.request.post(`/api/v1/classes/${code}/join`, {
        headers: { Authorization: `Bearer ${token}` },
        data: { display_name: name },
      })
      expect(joined.ok()).toBeTruthy()
      accounts.push({
        id: user.id,
        studentId: ((await joined.json()) as { id: string }).id,
        token,
      })
    }
    const passageResponse = await page.request.post("/api/v1/admin/passages", {
      headers: adminHeaders,
      data: {
        title: `Follow-up test ${Date.now()}`,
        text: "I like sharing my ideas with my classmates.",
        suggested_seconds: 30,
      },
    })
    expect(passageResponse.ok()).toBeTruthy()
    const passage = (await passageResponse.json()) as { id: string }
    passageId = passage.id
    const published = await page.request.put(
      `/api/v1/classes/${code}/assignment`,
      {
        headers: adminHeaders,
        data: {
          title: "Original practice",
          items: [{ type: "passage", id: passage.id }],
        },
      },
    )
    expect(published.ok()).toBeTruthy()
    const aliceHeaders = { Authorization: `Bearer ${accounts[0].token}` }
    const benHeaders = { Authorization: `Bearer ${accounts[1].token}` }
    const planResponse = await page.request.get(
      `/api/v1/classes/${code}/today`,
      { headers: aliceHeaders },
    )
    const plan = (await planResponse.json()) as {
      session_id: string
      items: { id: string }[]
    }
    const upload = await page.request.post("/api/v1/attempts", {
      headers: aliceHeaders,
      multipart: {
        session_id: plan.session_id,
        item_id: plan.items[0].id,
        item_type: "passage",
        duration_s: "4",
        audio: { name: "answer.wav", mimeType: "audio/wav", buffer: wav() },
      },
    })
    expect(upload.ok()).toBeTruthy()
    const attemptId = ((await upload.json()) as { id: string }).id
    await expect
      .poll(
        async () =>
          (
            (await (
              await page.request.get(`/api/v1/attempts/${attemptId}`, {
                headers: aliceHeaders,
              })
            ).json()) as { status: string }
          ).status,
        { timeout: 20000 },
      )
      .toBe("done")
    const original = (await (
      await page.request.get(`/api/v1/attempts/${attemptId}`, {
        headers: aliceHeaders,
      })
    ).json()) as { overall: number | null; session_id: string }
    await page.addInitScript((token) => {
      localStorage.setItem("access_token", token)
      localStorage.setItem("esa:role", "admin")
      localStorage.setItem("esa:lang", "zh")
    }, adminToken)
    await page.goto(`/t/${code}`)
    await page.getByRole("tab", { name: "学生结果" }).click()
    await page.getByRole("button", { name: "展开 Alice 的详情" }).click()
    await page
      .getByRole("button", { name: "详细反馈", exact: true })
      .first()
      .click()
    const feedback = page.getByRole("dialog")
    await feedback
      .getByRole("textbox", { name: "教师点评内容" })
      .fill("Start clearly and practise linking your ideas.")
    await feedback
      .getByRole("checkbox", { name: "标记为重点关注", exact: true })
      .check()
    await feedback.getByRole("button", { name: "保存教师点评" }).click()
    await expect(
      feedback.getByRole("region", { name: "教师点评", exact: true }),
    ).toContainText("Start clearly", { timeout: 15000 })
    await page.keyboard.press("Escape")
    const tasks = page.getByRole("region", {
      name: "指定学生补练",
      exact: true,
    })
    await tasks.getByRole("button", { name: "布置补练", exact: true }).click()
    const assignment = page.getByRole("dialog")
    await assignment
      .getByLabel("补练名称", { exact: true })
      .fill("Alice focused practice")
    await assignment
      .getByRole("checkbox", { name: "Alice", exact: true })
      .check()
    await assignment
      .getByRole("button", { name: "确认布置给 1 人", exact: true })
      .click()
    await expect(tasks).toContainText("Alice focused practice")
    const assigned = (await (
      await page.request.get(`/api/v1/classes/${code}/followups`, {
        headers: aliceHeaders,
      })
    ).json()) as { id: string }[]
    expect(assigned).toHaveLength(1)
    expect(
      await (
        await page.request.get(`/api/v1/classes/${code}/followups`, {
          headers: benHeaders,
        })
      ).json(),
    ).toEqual([])
    expect(
      (
        await page.request.post(
          `/api/v1/classes/${code}/followups/${assigned[0].id}/start`,
          { headers: benHeaders },
        )
      ).status(),
    ).toBe(404)
    studentContext = await browser.newContext({
      baseURL: new URL(page.url()).origin,
    })
    await studentContext.addInitScript(
      ({ code, account }) => {
        localStorage.setItem("access_token", account.token)
        localStorage.setItem("esa:role", "student")
        localStorage.setItem("esa:lang", "zh")
        localStorage.setItem(
          `esa:student:${code}`,
          JSON.stringify({
            id: account.studentId,
            user_id: account.id,
            display_name: "Alice",
          }),
        )
      },
      { code, account: accounts[0] },
    )
    const student = await studentContext.newPage()
    await student.goto(`/p/${code}/result?session=${plan.session_id}`)
    await expect(
      student.getByRole("region", { name: "教师点评", exact: true }),
    ).toContainText("Start clearly", { timeout: 15000 })
    await student.goto(`/home/${code}`)
    const ownTasks = student.getByRole("region", {
      name: "老师布置的补练",
      exact: true,
    })
    await ownTasks
      .getByRole("button", { name: "开始补练", exact: true })
      .click()
    await expect(student).toHaveURL(new RegExp(`/p/${code}.*session=`))
    const taskSessionId = new URL(student.url()).searchParams.get("session")
    expect(taskSessionId).not.toBe(plan.session_id)
    const nextUpload = await page.request.post("/api/v1/attempts", {
      headers: aliceHeaders,
      multipart: {
        session_id: taskSessionId ?? "",
        item_id: plan.items[0].id,
        item_type: "passage",
        duration_s: "4",
        audio: { name: "practice.wav", mimeType: "audio/wav", buffer: wav() },
      },
    })
    expect(nextUpload.ok()).toBeTruthy()
    const followupAttempt = ((await nextUpload.json()) as { id: string }).id
    await expect
      .poll(
        async () =>
          (
            (await (
              await page.request.get(`/api/v1/attempts/${followupAttempt}`, {
                headers: aliceHeaders,
              })
            ).json()) as { status: string }
          ).status,
        { timeout: 20000 },
      )
      .toBe("done")
    const unchanged = (await (
      await page.request.get(`/api/v1/attempts/${attemptId}`, {
        headers: aliceHeaders,
      })
    ).json()) as { overall: number | null; session_id: string }
    expect(unchanged.overall).toBe(original.overall)
    expect(unchanged.session_id).toBe(original.session_id)
    const finalTasks = (await (
      await page.request.get(`/api/v1/classes/${code}/followups`, {
        headers: adminHeaders,
      })
    ).json()) as { targets: { done_count: number; total_count: number }[] }[]
    expect(finalTasks[0].targets[0].done_count).toBe(
      finalTasks[0].targets[0].total_count,
    )
  } finally {
    await studentContext?.close()
    await page.goto("about:blank")
    await page.request.delete(`/api/v1/classes/${code}?delete_history=true`, {
      headers: adminHeaders,
    })
    if (passageId)
      await page.request.delete(`/api/v1/admin/passages/${passageId}`, {
        headers: adminHeaders,
      })
    // Accounts are ephemeral test identities in the isolated E2E database.
  }
})
