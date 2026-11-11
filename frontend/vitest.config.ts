import { fileURLToPath } from "node:url"

import react from "@vitejs/plugin-react-swc"
import { defineConfig } from "vitest/config"

/**
 * 组件级测试专用配置。
 *
 * 纯逻辑测试仍走 `node --test tests/*.test.ts`（见 package.json 的 `test` 脚本），
 * 这里只负责需要 DOM 渲染环境与 JSX 转译的 React 组件 / hooks 测试。
 * 两者分开是为了不动已经跑通的 26 个纯函数用例。
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // 与 tsconfig.json 的 paths 保持一致，否则组件里的 `@/…` 导入无法解析
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["tests/components/**/*.test.tsx"],
    setupFiles: ["./tests/components/setup.ts"],
    restoreMocks: true,
  },
})
