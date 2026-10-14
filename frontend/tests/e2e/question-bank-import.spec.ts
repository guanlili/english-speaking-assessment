import { expect, type Page, test } from "@playwright/test"

/**
 * 题库批量导入（2026-10 本期：老师自助录题）。
 *
 * 集成冒烟：/create 入口三按钮可见 → CSV 上传 → 预览计数 → 确认导入
 * → 重传同一文件被完全重复挡住（确认按钮禁用）。不覆盖导出下载
 * （浏览器下载事件断言脆，往返无损已由后端 test_question_bank_io 覆盖）。
 */

async function loginTeacherDemo(page: Page) {
  await page.goto("/login")
  await page.getByText("本地演示体验", { exact: false }).click()
  await page.getByRole("button", { name: "教师演示" }).click()
  await page.waitForURL((url) => !url.pathname.includes("/login"), {
    timeout: 15_000,
  })
}

function importCsv(marker: string): Buffer {
  const rows = [
    "题型,标题,单元,主题,难度,内容,中文提示,挂靠篇目,秒数,可听次数,考试题型,考试级别,话题卡要点,准备秒数,音频链接,状态",
    `情景问答,,,E2E 导入测试,,${marker} Do you like e2e imports?,,,20,,,,,,,,`,
  ]
  return Buffer.from(`\ufeff${rows.join("\n")}\n`, "utf-8")
}

test("题库批量导入：上传 CSV → 预览 → 确认 → 重传防重", async ({ page }) => {
  await loginTeacherDemo(page)
  await page.goto("/create")

  // 入口三按钮
  await expect(page.getByRole("button", { name: /下载模板/ })).toBeVisible()
  const importButton = page.getByRole("button", { name: /^批量导入$/ })
  await expect(importButton).toBeVisible()
  await expect(page.getByRole("button", { name: /导出题目/ })).toBeVisible()

  const marker = `e2e-${Date.now()}`
  const dialog = page.getByRole("dialog")

  await importButton.click()
  await expect(dialog).toBeVisible()
  const fileInput = dialog.locator('input[type="file"]')
  await fileInput.setInputFiles({
    name: "e2e-import.csv",
    mimeType: "text/csv",
    buffer: importCsv(marker),
  })
  await dialog.getByRole("button", { name: /^预览$/ }).click()
  await expect(dialog.getByText(/将导入 1/)).toBeVisible()

  await dialog.getByRole("button", { name: /确认导入/ }).click()
  await expect(dialog.getByText(/新建 1/)).toBeVisible()

  // 重传同一文件：判为完全重复，无新题可导（确认按钮禁用）
  await dialog.getByRole("button", { name: /继续导入下一批/ }).click()
  await fileInput.setInputFiles({
    name: "e2e-import.csv",
    mimeType: "text/csv",
    buffer: importCsv(marker),
  })
  await dialog.getByRole("button", { name: /^预览$/ }).click()
  await expect(dialog.getByText(/完全重复 1（自动跳过）/)).toBeVisible()
  await expect(dialog.getByRole("button", { name: /确认导入/ })).toBeDisabled()
})
