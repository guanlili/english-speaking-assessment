import assert from "node:assert/strict"
import test from "node:test"
import {
  assignmentItemKey,
  defaultAssignmentOrder,
  moveAssignmentItem,
  reconcileAssignmentOrder,
} from "../src/lib/assignment-order.ts"

const item = (type: string, id: string) => ({ type, id })

test("default order alternates repeat and question after passages", () => {
  const ordered = defaultAssignmentOrder(
    [item("passage", "p")],
    [item("repeat", "r1"), item("repeat", "r2")],
    [item("question", "q1"), item("question", "q2")],
  )
  assert.deepEqual(ordered.map(assignmentItemKey), [
    "passage:p",
    "repeat:r1",
    "question:q1",
    "repeat:r2",
    "question:q2",
  ])
})

test("manual order survives selection changes and moves across types", () => {
  const available = defaultAssignmentOrder(
    [],
    [item("repeat", "r1"), item("repeat", "r2")],
    [item("question", "q1")],
  )
  const moved = moveAssignmentItem(available, 2, -1)
  assert.deepEqual(moved.map(assignmentItemKey), [
    "repeat:r1",
    "repeat:r2",
    "question:q1",
  ])
  const changed = reconcileAssignmentOrder(
    [item("repeat", "r2"), item("question", "q1"), item("question", "q2")],
    moved.map(assignmentItemKey),
  )
  assert.deepEqual(changed.map(assignmentItemKey), [
    "repeat:r2",
    "question:q1",
    "question:q2",
  ])
})
