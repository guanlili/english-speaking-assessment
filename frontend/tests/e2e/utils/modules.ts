import type { Route } from "@playwright/test"

/**
 * mocked E2E 的世界口径：既有规格按「完整产品」编写，默认双模块全开。
 * 模块授权的最终裁决在后端闸门；这里的桩只保证既有导航/入口不被空清单隐藏。
 */
export const MOCK_ENABLED_MODULES = ["speaking", "vocabulary"] as const

export function isModulesMeRoute(route: Route): boolean {
  return new URL(route.request().url()).pathname.endsWith("/modules/me")
}

export async function fulfillModulesMe(route: Route): Promise<void> {
  await route.fulfill({ json: { modules: [...MOCK_ENABLED_MODULES] } })
}
