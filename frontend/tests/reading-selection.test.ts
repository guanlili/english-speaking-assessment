import assert from "node:assert/strict"
import test from "node:test"
import { normalizeReadingSelection } from "../src/lib/reading-selection.ts"

test("legacy sentence selections collapse to one article without reordering other types", () => {
  const passages = [
    {
      id: "article",
      title: "Article",
      text: "First. Second.",
      reading_child_ids: ["first", "second"],
    },
  ]
  const items = [
    { type: "passage", id: "first" },
    { type: "repeat", id: "r" },
    { type: "passage", id: "second" },
    { type: "passage", id: "article" },
    { type: "question", id: "q" },
  ]
  assert.deepEqual(normalizeReadingSelection(items, passages), [
    { type: "passage", id: "article" },
    { type: "repeat", id: "r" },
    { type: "question", id: "q" },
  ])
  assert.equal(items[0].id, "first")
})

test("independent articles and unrelated items retain their IDs", () => {
  const items = [
    { type: "passage", id: "a" },
    { type: "repeat", id: "r" },
    { type: "passage", id: "b" },
  ]
  assert.deepEqual(normalizeReadingSelection(items, []), items)
})
