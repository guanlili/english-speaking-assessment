import { APP_NAME } from "@/config"

// 按项目需要补充页脚内容（备案号、联系方式、法律链接等）
export function Footer() {
  const currentYear = new Date().getFullYear()

  return (
    <footer className="border-t py-4 px-6">
      <p className="text-muted-foreground text-center text-sm">
        © {currentYear} {APP_NAME}
      </p>
    </footer>
  )
}
