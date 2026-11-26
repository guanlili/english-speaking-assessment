import assert from "node:assert/strict"
import test from "node:test"
import type {
  PkMatchItem,
  PkMatchView,
  PkPlayerSummary,
} from "../src/client/types.gen"
import {
  PK_LOBBY_POLL_MS,
  parseSseBuffer,
  pkActiveMatches,
  pkAnswerKey,
  pkLobbyPollInterval,
  pkNextItemIndex,
  pkOutcome,
  pkPhase,
  pkRemainingSeconds,
  pkShouldPolling,
  pkWaitingPlayers,
} from "../src/lib/pk.ts"

const activeMatch = {
  match_id: "m1",
  lobby_id: "l1",
  status: "active",
  state_version: 1,
  question_count: 3,
  current_item_index: 0,
} as unknown as PkMatchView

const finishedMatch = {
  ...activeMatch,
  status: "finished",
  result: { status: "finished", drew: false, winner_student_id: "s1" },
} as unknown as PkMatchView

test("pkPhase: finished match wins over lobby waiting state", () => {
  assert.equal(
    pkPhase({ status: "open", my_status: "waiting" }, finishedMatch),
    "finished",
  )
})

test("pkPhase: active match while waiting in lobby", () => {
  assert.equal(
    pkPhase({ status: "open", my_status: "waiting" }, activeMatch),
    "match",
  )
})

test("pkPhase: closed lobby, waiting, match link, idle", () => {
  assert.equal(pkPhase({ status: "closed" }, null), "closed")
  assert.equal(
    pkPhase({ status: "open", my_status: "waiting" }, null),
    "waiting",
  )
  assert.equal(pkPhase({ status: "open", my_match_id: "m1" }, null), "match")
  assert.equal(pkPhase({ status: "open" }, null), "idle")
})

test("pkNextItemIndex: first unanswered item, all answered returns count", () => {
  const items: PkMatchItem[] = [
    { item_index: 0, answered: true },
    { item_index: 1, answered: false },
    { item_index: 2, answered: false },
  ] as PkMatchItem[]
  assert.equal(pkNextItemIndex(items), 1)
  assert.equal(pkNextItemIndex(undefined), 0)
  assert.equal(
    pkNextItemIndex(items.map((it) => ({ ...it, answered: true }))),
    3,
  )
})

test("pkRemainingSeconds: null/negative/rounding", () => {
  assert.equal(pkRemainingSeconds(null), 0)
  assert.equal(pkRemainingSeconds(undefined), 0)
  assert.equal(pkRemainingSeconds(-3), 0)
  assert.equal(pkRemainingSeconds(12.6), 13)
})

test("pkShouldPolling: closed SSE or stale event forces polling", () => {
  const now = 10_000
  assert.equal(pkShouldPolling({ sseOpen: false, lastEventAt: now, now }), true)
  assert.equal(pkShouldPolling({ sseOpen: true, lastEventAt: null, now }), true)
  assert.equal(
    pkShouldPolling({ sseOpen: true, lastEventAt: now - 2000, now }),
    true,
  )
  assert.equal(
    pkShouldPolling({ sseOpen: true, lastEventAt: now - 500, now }),
    false,
  )
})

test("pkLobbyPollInterval: only polls while waiting; stops once matched/left/unknown", () => {
  assert.equal(pkLobbyPollInterval({ my_status: "waiting" }), PK_LOBBY_POLL_MS)
  assert.equal(
    pkLobbyPollInterval({ my_status: "active", my_match_id: "m1" }),
    false,
  )
  assert.equal(pkLobbyPollInterval({ status: "open" }), false)
  assert.equal(pkLobbyPollInterval({ my_status: null }), false)
  assert.equal(pkLobbyPollInterval(null), false)
  assert.equal(pkLobbyPollInterval(undefined), false)
})

test("pkOutcome: win/lose/drew/none", () => {
  assert.equal(pkOutcome(finishedMatch.result, "s1"), "win")
  assert.equal(pkOutcome(finishedMatch.result, "s2"), "lose")
  const drew = {
    status: "finished",
    drew: true,
    winner_student_id: null,
  } as PkMatchView["result"]
  assert.equal(pkOutcome(drew, "s1"), "drew")
  assert.equal(pkOutcome(null, "s1"), "none")
  const ongoing = {
    status: "active",
    drew: false,
    winner_student_id: null,
  } as PkMatchView["result"]
  assert.equal(pkOutcome(ongoing, "s1"), "none")
})

test("pkAnswerKey: stable per match/player/item/attempt", () => {
  assert.equal(
    pkAnswerKey("m1", "11111111-2222-3333-4444-555555555555", 2, 1),
    "m1:11111111:2:1",
  )
  assert.notEqual(
    pkAnswerKey("m1", "11111111-2222-3333-4444-555555555555", 2, 1),
    pkAnswerKey("m1", "99999999-8888-7777-6666-555555555555", 2, 1),
  )
  assert.notEqual(
    pkAnswerKey("m1", "11111111-2222-3333-4444-555555555555", 2, 1),
    pkAnswerKey("m1", "11111111-2222-3333-4444-555555555555", 2, 2),
  )
  assert.equal(pkAnswerKey("m1", null, 2, 1), "m1:anon:2:1")
  const real = pkAnswerKey(
    "00000000-0000-4000-8000-000000000000",
    "00000000-0000-4000-8000-000000000001",
    12,
    1,
  )
  assert.ok(real.length <= 64, `key too long: ${real}`)
})

test("parseSseBuffer: splits completed blocks, keeps partial tail", () => {
  const first = 'event: state\ndata: {"v":1}\n\n'
  const second = 'event: state\ndata: {"v":2}\n'
  const { events, rest } = parseSseBuffer(first + second)
  assert.equal(events.length, 1)
  assert.equal(events[0], 'event: state\ndata: {"v":1}')
  assert.equal(rest, 'event: state\ndata: {"v":2}\n')
})

test("parseSseBuffer: CRLF normalized and blank blocks dropped", () => {
  const { events, rest } = parseSseBuffer(
    "event: ping\r\ndata: {}\r\n\r\n\r\nevent: ping\r\n",
  )
  assert.deepEqual(events, ["event: ping\ndata: {}"])
  assert.equal(rest, "event: ping\n")
})

const player = (over: Partial<PkPlayerSummary>): PkPlayerSummary => ({
  student_id: "s1",
  status: "waiting",
  ...over,
})

test("pkWaitingPlayers: keeps only waiting, preserves order", () => {
  const players = [
    player({ student_id: "s1" }),
    player({ student_id: "s2", status: "active", match_id: "m1" }),
    player({ student_id: "s3" }),
  ]
  const waiting = pkWaitingPlayers(players)
  assert.deepEqual(
    waiting.map((p) => p.student_id),
    ["s1", "s3"],
  )
  assert.deepEqual(pkWaitingPlayers(undefined), [])
})

test("pkActiveMatches: groups active players by match_id, skips waiting and null match", () => {
  const players = [
    player({ student_id: "a", status: "active", match_id: "m1", score: 80 }),
    player({ student_id: "b", status: "active", match_id: "m1", score: 60 }),
    player({ student_id: "c", status: "active", match_id: "m2", score: 100 }),
    player({ student_id: "d", status: "waiting" }),
    player({ student_id: "e", status: "active", match_id: null }),
  ]
  const matches = pkActiveMatches(players)
  assert.equal(matches.length, 2)
  assert.deepEqual(matches[0].matchId, "m1")
  assert.deepEqual(
    matches[0].players.map((p) => p.student_id),
    ["a", "b"],
  )
  assert.deepEqual(matches[1].matchId, "m2")
  assert.deepEqual(
    matches[1].players.map((p) => p.student_id),
    ["c"],
  )
  assert.deepEqual(pkActiveMatches(undefined), [])
})
