import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react-swc"
import { defineConfig } from "vite"

// Component host stays outside the production app and its changing teacher UI.
export default defineConfig({
  root: __dirname,
  // Keep the component host from invalidating a concurrently running app dev server.
  cacheDir: path.resolve(__dirname, "../../node_modules/.vite-fixtures"),
  resolve: { alias: { "@": path.resolve(__dirname, "../../src") } },
  plugins: [react(), tailwindcss()],
  server: { fs: { allow: [path.resolve(__dirname, "../..")] } },
})
