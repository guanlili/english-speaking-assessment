import { defineConfig } from "@hey-api/openapi-ts"

export default defineConfig({
  input: "./openapi.json",
  output: "./src/client",

  plugins: [
    // 0.73 时代的 legacy/axios 插件已移除（2026-10 迁移 0.99）：
    // 客户端换 client-fetch；SDK 以下配置保持既有调用形态——
    // 按标签分组为 *Service 类、方法名 = operationId 剥掉标签前缀后
    // 首字母小写（复刻旧 methodNameBuilder 语义）、参数扁平单对象、
    // 直接返回数据、错误抛出，业务代码无需逐调用点改写。
    {
      name: "@hey-api/client-fetch",
      // 不设全局 parseAs——CSV/JSON 按内容类型正常解析；题库三个
      // xlsx 二进制端点（模板/错误行/导出）在调用点传
      // { parseAs: "blob" }（fetch 无法在拦截器切 responseType）
    },
    {
      name: "@hey-api/sdk",
      responseStyle: "data",
      paramsStructure: "flat",
      operations: {
        strategy: (operation) => {
          // IR 的 operation.id 已是驼峰形（login-read_login_options →
          // loginReadLoginOptions）。剥前缀按「归一化后的标签长度」截：
          // 标签里的连字符/下划线在驼峰 id 里同长度消失
          // （question-bank ↔ questionBank…），逐字符比对即可。
          const tag = operation.tags?.[0] ?? "Default"
          const id = operation.id
          const norm = (s: string) => s.toLowerCase().replace(/[-_]/g, "")
          const t = norm(tag)
          const rest =
            id.length > t.length && norm(id.slice(0, t.length)) === t
              ? id.slice(t.length)
              : id
          return [[tag, rest || id]]
        },
        containerName: { name: "{{name}}Service", casing: "PascalCase" },
      },
    },
  ],
})
