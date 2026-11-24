import assert from "node:assert/strict"
import test from "node:test"

import {
  PLACEMENT_BAND_ORDER,
  placementBandLabel,
  placementLimitationLabel,
} from "../src/lib/placement.ts"

test("档位顺序固定为 KET → PET → CET4 → ADVANCED", () => {
  assert.deepEqual(PLACEMENT_BAND_ORDER, ["KET", "PET", "CET4", "ADVANCED"])
})

test("已知档位返回双语标签，未知档位回退代码本身", () => {
  assert.equal(placementBandLabel("KET").zh, "KET（基础）")
  assert.equal(
    placementBandLabel("ADVANCED").en,
    "Academic / IELTS-TOEFL (Advanced)",
  )
  const fallback = placementBandLabel("NOPE")
  assert.equal(fallback.zh, "NOPE")
  assert.equal(fallback.en, "NOPE")
})

test("素材限制：none/空为 null，material_limited 出说明，未知标识回退", () => {
  assert.equal(placementLimitationLabel("none"), null)
  assert.equal(placementLimitationLabel(null), null)
  assert.equal(placementLimitationLabel(undefined), null)

  const limited = placementLimitationLabel("material_limited")
  assert.ok(limited)
  assert.match(limited.zh, /素材有限/)
  assert.match(limited.en, /Limited material/)

  const unknown = placementLimitationLabel("some_other_flag")
  assert.ok(unknown)
  assert.equal(unknown.zh, "some_other_flag")
})
