import assert from "node:assert/strict"
import { test } from "node:test"
import { inspectLesson } from "../src/lib/lesson-readiness.ts"

const passage = {
  id: "p",
  slug: "test",
  title: "Pets",
  topic: "Pets",
  text: "I have a cat.",
  unit_id: "unit",
  is_active: true,
  sentences: [
    {
      id: "s",
      passage_id: "p",
      order_index: 0,
      text: "I have a cat.",
      replay_limit: 2,
    },
  ],
}
const scenario = {
  id: "q",
  topic: "Pets",
  is_active: true,
  questions: ["A2", "B1", "B2"].map((band) => ({
    id: band,
    band,
    text: "Do you have a pet?",
    suggested_seconds: 20,
  })),
}
const all = { reading: true, repeat: true, qa: true }
test("complete content allows all three types", () =>
  assert.deepEqual(
    inspectLesson("unit", all, [passage], [scenario]).problems,
    [],
  ))
test("reading-only does not require repeat or questions", () =>
  assert.deepEqual(
    inspectLesson(
      "unit",
      { reading: true, repeat: false, qa: false },
      [{ ...passage, sentences: [] }],
      [],
    ).problems,
    [],
  ))
test("empty selection cannot publish", () =>
  assert.equal(
    inspectLesson("", { reading: false, repeat: false, qa: false }, [], [])
      .problems.length,
    2,
  ))
test("inactive materials do not count as ready", () =>
  assert.equal(
    inspectLesson("unit", all, [{ ...passage, is_active: false }], [scenario])
      .passage,
    undefined,
  ))
test("multiple active passages cannot produce a misleading preview", () =>
  assert.match(
    inspectLesson(
      "unit",
      all,
      [passage, { ...passage, id: "other" }],
      [scenario],
    ).problems[0],
    /多篇/,
  ))
test("missing sentences prevent repeat publication", () =>
  assert.match(
    inspectLesson("unit", all, [{ ...passage, sentences: [] }], [scenario])
      .problems[0],
    /复述句/,
  ))
test("missing adaptive band is identified", () =>
  assert.match(
    inspectLesson(
      "unit",
      all,
      [passage],
      [
        {
          ...scenario,
          questions: scenario.questions.filter((q) => q.band !== "B2"),
        },
      ],
    ).problems[0],
    /B2/,
  ))
test("disabled and mismatched topics cannot supply questions", () => {
  assert.match(
    inspectLesson("unit", all, [passage], [{ ...scenario, is_active: false }])
      .problems[0],
    /A2 \/ B1 \/ B2/,
  )
  assert.match(
    inspectLesson("unit", all, [passage], [{ ...scenario, topic: "School" }])
      .problems[0],
    /缺少/,
  )
})
