import assert from "node:assert/strict"
import { test } from "node:test"

import { itemsUsingDeviceSpeech } from "../src/lib/device-speech.ts"

test("flags listened items that have no model audio", () => {
  const flagged = itemsUsingDeviceSpeech([
    { type: "instruction", label: "Read the note", audioUrl: null },
    { type: "repeat", label: "I like cats", audioUrl: null },
    { type: "repeat", label: "I like dogs", audioUrl: "/audio/dogs.wav" },
    { type: "question", label: "Describe a pet" },
    { type: "passage", label: "Pets", audioUrl: "" },
  ])
  assert.deepEqual(
    flagged.map((item) => item.label),
    ["I like cats", "Describe a pet", "Pets"],
  )
})
