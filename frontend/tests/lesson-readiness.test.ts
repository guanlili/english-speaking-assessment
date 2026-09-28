import assert from "node:assert/strict"
import { test } from "node:test"
import { inspectSelection } from "../src/lib/lesson-readiness.ts"

const scenario = {
  id: "sc1",
  topic: "Boring Places",
  is_active: true,
  questions: [
    {
      id: "q1",
      band: "B1",
      text: "Describe a boring place.",
      suggested_seconds: 30,
    },
    { id: "q2", band: "B1", text: "Explain why.", suggested_seconds: 45 },
  ],
}
const emptyScenario = { ...scenario, id: "sc2", questions: [] }
const data = { sentences: [], scenarios: [scenario, emptyScenario] }
const all = { reading: true, repeat: true, qa: true }

test("each type only requires its own selection", () => {
  assert.deepEqual(
    inspectSelection(
      { reading: true, repeat: false, qa: false },
      { passages: ["p1"], sentences: [], scenarioId: null },
      data,
    ).problems,
    [],
  )
  assert.deepEqual(
    inspectSelection(
      { reading: false, repeat: true, qa: false },
      { passages: [], sentences: ["s1", "s2"], scenarioId: null },
      data,
    ).problems,
    [],
  )
  assert.deepEqual(
    inspectSelection(
      { reading: false, repeat: false, qa: true },
      { passages: [], sentences: [], scenarioId: "sc1" },
      data,
    ).problems,
    [],
  )
})

test("checked type with empty selection is reported per type", () => {
  const { problems } = inspectSelection(
    all,
    {
      passages: [],
      sentences: [],
      scenarioId: null,
    },
    data,
  )
  assert.equal(problems.length, 3) // 三类勾选了但都没选内容
  assert.match(problems[0], /朗读/)
  assert.match(problems[1], /复述/)
  assert.match(problems[2], /问答/)
})

test("scenario without questions blocks QA", () => {
  assert.match(
    inspectSelection(
      { reading: false, repeat: false, qa: true },
      { passages: [], sentences: [], scenarioId: "sc2" },
      data,
    ).problems[0],
    /有题目/,
  )
})
