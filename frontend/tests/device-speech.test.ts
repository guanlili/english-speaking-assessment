import assert from "node:assert/strict"
import { test } from "node:test"

import {
  itemsUsingDeviceSpeech,
  passageSpeechItems,
} from "../src/lib/device-speech.ts"

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

test("split articles do not inherit the whole-passage audio", () => {
  const flagged = itemsUsingDeviceSpeech(
    passageSpeechItems({
      title: "Pets",
      audioUrl: "/audio/pets.wav",
      readingSplit: true,
      segments: ["I have a cat.", "It is small."],
    }),
  )
  assert.deepEqual(
    flagged.map((item) => item.label),
    ["I have a cat.", "It is small."],
  )
  const whole = itemsUsingDeviceSpeech(
    passageSpeechItems({
      title: "Pets",
      audioUrl: "/audio/pets.wav",
      readingSplit: false,
      segments: ["I have a cat.", "It is small."],
    }),
  )
  assert.deepEqual(whole, [])
})
