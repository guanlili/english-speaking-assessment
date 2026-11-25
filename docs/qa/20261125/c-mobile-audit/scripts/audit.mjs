/**
 * #517 移动端真机级审计 — 本地 CDP 模拟驱动脚本（第一阶段）。
 *
 * 口径（与 README 一致）：
 * - 证据全部来自本 worktree dev 前端（5181 → 本地后端 8034 → 本机 Postgres 5433），不连生产。
 * - 视口由 Playwright/Chrome CDP 设备模拟（isMobile + hasTouch），**不是真机**；
 *   凡「真机」结论必须另有真实设备/桌面缩放证据，本脚本产出一律标注 simulated。
 *
 * 用法（在 frontend 目录下执行，以便解析 node_modules）：
 *   node ../docs/qa/20261125/c-mobile-audit/scripts/audit.mjs smoke
 *   node ../docs/qa/20261125/c-mobile-audit/scripts/audit.mjs matrix
 */
import { createRequire } from "node:module"
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const FRONTEND_DIR = path.resolve(__dirname, "../../../../..", "frontend")
const require = createRequire(path.join(FRONTEND_DIR, "package.json"))
const { chromium } = require("@playwright/test")

const BASE_URL = process.env.AUDIT_BASE_URL ?? "http://127.0.0.1:5181"
const OUT_DIR = path.resolve(__dirname, "..")
const SHOT_DIR = path.join(OUT_DIR, "screenshots")

const STUDENT_ID = "b2776fe2-d4db-41e1-af82-9bafa97e552e" // DEMO01 演示学生（本地合成数据）

/** 路由矩阵。critical=true 的页面跑 4 宽 × 中英全量；其余跑 390 中英 + 320/430 冒烟。 */
const ROUTES = [
  { key: "login", path: "/login", role: "public", critical: true },
  { key: "student-home", path: "/home/DEMO01", role: "student", critical: true },
  { key: "student-practice", path: "/p/DEMO01", role: "student", critical: true },
  { key: "vocab-index", path: "/vocab/DEMO01", role: "student", critical: true },
  { key: "vocab-placement", path: "/vocab/DEMO01/placement", role: "student", critical: false },
  { key: "vocab-self", path: "/vocab/DEMO01/self", role: "student", critical: true },
  { key: "vocab-leaderboard", path: "/vocab/DEMO01/leaderboard", role: "student", critical: true },
  { key: "vocab-books", path: "/vocab/DEMO01/books", role: "student", critical: true },
  { key: "vocab-records", path: "/vocab/DEMO01/records", role: "student", critical: false },
  { key: "teacher-board", path: "/t/DEMO01", role: "teacher", critical: true },
  { key: "teacher-vocab", path: "/t/DEMO01/vocab", role: "teacher", critical: true },
  { key: "teacher-results", path: "/t/DEMO01/vocab?tab=results", role: "teacher", critical: false },
  { key: "teacher-trend", path: "/t/DEMO01/vocab?tab=trend", role: "teacher", critical: false },
  { key: "teacher-placement", path: "/t/DEMO01/vocab?tab=placement", role: "teacher", critical: false },
  { key: "teacher-pk", path: "/t/DEMO01/vocab?tab=pk", role: "teacher", critical: false },
  { key: "teacher-farm", path: "/t/DEMO01/vocab?tab=farm", role: "teacher", critical: false },
  { key: "teacher-review", path: "/t/DEMO01/vocab?tab=review", role: "teacher", critical: false },
  { key: "teacher-vocabboard", path: "/t/DEMO01/vocab?tab=leaderboard", role: "teacher", critical: false },
  { key: "teacher-student", path: `/t/DEMO01/s/${STUDENT_ID}`, role: "teacher", critical: true },
  { key: "admin-dashboard", path: "/admin/dashboard", role: "operator", critical: true },
  { key: "admin-vocabbooks", path: "/admin/vocabbooks", role: "operator", critical: true },
  { key: "admin-licenses", path: "/admin/vocabulary-licenses", role: "operator", critical: true, reveal: ".overflow-x-auto" },
  { key: "admin-users", path: "/admin", role: "operator", critical: false },
  { key: "admin-schools", path: "/admin/schools", role: "operator", critical: false },
]

const PORTRAIT = [
  { width: 320, height: 568, orient: "portrait" },
  { width: 360, height: 640, orient: "portrait" },
  { width: 390, height: 844, orient: "portrait" },
  { width: 430, height: 932, orient: "portrait" },
]
const LANDSCAPE = [{ width: 844, height: 390, orient: "landscape" }]

async function setLang(page, lang) {
  await page.addInitScript((langValue) => {
    localStorage.setItem("esa:lang", langValue)
  }, lang)
}

async function loginTeacher(context) {
  const page = await context.newPage()
  await page.goto(`${BASE_URL}/login`)
  await page.getByText(/本地演示体验|Local demo/).click()
  await page.getByRole("button", { name: /教师演示|Teacher demo/ }).click()
  await page.waitForURL((url) => url.pathname.startsWith("/t/"), { timeout: 15_000 })
  await page.close()
}

async function loginOperator(context) {
  const page = await context.newPage()
  await page.goto(`${BASE_URL}/login`)
  await page.getByText(/本地演示体验|Local demo/).click()
  await page.getByRole("button", { name: /运营演示|Operator demo/ }).click()
  await page.waitForURL((url) => url.pathname.includes("/admin"), { timeout: 15_000 })
  await page.close()
}

async function loginStudent(context) {
  const page = await context.newPage()
  await page.goto(`${BASE_URL}/login`)
  await page.getByRole("tab", { name: /学生登录|Student/ }).click()
  await page.getByPlaceholder(/学号|Student ID/).fill("student")
  const pwdInput = page.getByTestId("student-password-input")
  for (const pwd of ["demo1234", "brs123456"]) {
    await pwdInput.fill(pwd)
    await page.getByRole("button", { name: /登录|Sign in/ }).click()
    try {
      await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 8_000 })
      break
    } catch {
      // try next password
    }
  }
  // 建立本地学生身份（幂等入班）
  await page.goto(`${BASE_URL}/j/DEMO01`)
  const hasIdentity = await page
    .waitForFunction(
      () => localStorage.getItem("esa:student:DEMO01") !== null,
      undefined,
      { timeout: 8_000, polling: 250 },
    )
    .then(() => true)
    .catch(() => false)
  if (!hasIdentity) {
    const joinBtn = page.getByRole("button", { name: /进入课堂|Join class/ })
    if (await joinBtn.count()) {
      await joinBtn.click()
      await page.waitForFunction(
        () => localStorage.getItem("esa:student:DEMO01") !== null,
        undefined,
        { timeout: 8_000 },
      )
    }
  }
  await page.close()
}

/** 采集单页指标：横向溢出、触控目标、控件字号、固定底栏安全区。 */
async function collectMetrics(page) {
  return page.evaluate(() => {
    const doc = document.documentElement
    const vw = doc.clientWidth
    const offenders = []
    const targets = []
    const smallFonts = []
    const isVisible = (el) => {
      const r = el.getBoundingClientRect()
      if (r.width === 0 || r.height === 0) return false
      const cs = getComputedStyle(el)
      if (cs.display === "none" || cs.visibility === "hidden") return false
      return el.offsetParent !== null || cs.position === "fixed"
    }
    const clippedByAncestor = (el) => {
      let cur = el.parentElement
      while (cur) {
        const ox = getComputedStyle(cur).overflowX
        if (["auto", "scroll", "clip", "hidden"].includes(ox)) return true
        cur = cur.parentElement
      }
      return false
    }
    document.querySelectorAll("*").forEach((el) => {
      if (!isVisible(el)) return
      const r = el.getBoundingClientRect()
      if ((r.right > vw + 1 || r.width > vw + 1) && !clippedByAncestor(el)) {
        offenders.push({
          tag: el.tagName.toLowerCase(),
          cls: String(el.className ?? "").slice(0, 80),
          right: Math.round(r.right),
          width: Math.round(r.width),
        })
      }
    })
    const targetSel = "a,button,input,select,textarea,[role=button],[role=tab],[role=link]"
    document.querySelectorAll(targetSel).forEach((el) => {
      if (!isVisible(el)) return
      const r = el.getBoundingClientRect()
      const label =
        (el.innerText || el.getAttribute("aria-label") || el.getAttribute("placeholder") || "").trim().slice(0, 28)
      if (/devtool|DevTools|Skip to main|跳到主要内容|跳至主要内容/i.test(label)) return
      if (el.classList.contains("sr-only")) return
      if (r.height < 44 || r.width < 44) {
        targets.push({
          tag: el.tagName.toLowerCase(),
          label,
          w: Math.round(r.width),
          h: Math.round(r.height),
        })
      }
    })
    document.querySelectorAll("input,select,textarea").forEach((el) => {
      if (!isVisible(el)) return
      const type = el.getAttribute("type")
      if (type === "checkbox" || type === "radio" || type === "hidden") return
      const fs = parseFloat(getComputedStyle(el).fontSize)
      if (fs < 16) smallFonts.push({ tag: el.tagName.toLowerCase(), type, fs })
    })
    const meta = document.querySelector('meta[name="viewport"]')?.getAttribute("content") ?? ""
    const fixedBottom = [...document.querySelectorAll("footer,nav,div")]
      .filter((el) => {
        const pos = getComputedStyle(el).position
        const b = getComputedStyle(el).bottom
        return pos === "fixed" && b === "0px"
      })
      .map((el) => {
        const cs = getComputedStyle(el)
        return { cls: String(el.className ?? "").slice(0, 60), safeArea: cs.paddingBottom }
      })
    return {
      vw,
      scrollWidth: doc.scrollWidth,
      overflow: doc.scrollWidth - vw,
      offenders: offenders.slice(0, 25),
      targets: targets.slice(0, 40),
      smallFonts: smallFonts.slice(0, 20),
      fixedBottom,
      viewportMeta: meta,
      zoomLocked: /maximum-scale\s*=\s*1|user-scalable\s*=\s*no/i.test(meta),
    }
  })
}

/** 交互式动作：打开弹窗 / 展开内联面板后再截图与采集指标。 */
const ACTIONS = [
  {
    key: "dialog-add-user",
    role: "operator",
    path: "/admin",
    trigger: { kind: "button", name: /添加用户|Add User/ },
    langs: ["zh", "en"],
    widths: [390, 320],
  },
  {
    key: "inline-new-book",
    role: "teacher",
    path: "/t/DEMO01/vocab",
    trigger: { kind: "button", name: /新建班级词库|New classroom book/ },
    langs: ["zh", "en"],
    widths: [390, 320],
  },
  {
    key: "book-detail",
    role: "student",
    path: "/vocab/DEMO01/books",
    trigger: { kind: "first-book" },
    langs: ["zh", "en"],
    widths: [390, 320],
  },
  {
    key: "sidebar-nav",
    role: "operator",
    path: "/admin/vocabulary-licenses",
    trigger: { kind: "sidebar" },
    langs: ["zh", "en"],
    widths: [390, 320],
  },
]

async function shootAction(context, action, viewport, lang) {
  const page = await context.newPage()
  await setLang(page, lang)
  await page.setViewportSize({ width: viewport.width, height: viewport.height })
  const errors = []
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)))
  let status = "PASS"
  let metrics = null
  let finalPath = ""
  let note = ""
  try {
    await page.goto(`${BASE_URL}${action.path}`, { waitUntil: "networkidle", timeout: 20_000 })
    await page.waitForTimeout(500)
    if (action.trigger.kind === "button") {
      const btn = page.getByRole("button", { name: action.trigger.name })
      if (await btn.count()) {
        await btn.first().click()
        await page.waitForTimeout(600)
      } else {
        note = "trigger-not-found"
        status = "SKIP"
      }
    } else if (action.trigger.kind === "sidebar") {
      const trigger = page.getByRole("button", { name: /切换导航栏|Toggle navigation/ })
      if (await trigger.count()) {
        await trigger.first().click()
        await page.waitForTimeout(600)
      } else {
        note = "sidebar-trigger-not-found"
        status = "SKIP"
      }
    } else if (action.trigger.kind === "first-book") {
      const card = page.locator("li button").first()
      if (await card.count()) {
        await card.click()
        await page.waitForTimeout(600)
      } else {
        note = "no-book-card"
        status = "SKIP"
      }
    }
    metrics = await collectMetrics(page)
    if (metrics.overflow > 1) status = "FAIL"
    const suffix = viewport.orient === "landscape" ? "-land" : ""
    const file = `${action.key}-${lang}-${viewport.width}${suffix}.png`
    await page.screenshot({ path: path.join(SHOT_DIR, file), fullPage: false })
    finalPath = file
  } catch (err) {
    status = "ERROR"
    metrics = { error: String(err).slice(0, 200) }
  }
  await page.close()
  return { route: action.key, path: action.path, role: action.role, lang, viewport, status, metrics, shot: finalPath, note, errors }
}

async function shoot(context, route, viewport, lang, label) {
  const page = await context.newPage()
  await setLang(page, lang)
  await page.setViewportSize({ width: viewport.width, height: viewport.height })
  const errors = []
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)))
  let status = "PASS"
  let metrics = null
  let finalPath = ""
  try {
    await page.goto(`${BASE_URL}${route.path}`, { waitUntil: "networkidle", timeout: 20_000 })
    await page.waitForTimeout(600)
    metrics = await collectMetrics(page)
    if (metrics.overflow > 1) status = "FAIL"
    const suffix = viewport.orient === "landscape" ? "-land" : ""
    const file = `${route.key}-${lang}-${viewport.width}${suffix}.png`
    await page.screenshot({ path: path.join(SHOT_DIR, file), fullPage: false })
    finalPath = file
    // 指定 reveal 选择器时，滚动到目标（如表格）补一张截图作为下方区域证据。
    if (route.reveal) {
      const target = page.locator(route.reveal).first()
      if (await target.count()) {
        await target.scrollIntoViewIfNeeded({ timeout: 5_000 })
        await page.waitForTimeout(400)
        const tableFile = `${route.key}-${lang}-${viewport.width}${suffix}-table.png`
        await page.screenshot({ path: path.join(SHOT_DIR, tableFile), fullPage: false })
      }
    }
  } catch (err) {
    status = "ERROR"
    metrics = { error: String(err).slice(0, 200) }
  }
  await page.close()
  return { route: route.key, path: route.path, role: route.role, lang, viewport, label, status, metrics, shot: finalPath, errors }
}

async function main() {
  const mode = process.argv[2] ?? "smoke"
  fs.mkdirSync(SHOT_DIR, { recursive: true })

  const browser = await chromium.launch({ channel: "chrome", headless: true })
  const contexts = {}
  try {
    // 三类角色各开一个上下文（登录态隔离）
    for (const role of ["student", "teacher", "operator", "public"]) {
      const ctx = await browser.newContext({
        viewport: { width: 390, height: 844 },
        deviceScaleFactor: 2,
        isMobile: true,
        hasTouch: true,
        locale: "zh-CN",
      })
      contexts[role] = ctx
    }
    await loginStudent(contexts.student)
    await loginTeacher(contexts.teacher)
    await loginOperator(contexts.operator)

    const results = []
    if (mode === "interactive") {
      for (const action of ACTIONS) {
        for (const w of action.widths) {
          const vp = PORTRAIT.find((p) => p.width === w)
          for (const lang of action.langs) {
            const r = await shootAction(contexts[action.role], action, vp, lang)
            results.push(r)
            console.log(`${r.status.padEnd(5)} ${action.key} ${lang} ${w}${r.note ? ` (${r.note})` : ""}`)
          }
        }
      }
    } else {
    const smokeVps = [PORTRAIT[0], PORTRAIT[2], PORTRAIT[3]]
    for (const route of ROUTES) {
      const ctx = contexts[route.role]
      const vps = mode === "matrix" && route.critical ? [...PORTRAIT, ...LANDSCAPE] : smokeVps
      for (const vp of vps) {
        for (const lang of ["zh", "en"]) {
          const r = await shoot(ctx, route, vp, lang, route.key)
          results.push(r)
          console.log(
            `${r.status.padEnd(5)} ${route.key} ${lang} ${vp.width}x${vp.height}${vp.orient === "landscape" ? " land" : ""}` +
              (metricsOverflow(r.metrics) ? ` overflow=${metricsOverflow(r.metrics)}` : ""),
          )
        }
      }
    }
    }
    const report = {
      generatedAt: new Date().toISOString(),
      baseUrl: BASE_URL,
      environment: "local dev, Chrome CDP emulation (simulated, NOT a real device)",
      mode,
      results,
    }
    const reportFile = mode === "interactive" ? "audit-interactive.json" : "audit.json"
    fs.writeFileSync(path.join(OUT_DIR, reportFile), JSON.stringify(report, null, 2))
  } finally {
    await browser.close()
  }
}

function metricsOverflow(m) {
  return m && typeof m.overflow === "number" ? m.overflow : null
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
