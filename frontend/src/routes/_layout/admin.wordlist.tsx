import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, redirect } from "@tanstack/react-router"
import { Upload } from "lucide-react"
import { useRef, useState } from "react"
import { AdminService, UsersService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { APP_NAME } from "@/config"
import useCustomToast from "@/hooks/useCustomToast"

export const Route = createFileRoute("/_layout/admin/wordlist")({
  component: WordlistAdmin,
  beforeLoad: async () => {
    const user = await UsersService.readUserMe()
    if (!user.is_superuser) {
      throw redirect({ to: "/" })
    }
  },
  head: () => ({ meta: [{ title: `分级词表 - ${APP_NAME}` }] }),
})

function WordlistAdmin() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const fileRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)

  const statsQuery = useQuery({
    queryKey: ["admin", "wordlist"],
    queryFn: () => AdminService.wordlistStats(),
  })

  const importMutation = useMutation({
    mutationFn: async (file: File) =>
      AdminService.importWordlistCsv({
        formData: {
          // 生成器把 binary 标为 string，运行时传 File
          file: file as unknown as string,
        },
      }),
    onSuccess: (data) => {
      showSuccessToast(
        `已导入 ${data.imported ?? 0} 个词${
          (data.invalid_rows ?? []).length > 0
            ? `，跳过 ${(data.invalid_rows ?? []).length} 个无效行`
            : ""
        }`,
      )
      queryClient.invalidateQueries({ queryKey: ["admin", "wordlist"] })
    },
    onError: (err: { body?: { detail?: string } }) =>
      showErrorToast(err.body?.detail ?? "导入失败"),
  })

  const onFileChange = async (file: File | undefined) => {
    if (!file) return
    setUploading(true)
    try {
      await importMutation.mutateAsync(file)
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ""
    }
  }

  const stats = statsQuery.data

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">分级词表</h1>
        <p className="text-muted-foreground">
          学生词汇参考等级的数据来源。导入学校分级词表 CSV 会整体替换当前词表。
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">当前词表</CardTitle>
          <CardDescription>
            {stats?.name ?? "未配置"} · 界面会向学生标注词表来源
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <Badge variant="secondary">共 {stats?.total ?? 0} 词</Badge>
          {Object.entries(stats?.by_band ?? {}).map(([band, count]) => (
            <Badge key={band} variant="outline">
              {band} × {count}
            </Badge>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">导入 CSV</CardTitle>
          <CardDescription>
            第一行表头 <code>lemma,band</code>；band 取 A2/B1/B2；UTF-8 编码；
            重复词自动去重。整体替换现有词表。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(e) => void onFileChange(e.target.files?.[0])}
          />
          <Button onClick={() => fileRef.current?.click()} disabled={uploading}>
            <Upload />
            {uploading ? "导入中…" : "选择 CSV 文件"}
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
