import { defineConfig } from "@playwright/test"

/**
 * E2E 冒烟：针对完整 docker 栈（compose up 后 frontend 在 80 端口）。
 * 本地：docker compose up -d --build 后 npm run e2e。
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
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
})
