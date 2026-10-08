import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import { tanstackRouter } from "@tanstack/router-plugin/vite"
import react from "@vitejs/plugin-react-swc"
import { defineConfig } from "vite"

// https://vitejs.dev/config/
export default defineConfig({
  server: {
    proxy: {
      "/api": {
        target: process.env.API_PROXY_TARGET || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    rollupOptions: {
      output: {
        // 框架代码拆成稳定 vendor chunk：不拆的话 React/TanStack 与业务代码
        // 混在同一个 entry，任何业务改动都让整包 hash 变化——弱网学生端
        // 每次发版都要重新下载全部框架代码，长缓存形同虚设。
        // radix / 表单族再各拆一块：多路由共享、单独失效。
        manualChunks(id: string) {
          if (!id.includes("node_modules")) {
            return undefined
          }
          if (id.includes("node_modules/@radix-ui/")) {
            return "radix-ui"
          }
          if (/node_modules\/(react-hook-form|zod|@hookform\/)/.test(id)) {
            return "form"
          }
          if (
            /node_modules\/(react|react-dom|scheduler)\//.test(id) ||
            id.includes("node_modules/@tanstack/")
          ) {
            return "vendor"
          }
          return undefined
        },
      },
    },
  },
  plugins: [
    tanstackRouter({
      target: "react",
      autoCodeSplitting: true,
    }),
    react(),
    tailwindcss(),
  ],
})
