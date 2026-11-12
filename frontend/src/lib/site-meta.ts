import { APP_NAME, SITE_URL } from "@/config"

/**
 * 公开页统一的 head 元信息：标题、描述、canonical 与分享卡片（og / twitter）。
 *
 * 这些页面是唯一面向站外（搜索引擎、群聊转发、试用前预览）的入口，
 * 之前只有 title，转发到微信/飞书时没有任何卡片信息。
 * 域名统一取 config 的 SITE_URL，避免每页各写一份。
 */
export function publicPageHead({
  path,
  title,
  description,
}: {
  path: string
  title: string
  description: string
}) {
  const url = `${SITE_URL}${path}`
  return {
    meta: [
      { title },
      { name: "description", content: description },
      { property: "og:type", content: "website" },
      { property: "og:site_name", content: APP_NAME },
      { property: "og:title", content: title },
      { property: "og:description", content: description },
      { property: "og:url", content: url },
      { property: "og:locale", content: "zh_CN" },
      { name: "twitter:card", content: "summary" },
      { name: "twitter:title", content: title },
      { name: "twitter:description", content: description },
    ],
    links: [{ rel: "canonical", href: url }],
  }
}
