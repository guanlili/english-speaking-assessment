/** 临时调试：列出指定页面可见控件的 bbox / 字号 / 选择器。用法: node debug.mjs <path> [role] [lang] [width] */
import { createRequire } from "node:module"
import path from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const FRONTEND_DIR = path.resolve(__dirname, "../../../../..", "frontend")
const require = createRequire(path.join(FRONTEND_DIR, "package.json"))
const { chromium } = require("@playwright/test")

const BASE_URL = "http://127.0.0.1:5181"
const route = process.argv[2] ?? "/t/DEMO01/vocab"
const role = process.argv[3] ?? "teacher"
const lang = process.argv[4] ?? "en"
const width = Number(process.argv[5] ?? 390)
const height = Number(process.argv[6] ?? 844)

async function login(ctx, r) {
  if (r === "public") return
  const page = await ctx.newPage()
  if (r === "teacher") {
    await page.goto(`${BASE_URL}/login`)
    await page.getByText(/本地演示体验|Local demo/).click()
    await page.getByRole("button", { name: /教师演示|Teacher demo/ }).click()
    await page.waitForURL((u) => u.pathname.startsWith("/t/"), { timeout: 15_000 })
  } else if (r === "operator") {
    await page.goto(`${BASE_URL}/login`)
    await page.getByText(/本地演示体验|Local demo/).click()
    await page.getByRole("button", { name: /运营演示|Operator demo/ }).click()
    await page.waitForURL((u) => u.pathname.includes("/admin"), { timeout: 15_000 })
  } else if (r === "student") {
    await page.goto(`${BASE_URL}/login`)
    await page.getByRole("tab", { name: /学生登录|Student/ }).click()
    await page.getByPlaceholder(/学号|Student ID/).fill("student")
    const pwd = page.getByTestId("student-password-input")
    for (const pw of ["demo1234", "brs123456"]) {
      await pwd.fill(pw)
      await page.getByRole("button", { name: /登录|Sign in/ }).click()
      try {
        await page.waitForURL((u) => !u.pathname.includes("/login"), { timeout: 8_000 })
        break
      } catch {}
    }
    await page.goto(`${BASE_URL}/j/DEMO01`)
    const hasIdentity = await page
      .waitForFunction(() => localStorage.getItem("esa:student:DEMO01") !== null, undefined, { timeout: 8_000, polling: 250 })
      .then(() => true)
      .catch(() => false)
    if (!hasIdentity) {
      const joinBtn = page.getByRole("button", { name: /进入课堂|Enter class/ })
      if (await joinBtn.count()) {
        await joinBtn.click()
        await page.waitForFunction(() => localStorage.getItem("esa:student:DEMO01") !== null, undefined, { timeout: 8_000 })
      }
    }
  }
  await page.close()
}

const browser = await chromium.launch({ channel: "chrome", headless: true })
const ctx = await browser.newContext({
  viewport: { width, height },
  deviceScaleFactor: 2,
  isMobile: true,
  hasTouch: true,
  locale: "zh-CN",
})
await ctx.addInitScript((l) => localStorage.setItem("esa:lang", l), lang)
await login(ctx, role)
const page = await ctx.newPage()
await page.goto(`${BASE_URL}${route}`, { waitUntil: "networkidle", timeout: 20_000 })
await page.waitForTimeout(800)
const data = await page.evaluate(() => {
  const out = []
  const vis = (el) => {
    const r = el.getBoundingClientRect()
    if (!r.width || !r.height) return false
    const cs = getComputedStyle(el)
    return cs.display !== "none" && cs.visibility !== "hidden" && (el.offsetParent !== null || cs.position === "fixed")
  }
  document.querySelectorAll("input,select,textarea,button,a").forEach((el) => {
    if (!vis(el)) return
    const r = el.getBoundingClientRect()
    const cs = getComputedStyle(el)
    out.push({
      tag: el.tagName.toLowerCase(),
      id: el.id || undefined,
      label: (el.innerText || el.getAttribute("aria-label") || el.getAttribute("placeholder") || "").trim().slice(0, 30),
      w: Math.round(r.width),
      h: Math.round(r.height),
      fs: cs.fontSize,
      cls: String(el.className ?? "").slice(0, 70),
    })
  })
  const doc = document.documentElement
  return { overflow: doc.scrollWidth - doc.clientWidth, sw: doc.scrollWidth, vw: doc.clientWidth, controls: out }
})
console.log("overflow", data.overflow, "sw", data.sw, "vw", data.vw)
for (const c of data.controls) console.log(JSON.stringify(c))
await page.screenshot({ path: path.join(__dirname, "..", "screenshots", `debug-${role}-${lang}-${width}.png`) })
await browser.close()
