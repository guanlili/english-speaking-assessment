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
const data = {
  sentences: [],
  scenarios: [scenario, emptyScenario],
  instructions: [
    {
      id: "i1",
      title: "Part B",
      text: "Read carefully.",
      suggested_seconds: 15,
    },
  ],
}
const all = { reading: true, repeat: true, qa: true, instruction: false }
const none = { reading: false, repeat: false, qa: false, instruction: false }

test("each type only requires its own selection", () => {
  assert.deepEqual(
    inspectSelection(
      { reading: true, repeat: false, qa: false, instruction: false },
      { passages: ["p1"], sentences: [], scenarioIds: [], instructions: [] },
      data,
    ).problems,
    [],
  )
  assert.deepEqual(
    inspectSelection(
      { reading: false, repeat: true, qa: false, instruction: false },
      {
        passages: [],
        sentences: ["s1", "s2"],
        scenarioIds: [],
        instructions: [],
      },
      data,
    ).problems,
    [],
  )
  assert.deepEqual(
    inspectSelection(
      { reading: false, repeat: false, qa: true, instruction: false },
      { passages: [], sentences: [], scenarioIds: ["sc1"], instructions: [] },
      data,
    ).problems,
    [],
  )
  assert.deepEqual(
    inspectSelection(
      { reading: false, repeat: true, qa: false, instruction: true },
      {
        passages: [],
        sentences: ["s1"],
        scenarioIds: [],
        instructions: ["i1"],
      },
      data,
    ).problems,
    [],
  )
})

test("checked type with empty selection is reported per type", () => {
  const { problems } = inspectSelection(
    { ...all, instruction: true },
    {
      passages: [],
      sentences: [],
      scenarioIds: [],
      instructions: [],
    },
    data,
  )
  assert.equal(problems.length, 4) // 四类勾选了但都没选内容
  // problems 现为 BiString：中英两侧都要能定位到对应题型
  assert.match(problems[0].zh, /朗读/)
  assert.match(problems[0].en, /Read Aloud/)
  assert.match(problems[1].zh, /复述/)
  assert.match(problems[1].en, /Listen & Repeat/)
  assert.match(problems[2].zh, /问答/)
  assert.match(problems[2].en, /Q&A/)
  assert.match(problems[3].zh, /题目说明/)
  assert.match(problems[3].en, /[Ii]nstruction/)
})

test("scenario without questions blocks QA", () => {
  assert.match(
    inspectSelection(
      { reading: false, repeat: false, qa: true, instruction: false },
      { passages: [], sentences: [], scenarioIds: ["sc2"], instructions: [] },
      data,
    ).problems[0].zh,
    /有题目/,
  )
  assert.match(
    inspectSelection(
      { reading: false, repeat: false, qa: true, instruction: false },
      { passages: [], sentences: [], scenarioIds: ["sc2"], instructions: [] },
      data,
    ).problems[0].en,
    /with questions/,
  )
})

test("multiple active QA topics can be selected together", () => {
  const second = { ...scenario, id: "sc3", topic: "Travel" }
  const result = inspectSelection(
    { reading: false, repeat: false, qa: true, instruction: false },
    {
      passages: [],
      sentences: [],
      scenarioIds: ["sc1", "sc3"],
      instructions: [],
    },
    { ...data, scenarios: [...data.scenarios, second] },
  )
  assert.deepEqual(result.problems, [])
  assert.deepEqual(
    result.scenarios.map((item) => item.id),
    ["sc1", "sc3"],
  )
})

test("instructions alone cannot form a lesson", () => {
  const { problems } = inspectSelection(
    { ...none, instruction: true },
    {
      passages: [],
      sentences: [],
      scenarioIds: [],
      instructions: ["i1"],
    },
    data,
  )
  assert.equal(problems.length, 1)
  assert.match(problems[0].zh, /可作答/)
  assert.match(problems[0].en, /answerable/)
})

test("no type checked still reports the answerable-type rule", () => {
  const { problems } = inspectSelection(
    none,
    { passages: [], sentences: [], scenarioIds: [], instructions: [] },
    data,
  )
  assert.equal(problems.length, 1)
  assert.match(problems[0].zh, /至少选择一种/)
})
