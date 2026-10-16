import assert from "node:assert/strict"
import { test } from "node:test"

import { skippedSpans } from "../src/lib/skipped-spans.ts"

test("marks the words skipped in reading order", () => {
  assert.deepEqual(
    skippedSpans("I usually visit the museum", "I visit the museum"),
    ["usually"],
  )
})

test("an extra word at the start does not mark the whole sentence skipped", () => {
  assert.deepEqual(
    skippedSpans(
      "I usually visit the museum",
      "well I usually visit the museum",
    ),
    [],
  )
})

test("silence does not invent a skipped span", () => {
  assert.deepEqual(skippedSpans("I usually visit the museum", ""), [])
})

test("groups a consecutive skip and caps the list", () => {
  const reference = "one two three four five six seven eight nine ten"
  const spans = skippedSpans(reference, "one ten")
  assert.deepEqual(spans, ["two three four five six seven eight nine"])
})
