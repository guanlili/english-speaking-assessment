import { useQuery } from "@tanstack/react-query"
import { VocabularyService } from "@/client"

/**
 * 按词库读取授权台账（词库级 + 词条级清单）。
 * 查询键与页面其他词库详情查询并列，保存后由调用方失效对应键。
 */
export function useBookLicense(bookId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["admin", "vocab-book-license", bookId],
    queryFn: () =>
      VocabularyService.readBookLicense({ book_id: bookId as string }),
    enabled: enabled && bookId !== null,
  })
}
