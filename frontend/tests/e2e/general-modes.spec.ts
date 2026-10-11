import { expect, test } from "@playwright/test"

for (const width of [390, 820, 1180]) {
  for (const exam of [false, true]) {
    for (const feedback of [false, true]) {
      test(`${feedback ? "feedback" : "progress"} excludes instructions ${exam ? "exam" : "practice"} ${width}`, async ({
        page,
      }) => {
        await page.setViewportSize({ width, height: 900 })
        await page.addInitScript(() => {
          localStorage.setItem("access_token", "test-token")
          localStorage.setItem("esa:role", "student")
          localStorage.setItem(
            "esa:student:GENERAL",
            JSON.stringify({
              id: "student",
              display_name: "Student",
              user_id: "user",
            }),
          )
        })
        await page.route("**/api/v1/**", async (route) => {
          const path = new URL(route.request().url()).pathname
          await route.fulfill({
            json: path.endsWith("/users/me")
              ? { id: "user", role: "student", is_active: true }
              : path.endsWith("/today")
                ? {
                    classroom_code: "GENERAL",
                    session_id: "history-session",
                    band: "B1",
                    items: [
                      {
                        id: "instruction",
                        type: "instruction",
                        text: "Private instruction text",
                        suggested_seconds: 15,
                      },
                      {
                        id: "question",
                        type: "question",
                        text: "What do you like?",
                        suggested_seconds: 30,
                      },
                    ],
                    attempts: feedback
                      ? [
                          {
                            item_id: "question",
                            attempt_id: "attempt",
                            status: "done",
                            overall: 80,
                          },
                        ]
                      : [],
                    exam: exam
                      ? {
                          started: true,
                          ended: feedback,
                          current_item_index: 0,
                          item_remaining_seconds: 15,
                          item_duration_seconds: 15,
                          item_prep_remaining_seconds: 0,
                          time_limit_minutes: 30,
                          remaining_seconds: feedback ? 0 : 1800,
                        }
                      : null,
                  }
                : [],
          })
        })
        await page.goto(
          `/${exam ? "exam" : "p"}/GENERAL${feedback ? "/result" : ""}?session=history-session`,
        )
        if (feedback) {
          await expect(
            page.getByText(
              exam
                ? /考试已结束 · 已提交 1\/1 题 · 未作答 0 题/
                : /已完成 1 \/ 1 题/,
            ),
          ).toBeVisible()
          await expect(page.getByText("Private instruction text")).toHaveCount(
            0,
          )
        } else {
          await expect(
            page
              .getByRole("heading", { name: "题目说明", exact: true })
              .first(),
          ).toBeVisible()
          await expect(page.getByRole("progressbar")).toHaveAttribute(
            "aria-valuemax",
            "1",
          )
          await expect(
            page.getByRole("progressbar").locator("span"),
          ).toHaveCount(1)
          await expect(page.getByText(/第 \d+\/\d+ 题/)).toHaveCount(0)
        }
        expect(
          await page.evaluate(
            () =>
              document.documentElement.scrollWidth -
              document.documentElement.clientWidth,
          ),
        ).toBeLessThanOrEqual(1)
      })
    }
  }
}
