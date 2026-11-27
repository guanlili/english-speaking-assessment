import assert from "node:assert/strict"
import test from "node:test"
import type { ModuleKey } from "../src/hooks/useModules.ts"
import {
  filterItemsByModule,
  isModuleReadonlyState,
} from "../src/lib/module-filter.ts"

type Entry = { path: string; module?: ModuleKey | null }

const entries: Entry[] = [
  { path: "/classrooms", module: null }, // 底座：班级入口
  { path: "/help", module: null }, // 底座：帮助
  { path: "/home/$code", module: "speaking" },
  { path: "/create", module: "speaking" },
  { path: "/vocab/$code", module: "vocabulary" },
  { path: "/admin/vocabbooks", module: "vocabulary" },
]

function paths(keys: ModuleKey[]) {
  const owned = new Set(keys)
  return filterItemsByModule(entries, (key) => owned.has(key)).map(
    (entry) => entry.path,
  )
}

test("双开：口语、单词与底座入口全部保留", () => {
  assert.deepEqual(paths(["speaking", "vocabulary"]), [
    "/classrooms",
    "/help",
    "/home/$code",
    "/create",
    "/vocab/$code",
    "/admin/vocabbooks",
  ])
})

test("只买口语：单词入口隐藏，口语与底座保留", () => {
  assert.deepEqual(paths(["speaking"]), [
    "/classrooms",
    "/help",
    "/home/$code",
    "/create",
  ])
})

test("只买单词：口语入口隐藏，单词与底座保留", () => {
  assert.deepEqual(paths(["vocabulary"]), [
    "/classrooms",
    "/help",
    "/vocab/$code",
    "/admin/vocabbooks",
  ])
})

test("两模块均未购：仅剩共享底座入口", () => {
  assert.deepEqual(paths([]), ["/classrooms", "/help"])
})

test("只读判定：active 放行；未购/关闭/待生效/到期为只读；缺省按非只读", () => {
  assert.equal(isModuleReadonlyState("active"), false)
  for (const state of ["not_granted", "disabled", "scheduled", "expired"]) {
    assert.equal(isModuleReadonlyState(state), state !== "active")
  }
  assert.equal(isModuleReadonlyState(undefined), false)
  assert.equal(isModuleReadonlyState(null), false)
})
