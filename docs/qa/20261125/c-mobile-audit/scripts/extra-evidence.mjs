/**
 * #517 C 块第二阶段补充取证：桌面缩放 / WebKit 内核 / 软键盘模拟 / 长列表可达。
 *
 * 口径（与 README 一致，禁止混标）：
 * - `zoom`：系统 Chrome 桌面引擎，200% 缩放按「CSS 视口折半 + deviceScaleFactor 2」模拟；
 *   标注 real-chrome-zoom，仍非真机 pinch 缩放。
 * - `webkit`：Playwright WebKit 27 引擎（Safari 同内核），headless；标注 real-webkit，
 *   不是 Safari.app 真机。Safari.app 走 safaridriver 的链路见 README 阻塞说明。
 * - `keyboard`：CDP 无真实软键盘，用 visualViewport + 输入聚焦模拟；标注 sim-keyboard。
 * - `longlist`：长列表顶部 / 底部可达性取证；标注 sim-longlist。
 *
 * 用法（在 frontend 目录下执行）：
 *   node ../docs/qa/20261125/c-mobile-audit/scripts/extra-evidence.mjs zoom
 *   node ../docs/qa/20261125/c-mobile-audit/scripts/extra-evidence.mjs webkit
 *   node ../docs/qa/20261125/c-mobile-audit/scripts/extra-evidence.mjs keyboard
 *   node ../docs/qa/20261125/c-mobile-audit/scripts/extra-evidence.mjs longlist
 */
import { createRequire } from "node:module"
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const FRONTEND_DIR = path.resolve(__dirname, "../../../../..", "frontend")
const require = createRequire(path.join(FRONTEND_DIR, "package.json"))
const { chromium, webkit } = require("@playwright/test")

const BASE_URL = process.env.AUDIT_BASE_URL ?? "http://127.0.0.1:5181"
const OUT_DIR = path.resolve(__dirname, "..")
const SHOT_DIR = path.join(OUT_DIR, "screenshots")

const PAGES = [
  { key: "login", path: "/login", role: "public" },
  { key: "student-home", path: "/home/DEMO01", role: "student" },
  { key: "vocab-index", path: "/vocab/DEMO01", role: "student" },
  { key: "teacher-board", path: "/t/DEMO01", role: "teacher" },
  { key: "teacher-vocab", path: "/t/DEMO01/vocab", role: "teacher" },
  { key: "admin-dashboard", path: "/admin/dashboard", role: "operator" },
  { key: "admin-licenses", path: "/admin/vocabulary-licenses", role: "operator" },
]

function setLang(page, lang) {
  return page.addInitScript((langValue) => {
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
  // WebKit 下上一跳尚未落定时 goto 可能中断，容错继续，再靠 waitForFunction 校验身份。
  await page.goto(`${BASE_URL}/j/DEMO01`, { waitUntil: "domcontentloaded", timeout: 10_000 }).catch(() => {})
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
        offenders.push({ tag: el.tagName.toLowerCase(), right: Math.round(r.right), width: Math.round(r.width) })
      }
    })
    document.querySelectorAll("a,button,input,select,textarea,[role=button],[role=tab],[role=link]").forEach((el) => {
      if (!isVisible(el)) return
      const r = el.getBoundingClientRect()
      const label = (el.innerText || el.getAttribute("aria-label") || el.getAttribute("placeholder") || "").trim().slice(0, 28)
      if (/devtool|DevTools|Skip to main|跳到主要内容|跳至主要内容/i.test(label)) return
      if (el.classList.contains("sr-only")) return
      if (r.height < 44 || r.width < 44) {
        targets.push({ tag: el.tagName.toLowerCase(), label, w: Math.round(r.width), h: Math.round(r.height) })
      }
    })
    document.querySelectorAll("input,select,textarea").forEach((el) => {
      if (!isVisible(el)) return
      const type = el.getAttribute("type")
      if (type === "checkbox" || type === "radio" || type === "hidden") return
      const fs = parseFloat(getComputedStyle(el).fontSize)
      if (fs < 16) smallFonts.push({ tag: el.tagName.toLowerCase(), type, fs })
    })
    return { vw, scrollWidth: doc.scrollWidth, overflow: doc.scrollWidth - vw, offenders: offenders.slice(0, 25), targets: targets.slice(0, 40), smallFonts: smallFonts.slice(0, 20) }
  })
}

async function shootPage(context, pageDef, viewport, lang, prefix, extra = {}) {
  const page = await context.newPage()
  await setLang(page, lang)
  await page.setViewportSize({ width: viewport.width, height: viewport.height })
  const errors = []
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)))
  const record = { route: pageDef.key, path: pageDef.path, role: pageDef.role, lang, viewport, status: "PASS", metrics: null, shot: "", errors, ...extra }
  try {
    await page.goto(`${BASE_URL}${pageDef.path}`, { waitUntil: "networkidle", timeout: 20_000 })
    await page.waitForTimeout(600)
    record.metrics = await collectMetrics(page)
    if (record.metrics.overflow > 1) record.status = "FAIL"
    const file = `${prefix}-${pageDef.key}-${lang}-${viewport.width}.png`
    await page.screenshot({ path: path.join(SHOT_DIR, file), fullPage: false })
    record.shot = file
  } catch (err) {
    record.status = "ERROR"
    record.metrics = { error: String(err).slice(0, 200) }
  }
  await page.close()
  return record
}

async function runZoom() {
  // 桌面基准 1280×900，200% 缩放后 CSS 视口折半为 640×450；取 640×900 纵向观察头部/卡片/表格。
  const viewport = { width: 640, height: 900 }
  const browser = await chromium.launch({ channel: "chrome", headless: true })
  const contexts = {}
  const results = []
  try {
    for (const role of ["student", "teacher", "operator", "public"]) {
      contexts[role] = await browser.newContext({ viewport, deviceScaleFactor: 2, locale: "zh-CN" })
    }
    await loginStudent(contexts.student)
    await loginTeacher(contexts.teacher)
    await loginOperator(contexts.operator)
    for (const pageDef of PAGES) {
      for (const lang of ["zh", "en"]) {
        const r = await shootPage(contexts[pageDef.role], pageDef, viewport, lang, "real-chrome-zoom", {
          evidence: "系统 Chrome 桌面引擎；200% 缩放按 CSS 视口折半 + DSR2 模拟，非真机 pinch",
        })
        results.push(r)
        console.log(`${r.status.padEnd(5)} zoom ${pageDef.key} ${lang}`)
      }
    }
  } finally {
    await browser.close()
  }
  fs.writeFileSync(path.join(OUT_DIR, "zoom.json"), JSON.stringify({ generatedAt: new Date().toISOString(), baseUrl: BASE_URL, environment: "system Chrome desktop, 200% zoom simulated via halved CSS viewport + DSR2 (NOT real pinch)", results }, null, 2))
}

async function runWebKit() {
  const viewport = { width: 390, height: 844 }
  const browser = await webkit.launch({ headless: true })
  const contexts = {}
  const results = []
  try {
    for (const role of ["student", "teacher", "operator", "public"]) {
      contexts[role] = await browser.newContext({ viewport, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "zh-CN" })
    }
    await loginStudent(contexts.student)
    await loginTeacher(contexts.teacher)
    await loginOperator(contexts.operator)
    for (const pageDef of PAGES) {
      for (const lang of ["zh", "en"]) {
        const r = await shootPage(contexts[pageDef.role], pageDef, viewport, lang, "real-webkit", {
          evidence: "Playwright WebKit 27 引擎（Safari 同内核）headless；非 Safari.app 真机",
        })
        results.push(r)
        console.log(`${r.status.padEnd(5)} webkit ${pageDef.key} ${lang}`)
      }
    }
  } finally {
    await browser.close()
  }
  fs.writeFileSync(path.join(OUT_DIR, "webkit.json"), JSON.stringify({ generatedAt: new Date().toISOString(), baseUrl: BASE_URL, environment: "Playwright WebKit 27 (Safari-family engine), headless; NOT Safari.app device", results }, null, 2))
}

async function runKeyboard() {
  // 软键盘无法在 CDP 真实唤起：聚焦输入框后读 visualViewport，检查主按钮是否仍在可视区内。
  const viewport = { width: 390, height: 844 }
  const browser = await chromium.launch({ channel: "chrome", headless: true })
  const contexts = {}
  const results = []
  const kbdPages = [
    { key: "login", path: "/login", role: "public", input: 'input[type="password"]', submitTexts: ["登录", "Sign in"] },
    { key: "admin-licenses", path: "/admin/vocabulary-licenses", role: "operator", input: "#license-filter-tenant", submitTexts: ["导出 CSV", "Export CSV"] },
  ]
  try {
    for (const role of ["operator", "public"]) {
      contexts[role] = await browser.newContext({ viewport, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "zh-CN" })
    }
    await loginOperator(contexts.operator)
    for (const pageDef of kbdPages) {
      for (const lang of ["zh", "en"]) {
        const page = await contexts[pageDef.role].newPage()
        await setLang(page, lang)
        await page.setViewportSize(viewport)
        const rec = { route: pageDef.key, lang, viewport, status: "PASS", evidence: "CDP 无真实软键盘；visualViewport + 聚焦模拟（simulated）", metrics: null, shot: "" }
        try {
          await page.goto(`${BASE_URL}${pageDef.path}`, { waitUntil: "networkidle", timeout: 20_000 })
          await page.waitForTimeout(500)
          const input = page.locator(pageDef.input).first()
          await input.scrollIntoViewIfNeeded()
          await input.focus()
          await page.waitForTimeout(400)
          const probe = await page.evaluate((texts) => {
            const vv = window.visualViewport
            const submit = [...document.querySelectorAll("button")].find((b) => texts.some((t) => (b.innerText || "").trim().includes(t)))
            const sr = submit ? submit.getBoundingClientRect() : null
            return {
              innerHeight: window.innerHeight,
              vvHeight: vv ? vv.height : null,
              vvOffsetTop: vv ? vv.offsetTop : null,
              submit: sr ? { top: Math.round(sr.top), bottom: Math.round(sr.bottom), height: Math.round(sr.height), withinVv: sr.bottom <= (vv ? vv.height : window.innerHeight) } : null,
            }
          }, pageDef.submitTexts)
          rec.metrics = probe
          const file = `sim-keyboard-${pageDef.key}-${lang}-390.png`
          await page.screenshot({ path: path.join(SHOT_DIR, file), fullPage: false })
          rec.shot = file
          if (probe.submit && !probe.submit.withinVv) rec.status = "FAIL"
        } catch (err) {
          rec.status = "ERROR"
          rec.metrics = { error: String(err).slice(0, 200) }
        }
        results.push(rec)
        console.log(`${rec.status.padEnd(5)} keyboard ${pageDef.key} ${lang}`)
        await page.close()
      }
    }
  } finally {
    await browser.close()
  }
  fs.writeFileSync(path.join(OUT_DIR, "keyboard.json"), JSON.stringify({ generatedAt: new Date().toISOString(), baseUrl: BASE_URL, environment: "CDP simulated soft keyboard via visualViewport + focus (NOT a real device keyboard)", results }, null, 2))
}

async function runLonglist() {
  const viewport = { width: 390, height: 844 }
  const browser = await chromium.launch({ channel: "chrome", headless: true })
  const contexts = {}
  const results = []
  const listPages = [
    { key: "vocab-books", path: "/vocab/DEMO01/books", role: "student", row: "li button" },
    { key: "admin-licenses", path: "/admin/vocabulary-licenses", role: "operator", row: "tbody tr" },
  ]
  try {
    for (const role of ["student", "operator"]) {
      contexts[role] = await browser.newContext({ viewport, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "zh-CN" })
    }
    await loginStudent(contexts.student)
    await loginOperator(contexts.operator)
    for (const pageDef of listPages) {
      for (const lang of ["zh", "en"]) {
        const page = await contexts[pageDef.role].newPage()
        await setLang(page, lang)
        await page.setViewportSize(viewport)
        const rec = { route: pageDef.key, lang, viewport, status: "PASS", evidence: "长列表顶部/底部可达性，CDP 模拟滚动", metrics: null, shots: [] }
        try {
          await page.goto(`${BASE_URL}${pageDef.path}`, { waitUntil: "networkidle", timeout: 20_000 })
          await page.waitForTimeout(600)
          const topShot = `sim-longlist-${pageDef.key}-${lang}-top.png`
          await page.screenshot({ path: path.join(SHOT_DIR, topShot), fullPage: false })
          rec.shots.push(topShot)
          const rows = page.locator(pageDef.row)
          const count = await rows.count()
          await rows.last().scrollIntoViewIfNeeded({ timeout: 5_000 })
          await page.waitForTimeout(400)
          const lastRect = await rows.last().evaluate((el) => {
            const r = el.getBoundingClientRect()
            return { top: Math.round(r.top), bottom: Math.round(r.bottom), height: Math.round(r.height), visible: r.bottom > 0 && r.top < window.innerHeight }
          }).catch(() => null)
          const bottomShot = `sim-longlist-${pageDef.key}-${lang}-bottom.png`
          await page.screenshot({ path: path.join(SHOT_DIR, bottomShot), fullPage: false })
          rec.shots.push(bottomShot)
          rec.metrics = { rowCount: count, lastRow: lastRect, scrollY: await page.evaluate(() => Math.round(window.scrollY)) }
          if (count > 0 && (!lastRect || !lastRect.visible)) rec.status = "FAIL"
        } catch (err) {
          rec.status = "ERROR"
          rec.metrics = { error: String(err).slice(0, 200) }
        }
        results.push(rec)
        console.log(`${rec.status.padEnd(5)} longlist ${pageDef.key} ${lang}`)
        await page.close()
      }
    }
  } finally {
    await browser.close()
  }
  fs.writeFileSync(path.join(OUT_DIR, "longlist.json"), JSON.stringify({ generatedAt: new Date().toISOString(), baseUrl: BASE_URL, environment: "CDP simulated scroll; top/bottom reachability", results }, null, 2))
}

const mode = process.argv[2] ?? "zoom"
fs.mkdirSync(SHOT_DIR, { recursive: true })
if (mode === "zoom") await runZoom()
else if (mode === "webkit") await runWebKit()
else if (mode === "keyboard") await runKeyboard()
else if (mode === "longlist") await runLonglist()
else throw new Error(`unknown mode: ${mode}`)
