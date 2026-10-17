import { expect, type Locator, type Page, test } from "@playwright/test"
import type { ComposerState } from "../../src/client"

const passage = {
  id: "passage-original",
  slug: "original",
  title: "Shared passage",
  topic: "Travel",
  text: "We visited a new city.",
  cefr_band: "B1",
  suggested_seconds: 45,
  owner_id: "other-teacher",
  is_active: true,
  unit_id: null,
  audio_url: "/audio/passage.mp3",
  sentences: [],
  reading_split: false,
  reading_segments: [],
  reading_child_ids: [],
}
const sentence = {
  id: "sentence-original",
  text: "Please open your book.",
  translation: "请打开书。",
  owner_id: "other-teacher",
  passage_id: passage.id,
  passage_title: passage.title,
  order_index: 0,
  suggested_seconds: 12,
  replay_limit: 3,
  exam_kind: "toefl_lnr",
  exam_level: "KET",
  audio_url: "/audio/sentence.mp3",
}
const question = {
  id: "question-original",
  scenario_id: "scenario-original",
  topic: "Travel",
  band: "B1",
  text: "Describe a place you visited.",
  translation: "描述你去过的地方。",
  owner_id: "other-teacher",
  order_index: 0,
  suggested_seconds: 120,
  exam_kind: "ielts_p2",
  exam_level: "IELTS_TOEFL",
  cue_card_bullets: ["Where it is", "Who you went with"],
  prep_seconds: 60,
  audio_url: "/audio/question.mp3",
}
const scenario = {
  id: "scenario-original",
  topic: "Travel",
  owner_id: "other-teacher",
  is_active: true,
  questions: [
    question,
    {
      ...question,
      id: "question-second",
      text: "Why did you choose that place?",
    },
  ],
}
const instruction = {
  id: "instruction-original",
  title: "Read first",
  text: "Read the question carefully.",
  owner_id: "other-teacher",
  suggested_seconds: 20,
}
const extraInstruction = {
  ...instruction,
  id: "instruction-extra",
  title: "Draft choice",
}
const exercise = {
  id: "published",
  title: "Original lesson",
  item_count: 2,
  version_no: 1,
  status: "published",
  is_exam: false,
}
type Kind =
  | "passages"
  | "sentences"
  | "questions"
  | "scenarios"
  | "instructions"
const originals: Record<Kind, Record<string, unknown>> = {
  passages: passage,
  sentences: sentence,
  questions: question,
  scenarios: scenario,
  instructions: instruction,
}

async function setup(page: Page, lang: "zh" | "en") {
  await page.addInitScript((language) => {
    localStorage.setItem("access_token", "copy-teacher-token")
    localStorage.setItem("esa:role", "teacher")
    localStorage.setItem("esa:lang", language)
  }, lang)
  const copies = new Map<Kind, Record<string, unknown>>()
  const copyRequests: string[] = []
  const updates: { path: string; body: Record<string, unknown> }[] = []
  const reads: string[] = []
  const publications: unknown[] = []
  const drafts: ComposerState[] = []
  let failCopy = false
  let failSave = false
  let showCopiedInstruction = false
  let copyGate: Promise<void> | undefined
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    let json: unknown = []
    const copyMatch = path.match(
      /\/admin\/(passages|sentences|questions|scenarios|instructions)\/[^/]+\/copy$/,
    )
    if (copyMatch) {
      expect(request.method()).toBe("POST")
      expect(request.postData()).toBeNull()
      copyRequests.push(path)
      await copyGate
      copyGate = undefined
      if (failCopy) {
        failCopy = false
        return route.fulfill({
          status: 500,
          json: { detail: "INTERNAL_COPY_DETAIL_DO_NOT_DISPLAY" },
        })
      }
      const kind = copyMatch[1] as Kind
      const copy = {
        ...originals[kind],
        id: `${kind}-copy`,
        owner_id: "teacher",
      }
      if (kind === "passages")
        Object.assign(copy, {
          title: "Shared passage (copy)",
          slug: "original-copy",
        })
      if (kind === "sentences")
        Object.assign(copy, { passage_id: null, passage_title: null })
      if (kind === "scenarios")
        Object.assign(copy, {
          topic: "Travel (copy)",
          questions: scenario.questions.map((child, index) => ({
            ...child,
            id: index === 0 ? "scenario-child-copy" : "scenario-second-copy",
            scenario_id: copy.id,
            owner_id: "teacher",
          })),
        })
      if (kind === "instructions")
        Object.assign(copy, { title: "Read first (copy)" })
      copies.set(kind, copy)
      return route.fulfill({ json: copy })
    }
    if (request.method() === "PUT" && path.includes("/admin/")) {
      const body = request.postDataJSON() as Record<string, unknown>
      updates.push({ path, body })
      if (failSave) {
        failSave = false
        return route.fulfill({
          status: 500,
          json: { detail: "INTERNAL_SAVE_DETAIL_DO_NOT_DISPLAY" },
        })
      }
      const kind = path.split("/")[4] as Kind
      const updated = { ...copies.get(kind), ...body }
      copies.set(kind, updated)
      return route.fulfill({ json: updated })
    }
    if (request.method() === "GET") reads.push(path)
    if (path.endsWith("/users/me"))
      json = {
        id: "teacher",
        email: "teacher@example.com",
        role: "teacher",
        is_active: true,
        is_superuser: false,
      }
    // Copies deliberately do not appear on these catalog pages: the returned object must open the editor.
    else if (path.endsWith("/admin/passages"))
      json = { data: [passage], count: 21 }
    else if (path.endsWith("/admin/units")) json = []
    else if (path.endsWith("/admin/topics")) json = ["Travel"]
    else if (path.endsWith("/admin/sentences-page"))
      json = { data: [sentence], count: 21 }
    else if (path.endsWith("/admin/sentences")) json = [sentence]
    else if (path.endsWith("/admin/questions"))
      json = { data: [question], count: 21 }
    else if (path.endsWith("/admin/scenarios")) {
      const copy = copies.get("scenarios")
      json =
        url.searchParams.get("q") === "Travel (copy)" && copy
          ? { data: [copy], count: 1 }
          : { data: [scenario], count: 21 }
    } else if (path.endsWith("/admin/instructions"))
      json = [
        instruction,
        extraInstruction,
        ...(showCopiedInstruction ? [copies.get("instructions")] : []),
      ]
    else if (path.endsWith("/composer-selection"))
      json = {
        passages: [passage],
        sentences: [],
        scenarios: [],
        instructions: [
          instruction,
          extraInstruction,
          ...(copies.has("instructions") ? [copies.get("instructions")] : []),
        ],
        missing_ids: [],
      }
    else if (path.endsWith("/composer-draft")) {
      if (request.method() === "PUT") {
        const body = request.postDataJSON() as {
          state: ComposerState
          expected_revision: number
        }
        drafts.push(body.state)
        json = {
          state: body.state,
          revision: body.expected_revision + 1,
          updated_at: new Date().toISOString(),
        }
      } else json = null
    } else if (path.endsWith("/board"))
      json = {
        classroom_code: "COPY",
        classroom_name: "Copy class",
        class_size: 1,
        submitted_count: 0,
        completed_count: 0,
        pending_count: 0,
        engine: "mock",
        students: [],
        items: [],
        current_exercise: exercise,
        assigned_items: [
          { type: "passage", id: passage.id },
          { type: "instruction", id: instruction.id },
        ],
      }
    else if (path.endsWith("/weak-spots"))
      json = { word_gaps: [], low_items: [] }
    else if (path.endsWith("/exercises")) json = [exercise]
    else if (path.endsWith("/assignment")) {
      publications.push(request.postDataJSON())
      json = exercise
    }
    await route.fulfill({ json })
  })
  return {
    copies,
    copyRequests,
    updates,
    reads,
    publications,
    drafts,
    failNextCopy: () => {
      failCopy = true
    },
    failNextSave: () => {
      failSave = true
    },
    refreshInstructionCopy: (text: string) => {
      copies.set("instructions", { ...copies.get("instructions"), text })
      showCopiedInstruction = true
    },
    holdCopy: () => {
      let release: () => void = () => {}
      copyGate = new Promise<void>((resolve) => {
        release = resolve
      })
      return release
    },
  }
}

async function expectTouchTarget(button: Locator) {
  const box = await button.boundingBox()
  expect(box?.height).toBeGreaterThanOrEqual(44)
  expect(box?.width).toBeGreaterThanOrEqual(44)
}
async function expectFits(page: Page) {
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1)
  const dialog = page.getByRole("dialog")
  if (await dialog.count()) {
    expect(
      await dialog.evaluate((el) => el.scrollWidth - el.clientWidth),
    ).toBeLessThanOrEqual(1)
    for (const input of await dialog.locator("input, textarea, select").all()) {
      expect(
        await input.evaluate((el) =>
          Number.parseFloat(getComputedStyle(el).fontSize),
        ),
      ).toBeGreaterThanOrEqual(16)
    }
  }
}

for (const [width, lang] of [
  [390, "zh"],
  [820, "en"],
  [1180, "zh"],
] as const) {
  for (const kind of ["passages", "questions", "sentences"] as const) {
    test(`@webkit copy ${kind} opens editable returned copy at ${width}px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 1000 })
      const mock = await setup(page, lang)
      await page.goto(
        kind === "sentences" ? "/create#bank-repeat" : `/admin/${kind}`,
      )
      const section =
        kind === "sentences"
          ? page.locator("#bank-repeat")
          : page.getByRole("main")
      const labels = {
        passages: /复制篇目 Shared passage|Copy passage Shared passage/,
        questions: /复制题目|Copy question/,
        sentences: /复制复述句|Copy repeat sentence/,
      }
      const button = section.getByRole("button", {
        name: labels[kind],
        exact: true,
      })
      await expect(button).toBeVisible()
      await expectTouchTarget(button)
      await expect(
        section.getByRole("button", { name: /^(编辑|Edit)/ }),
      ).toHaveCount(0)
      const readsBefore = mock.reads.length
      await button.click()
      const dialog = page.getByRole("dialog")
      await expect(dialog).toBeVisible()
      const textId = {
        passages: "#edit-passage-text",
        questions: "#q-text",
        sentences: "#edit-sentence-text",
      }[kind]
      await expect(dialog.locator(textId)).toHaveValue(
        String(originals[kind].text),
      )
      if (kind === "sentences")
        await expect(dialog.getByRole("combobox").first()).toContainText(
          /独立题目|standalone/,
        )
      if (kind === "questions") {
        await expect(dialog.locator("#q-seconds")).toHaveValue("120")
        await expect(dialog.locator("#q-cue-card")).toHaveValue(
          question.cue_card_bullets.join("\n"),
        )
        await expect(dialog.locator("#q-prep")).toHaveValue("60")
      }
      await expectFits(page)
      await dialog.locator(textId).fill("Adapted copy only.")
      await dialog.getByRole("button", { name: /^(保存|Save)$/ }).click()
      await expect(dialog).toHaveCount(0)
      expect(mock.copyRequests).toHaveLength(1)
      expect(mock.updates).toHaveLength(1)
      expect(mock.updates[0].path).toBe(`/api/v1/admin/${kind}/${kind}-copy`)
      expect(mock.updates[0].body.text).toBe("Adapted copy only.")
      await expect.poll(() => mock.reads.length).toBeGreaterThan(readsBefore)
      await expect(
        section.getByText(String(originals[kind].text), { exact: true }),
      ).toHaveCount(kind === "passages" ? 0 : 1)
      await expectFits(page)
    })
  }

  test(`@webkit copied topic displays all children for adaptation at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 })
    const mock = await setup(page, lang)
    await page.goto("/admin/scenarios")
    const button = page.getByRole("button", {
      name: /^(复制主题 Travel|Copy topic Travel)$/,
    })
    await expectTouchTarget(button)
    await button.click()
    await expect(
      page.getByRole("textbox", { name: /搜索问答主题|Search Q&A topics/ }),
    ).toHaveValue("Travel (copy)")
    const card = page.getByTestId("scenario-scenarios-copy")
    await expect(card.getByText(question.text, { exact: false })).toBeVisible()
    await expect(
      card.getByText("Why did you choose that place?", { exact: false }),
    ).toBeVisible()
    await card
      .getByRole("button", { name: /^(编辑题目 1|Edit question 1)$/ })
      .click()
    const dialog = page.getByRole("dialog")
    await expect(dialog.locator("#scn-q-seconds")).toHaveValue("120")
    await expectFits(page)
    await dialog.locator("#scn-q-text").fill("Adapted topic child.")
    await dialog.getByRole("button", { name: /^(保存|Save)$/ }).click()
    await expect(dialog).toHaveCount(0)
    expect(mock.updates[0].path).toBe(
      "/api/v1/admin/questions/scenario-child-copy",
    )
    expect(mock.updates[0].body).not.toHaveProperty("exam_kind")
    expect(mock.updates[0].body).not.toHaveProperty("audio_url")
    await expectFits(page)
  })

  test(`@webkit instruction copy preserves draft and published selections at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 })
    const mock = await setup(page, lang)
    await page.goto("/t/COPY")
    await expect(
      page.locator("#pick-instruction-instruction-original"),
    ).toBeChecked()
    await page.locator("#pick-instruction-instruction-extra").check()
    const original = page.getByTestId("instruction-instruction-original")
    await expect(
      original.getByRole("button", {
        name: /编辑这条说明|Edit this instruction/,
      }),
    ).toHaveCount(0)
    const copy = original.getByRole("button", {
      name: /复制这条说明|Copy this instruction/,
    })
    await expectTouchTarget(copy)
    await copy.click()
    const dialog = page.getByRole("dialog")
    await expect(dialog.locator("#edit-instruction-title")).toHaveValue(
      "Read first (copy)",
    )
    await expect(dialog.locator("#edit-instruction-text")).toHaveValue(
      instruction.text,
    )
    await expectFits(page)
    mock.failNextSave()
    await dialog.locator("#edit-instruction-text").fill("Adapted instruction.")
    const save = dialog.getByRole("button", { name: /^(保存|Save)$/ })
    await save.click()
    await expect(
      page.getByText(/保存失败，请重试|Save failed. Please retry/),
    ).toBeVisible()
    await expect(dialog.locator("#edit-instruction-text")).toHaveValue(
      "Adapted instruction.",
    )
    await expect(
      page.getByText("INTERNAL_SAVE_DETAIL_DO_NOT_DISPLAY"),
    ).toHaveCount(0)
    await save.click()
    await expect(dialog).toHaveCount(0)
    for (const id of [instruction.id, extraInstruction.id, "instructions-copy"])
      await expect(page.locator(`#pick-instruction-${id}`)).toBeChecked()
    const copiedRow = page.getByTestId("instruction-instructions-copy")
    await copiedRow
      .getByRole("button", { name: /编辑这条说明|Edit this instruction/ })
      .click()
    await expect(dialog.locator("#edit-instruction-text")).toHaveValue(
      "Adapted instruction.",
    )
    await dialog.getByRole("button", { name: /^(取消|Cancel)$/ }).click()
    await expect(dialog).toHaveCount(0)
    await expect
      .poll(() => mock.drafts[mock.drafts.length - 1]?.selection.instructions)
      .toEqual([instruction.id, extraInstruction.id, "instructions-copy"])
    expect(mock.publications).toHaveLength(0)
    expect(
      mock.updates.every((update) =>
        update.path.endsWith("/instructions/instructions-copy"),
      ),
    ).toBe(true)
    await expectFits(page)
  })
}

test("@webkit read-only topic question can be copied without duplicating its topic", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 1000 })
  const mock = await setup(page, "zh")
  await page.goto("/admin/scenarios")
  const card = page.getByTestId("scenario-scenario-original")
  await card.locator("summary").click()
  await expect(
    card.getByRole("button", { name: "编辑题目 1", exact: true }),
  ).toHaveCount(0)
  await card.getByRole("button", { name: "复制题目 1", exact: true }).click()
  const dialog = page.getByRole("dialog")
  await expect(dialog.locator("#scn-q-text")).toHaveValue(question.text)
  await dialog.locator("#scn-q-text").fill("My adapted question.")
  await dialog.getByRole("button", { name: "保存", exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(mock.updates[0].path).toBe("/api/v1/admin/questions/questions-copy")
  expect(mock.copies.get("questions")?.scenario_id).toBe(scenario.id)
  expect(mock.copies.has("scenarios")).toBe(false)
  await expectFits(page)
})

test("@webkit refreshed instruction replaces a locally remembered copy", async ({
  page,
}) => {
  const mock = await setup(page, "zh")
  await page.goto("/t/COPY")
  await page
    .getByTestId("instruction-instruction-original")
    .getByRole("button", { name: "复制这条说明", exact: true })
    .click()
  const dialog = page.getByRole("dialog")
  await expect(dialog.locator("#edit-instruction-text")).toHaveValue(
    instruction.text,
  )
  await dialog.getByRole("button", { name: "取消", exact: true }).click()
  mock.refreshInstructionCopy("Updated from another window.")
  await page
    .getByRole("textbox", { name: "搜索题目说明", exact: true })
    .fill("Updated")
  const copy = page.getByTestId("instruction-instructions-copy")
  await expect(copy).toContainText("Updated from another window.")
  await copy.getByRole("button", { name: "编辑这条说明", exact: true }).click()
  await expect(dialog.locator("#edit-instruction-text")).toHaveValue(
    "Updated from another window.",
  )
  expect(mock.updates).toHaveLength(0)
})

for (const lang of ["zh", "en"] as const) {
  test(`@webkit copy failure is translated and retryable with rapid clicks guarded (${lang})`, async ({
    page,
  }) => {
    const mock = await setup(page, lang)
    mock.failNextCopy()
    await page.goto("/admin/passages")
    const button = page.getByRole("button", {
      name: /复制篇目 Shared passage|Copy passage Shared passage/,
    })
    await button.click()
    await expect(
      page.getByText(
        /复制失败，请重试；原内容未改动|Copy failed. Please retry; the original is unchanged./,
      ),
    ).toBeVisible()
    await expect(
      page.getByText("INTERNAL_COPY_DETAIL_DO_NOT_DISPLAY"),
    ).toHaveCount(0)
    await expect(page.getByRole("dialog")).toHaveCount(0)
    await expect(button).toBeEnabled()
    expect(mock.copyRequests).toHaveLength(1)
    const release = mock.holdCopy()
    await button.click()
    await expect(button).toBeDisabled()
    await button.dispatchEvent("click")
    await expect.poll(() => mock.copyRequests.length).toBe(2)
    release()
    await expect(page.getByRole("dialog")).toBeVisible()
    expect(mock.copyRequests).toHaveLength(2)
    expect(mock.updates).toHaveLength(0)
  })
}
