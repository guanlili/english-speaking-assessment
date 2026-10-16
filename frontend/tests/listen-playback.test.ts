import assert from "node:assert/strict"
import { test } from "node:test"

import {
  mayControlPlayback,
  playbackAfterSignal,
} from "../src/lib/listen-playback.ts"

test("an error after playback starts clears the playing state", () => {
  const started = playbackAfterSignal(false, "start")
  const failed = playbackAfterSignal(started.playing, "error")
  assert.equal(started.playing, true)
  assert.equal(started.notify, false)
  assert.equal(failed.playing, false)
  assert.equal(failed.notify, true)
})

test("a late request cannot control a different item", () => {
  assert.equal(mayControlPlayback(false, "a", "a"), false)
  assert.equal(mayControlPlayback(true, "a", "b"), false)
  assert.equal(mayControlPlayback(true, "b", "b"), true)
})
