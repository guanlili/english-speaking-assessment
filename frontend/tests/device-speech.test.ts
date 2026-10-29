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

test("split sentences with per-sentence audio count as voiced", () => {
  const flagged = itemsUsingDeviceSpeech(
    passageSpeechItems({
      title: "Pets",
      audioUrl: null,
      readingSplit: true,
      segments: ["I have a cat.", "It is small.", "It likes fish."],
      sentenceAudio: {
        "I have a cat.": "/audio/content/cat.wav",
        "It likes fish.": "/audio/content/fish.wav",
      },
    }),
  )
  // 只有未配音的句子计为缺音；已配音句子不再被误报
  assert.deepEqual(
    flagged.map((item) => item.label),
    ["It is small."],
  )
  // 全部句子配音后零打扰
  const allVoiced = itemsUsingDeviceSpeech(
    passageSpeechItems({
      title: "Pets",
      readingSplit: true,
      segments: ["A.", "B."],
      sentenceAudio: { "A.": "/audio/a.wav", "B.": "/audio/b.wav" },
    }),
  )
  assert.deepEqual(allVoiced, [])
})
