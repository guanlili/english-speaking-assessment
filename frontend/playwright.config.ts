import { defineConfig } from "@playwright/test"

// Only reviewed, API-mocked files may run concurrently. New files default to
// the serial integration project until their isolation has been checked.
const mockedFiles = [
  "admin-pagination",
  "auth-session",
  "attempt-audio",
  "audio-preview",
  "classroom-delete",
  "classroom-p1",
  "classroom-outcomes",
  "composer-pagination",
  "exam-automated",
  "exam-rules",
  "general-modes",
  "feedback-followups",
  "history-pagination",
  "home",
  "instruction-page",
  "interaction-clarity",
  "practice-navigation",
  "reading-tree",
  "recorder-lifecycle",
  "student-recording-flow",
  "sentence-pagination",
  "teacher-feedback",
  "teacher-drafts",
  "teacher-workspace",
  "teaching-tools",
].map((name) => `**/${name}.spec.ts`)
const mockOnly = process.env.E2E_MOCK_ONLY === "true"

export default defineConfig({
  testDir: "tests/e2e",
  webServer: [
    {
      command:
        "npx vite --config tests/fixtures/vite.config.ts --host 127.0.0.1 --port 5176 --strictPort",
      url: "http://127.0.0.1:5176",
      reuseExistingServer: !process.env.CI,
    },
    ...(mockOnly
      ? [
          {
            command:
              "npx vite preview --host 127.0.0.1 --port 5177 --strictPort",
            url: "http://127.0.0.1:5177",
            reuseExistingServer: !process.env.CI,
          },
        ]
      : []),
  ],
  timeout: 30_000,
  retries: 1,
  // Two workers per CI runner; the mock shards use independent runners.
  workers: process.env.CI ? 2 : 4,
  use: {
    baseURL:
      process.env.E2E_BASE_URL ??
      (mockOnly ? "http://127.0.0.1:5177" : "http://localhost:80"),
    locale: "zh-CN",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      testIgnore: mockedFiles,
      use: { browserName: "chromium" },
      workers: 1,
    },
    {
      name: "chromium-mock",
      testMatch: mockedFiles,
      use: { browserName: "chromium" },
      fullyParallel: true,
    },
    {
      name: "webkit",
      use: { browserName: "webkit" },
      // Preserve all existing tagged coverage, including the login-page smoke
      // in smoke.spec.ts, which does not call the backend.
      grep: /@webkit/,
      fullyParallel: true,
    },
  ],
})
