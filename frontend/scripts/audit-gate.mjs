#!/usr/bin/env node
// 前端依赖审计闸门（CI 用）：在 npm audit 之上加「按 advisory 豁免」能力。
//
// 为什么需要：npm audit 只看等级，没有豁免机制。遇到上游「已收录但尚无修复版本」
// 的 advisory（如 picomatch CVE-2026-112366，patched versions: None，经
// vite / tinyglobby / fdir / unplugin / @tanstack/router-* 传导），整个仓库的
// CI 会一直红，而事实上没有任何可升的版本——闸门失去意义，还会挡住无关交付。
//
// 规则：
//   - IGNORED 里的 advisory 视为已评估，不算失败（连带被它传导的包一并豁免）
//   - 豁免必须写到期日；过期后闸门直接失败，强制复查（避免豁免变永久后门）
//   - 其它任何 high / critical 一律失败
//
// 用法：node scripts/audit-gate.mjs [--json]

import { execFileSync } from "node:child_process"

// 已评估并接受风险的 advisory。加条目必须同时写清原因与复查日期。
const IGNORED = [
  {
    id: "GHSA-fc5q-39xc-vjpf",
    package: "picomatch",
    reason:
      "ReDoS（CVE-2026-112366），影响 <= 4.0.7；上游 patched versions 为 None，" +
      "目前无任何可升版本。仅出现在构建期工具链（vite/tailwind 构建、vitest），" +
      "不进入浏览器运行时产物。等 picomatch 发布修复版后移除本条并升级。",
    reviewBy: "2026-12-09",
  },
]

const SEVERITY_FAIL = new Set(["high", "critical"])

// AUDIT_GATE_STRICT=1：忽略豁免，按裸 npm audit 口径判定
// （用于随时复查「当前到底有哪些高危被豁免」）
const STRICT = process.env.AUDIT_GATE_STRICT === "1"
const activeIgnores = STRICT ? [] : IGNORED

function audit() {
  try {
    return JSON.parse(
      execFileSync(
        "npm",
        [
          "audit",
          "--package-lock-only",
          "--json",
          "--registry=https://registry.npmjs.org",
        ],
        { encoding: "utf8", maxBuffer: 16 * 1024 * 1024 },
      ),
    )
  } catch (error) {
    // npm audit 有漏洞时以非零退出，但 JSON 仍在 stdout
    if (error.stdout) return JSON.parse(error.stdout)
    throw error
  }
}

function main() {
  const today = new Date().toISOString().slice(0, 10)
  const expired = activeIgnores.filter((item) => today > item.reviewBy)
  if (expired.length) {
    console.error("❌ 审计豁免已过期，请复查后更新 reviewBy：")
    for (const item of expired) {
      console.error(`   ${item.id}（${item.package}）到期日 ${item.reviewBy}`)
    }
    process.exit(1)
  }

  const result = audit()
  const vulns = result.vulnerabilities || {}
  const ignoredIds = new Set(activeIgnores.map((item) => item.id))

  // 传导解释：某个包的 via 只有「已豁免的 advisory」或「已被解释的上游包」时，一并豁免
  const explained = new Set()
  let changed = true
  while (changed) {
    changed = false
    for (const [name, info] of Object.entries(vulns)) {
      if (explained.has(name)) continue
      const via = info.via || []
      const viaNames = via.filter((v) => typeof v === "string")
      const allClear = via.every((v) =>
        typeof v === "string"
          ? ignoredIds.has(v) || explained.has(v)
          : ignoredIds.has(v?.url?.split("/").pop() ?? ""),
      )
      if (via.every((v) => typeof v === "string") && allClear) {
        // 纯 advisory 引用：全部来自已豁免或已解释的来源
        explained.add(name)
        changed = true
      } else if (viaNames.length === 0 && allClear) {
        explained.add(name)
        changed = true
      }
    }
  }

  const blocking = []
  const waived = []
  for (const [name, info] of Object.entries(vulns)) {
    if (!SEVERITY_FAIL.has(info.severity)) continue
    if (explained.has(name)) {
      waived.push({ name, severity: info.severity, via: info.via })
    } else {
      blocking.push({ name, severity: info.severity, via: info.via })
    }
  }

  for (const item of waived) {
    console.log(
      `⚠️  已豁免（见 scripts/audit-gate.mjs IGNORED）: ${item.name} ${item.severity}`,
    )
  }

  if (blocking.length) {
    console.error(`❌ 发现 ${blocking.length} 个未豁免的高危依赖：`)
    for (const item of blocking) {
      const via = item.via
        .map((v) => (typeof v === "string" ? v : v?.title || v?.name || "?"))
        .join(", ")
      console.error(`   ${item.name} (${item.severity}) ← ${via}`)
    }
    process.exit(1)
  }

  console.log(
    `✅ 审计闸门通过：${blocking.length} 个阻塞项、${waived.length} 个已豁免项`,
  )
}

main()
