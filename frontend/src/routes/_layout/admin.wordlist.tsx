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
      setPreview(null)
      queryClient.invalidateQueries({ queryKey: ["admin", "wordlist"] })
    },
    onError: (err: { body?: { detail?: string } }) =>
      showErrorToast(err.body?.detail ?? "导入失败"),
  })

  // 预览：前端解析校验（搬原型的 parseCSV 口径），确认后才上传
  const [preview, setPreview] = useState<{
    file: File
    words: Array<{ word: string; band: string }>
    invalid: number
  } | null>(null)

  const parseCsv = (text: string): string[][] => {
    const rows: string[][] = []
    let row: string[] = []
    let cell = ""
    let quoted = false
    const src = text.replace(/^\uFEFF/, "")
    for (let i = 0; i < src.length; i++) {
      const c = src[i]
      if (c === '"') {
        if (quoted && src[i + 1] === '"') {
          cell += '"'
          i++
        } else quoted = !quoted
      } else if (c === "," && !quoted) {
        row.push(cell)
        cell = ""
      } else if ((c === "\n" || c === "\r") && !quoted) {
        if (c === "\r" && src[i + 1] === "\n") i++
        row.push(cell)
        if (row.some((v) => v.trim())) rows.push(row)
        row = []
        cell = ""
      } else cell += c
    }
    row.push(cell)
    if (row.some((v) => v.trim())) rows.push(row)
    return rows
  }

  const onFileChange = async (file: File | undefined) => {
    if (!file) return
    try {
      const rows = parseCsv(await file.text())
      if (!rows.length) throw new Error("文件为空")
      const headers = (rows.shift() ?? []).map((h) => h.trim().toLowerCase())
      const wi =
        headers.indexOf("lemma") >= 0
          ? headers.indexOf("lemma")
          : headers.indexOf("word")
      const bi = headers.indexOf("band")
      if (wi < 0 || bi < 0)
        throw new Error("缺少 lemma 或 band 列（第一行表头）")
      const seen = new Set<string>()
      const words: Array<{ word: string; band: string }> = []
      let invalid = 0
      for (const r of rows) {
        const word = (r[wi] ?? "").trim().toLowerCase()
        const band = (r[bi] ?? "").trim().toUpperCase()
        if (!word || !["A2", "B1", "B2"].includes(band) || seen.has(word)) {
          invalid++
          continue
        }
        seen.add(word)
        words.push({ word, band })
      }
      if (!words.length) throw new Error("没有有效词条")
      setPreview({ file, words, invalid })
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : "解析失败")
      if (fileRef.current) fileRef.current.value = ""
    }
  }

  const confirmImport = async () => {
    if (!preview) return
    setUploading(true)
    try {
      await importMutation.mutateAsync(preview.file)
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ""
    }
  }

  const downloadTemplate = () => {
    const csv = "lemma,band\r\nfriendly,B1\r\ndog,A2\r\ncrucial,B2"
    const url = URL.createObjectURL(
      new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" }),
    )
    const link = document.createElement("a")
    link.href = url
    link.download = "wordlist-template.csv"
    document.body.append(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
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
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={downloadTemplate}>
              下载模板
            </Button>
            <Button
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
            >
              <Upload />
              {uploading ? "导入中…" : "选择 CSV 文件"}
            </Button>
          </div>

          {preview && (
            <div className="mt-4 rounded-xl border border-dashed border-primary/40 bg-secondary/40 p-4">
              <p className="text-sm">
                校验通过：<strong>{preview.words.length}</strong> 个词条（A2{" "}
                {preview.words.filter((w) => w.band === "A2").length} / B1{" "}
                {preview.words.filter((w) => w.band === "B1").length} / B2{" "}
                {preview.words.filter((w) => w.band === "B2").length}
                {preview.invalid > 0
                  ? `，跳过 ${preview.invalid} 个无效/重复行`
                  : ""}
                ）
              </p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {preview.words.slice(0, 12).map((w) => (
                  <span
                    key={w.word}
                    className="rounded bg-secondary px-2 py-0.5 text-xs text-primary"
                  >
                    {w.word} · {w.band}
                  </span>
                ))}
                {preview.words.length > 12 && (
                  <span className="text-xs text-muted-foreground">
                    …共 {preview.words.length} 个
                  </span>
                )}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                确认后整体替换当前词表。
              </p>
              <div className="mt-3 flex gap-2">
                <Button
                  size="sm"
                  disabled={importMutation.isPending}
                  onClick={() => void confirmImport()}
                >
                  预览无误，替换词表
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setPreview(null)
                    if (fileRef.current) fileRef.current.value = ""
                  }}
                >
                  取消
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
