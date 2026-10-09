import { defineConfig } from "@playwright/test"

/**
 * E2E 冒烟：针对完整 docker 栈（compose up 后 frontend 在 80 端口）。
 * 本地：docker compose up -d --build 后 npm run e2e。
 *
 * 浏览器分两层（批次11）：
 * - chromium：全量套件（含依赖真实后端的用例）；
 * - webkit：仅 @webkit 标签的核心冒烟（登录/练习/考试/音频回放/草稿恢复），
 *   全部为网络层 mock 用例——不碰共享后端数据，与 chromium 天然隔离，
 *   也不把整个套件无差别乘 2。学生主力是 iPad（Safari/WebKit），
 *   这层冒烟是自动化能做到的 Safari 前哨；真实 iPad 人工验收见
 *   docs/manual-ipad-safari-checklist.md。
 */
export default defineConfig({
  testDir: "tests/e2e",
  timeout: 30_000,
  retries: 1,
  workers: 1,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:80",
    locale: "zh-CN",
  },
  projects: [
    { name: "chromium", use: { browserName: "chromium" } },
    {
      name: "webkit",
      use: { browserName: "webkit" },
      grep: /@webkit/,
    },
  ],
})
