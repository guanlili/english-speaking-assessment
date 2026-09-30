import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Upload } from "lucide-react"
import { useRef, useState } from "react"
import { AdminService } from "@/client"
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
import { downloadCsv } from "@/lib/csv"
import { useI18n } from "@/lib/i18n"

export const Route = createFileRoute("/_layout/admin/wordlist")({
  component: WordlistAdmin,
  head: () => ({
    meta: [{ title: `分级词表 / Graded Word List - ${APP_NAME}` }],
  }),
})

function WordlistAdmin() {
  const { t } = useI18n()
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
        t({
          zh: `已导入 ${data.imported ?? 0} 个词${
            (data.invalid_rows ?? []).length > 0
              ? `，跳过 ${(data.invalid_rows ?? []).length} 个无效行`
              : ""
          }`,
          en: `Imported ${data.imported ?? 0} words${
            (data.invalid_rows ?? []).length > 0
              ? `, skipped ${(data.invalid_rows ?? []).length} invalid rows`
              : ""
          }`,
        }),
      )
      setPreview(null)
      queryClient.invalidateQueries({ queryKey: ["admin", "wordlist"] })
    },
    onError: (err: { body?: { detail?: string } }) =>
      showErrorToast(
        err.body?.detail ?? t({ zh: "导入失败", en: "Import failed" }),
      ),
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
      if (!rows.length)
        throw new Error(t({ zh: "文件为空", en: "The file is empty" }))
      const headers = (rows.shift() ?? []).map((h) => h.trim().toLowerCase())
      const wi =
        headers.indexOf("lemma") >= 0
          ? headers.indexOf("lemma")
          : headers.indexOf("word")
      const bi = headers.indexOf("band")
      if (wi < 0 || bi < 0)
        throw new Error(
          t({
            zh: "缺少 lemma 或 band 列（第一行表头）",
            en: "Missing lemma or band column (header row)",
          }),
        )
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
      if (!words.length)
        throw new Error(
          t({ zh: "没有有效词条", en: "No valid word entries found" }),
        )
      setPreview({ file, words, invalid })
    } catch (error) {
      showErrorToast(
        error instanceof Error
          ? error.message
          : t({ zh: "解析失败", en: "Failed to parse file" }),
      )
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
    downloadCsv(
      [
        ["lemma", "band"],
        ["friendly", "B1"],
        ["dog", "A2"],
        ["crucial", "B2"],
      ],
      "wordlist-template.csv",
    )
  }

  const stats = statsQuery.data

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          {t({ zh: "分级词表", en: "Graded Word List" })}
        </h1>
        <p className="text-muted-foreground">
          {t({
            zh: "学生词汇参考档位的数据来源。导入学校分级词表 CSV 会整体替换当前词表。",
            en: "Source of the vocabulary reference levels students see. Importing a school CSV replaces the current word list entirely.",
          })}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t({ zh: "当前词表", en: "Current Word List" })}
          </CardTitle>
          <CardDescription>
            {stats?.name ?? t({ zh: "未配置", en: "Not configured" })} ·{" "}
            {t({
              zh: "界面会向学生标注词表来源",
              en: "Students see this word list source",
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <Badge variant="secondary">
            {t({
              zh: `共 ${stats?.total ?? 0} 词`,
              en: `${stats?.total ?? 0} words`,
            })}
          </Badge>
          {Object.entries(stats?.by_band ?? {}).map(([band, count]) => (
            <Badge key={band} variant="outline">
              {band} × {count}
            </Badge>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t({ zh: "导入 CSV", en: "Import CSV" })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: "第一行表头 lemma,band；band 取 A2/B1/B2；UTF-8 编码；重复词自动去重。整体替换现有词表。",
              en: "Header row lemma,band; band is A2/B1/B2; UTF-8 encoded; duplicates are removed automatically. This replaces the existing word list.",
            })}
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
              {t({ zh: "下载模板", en: "Download Template" })}
            </Button>
            <Button
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
            >
              <Upload />
              {uploading
                ? t({ zh: "导入中…", en: "Importing…" })
                : t({ zh: "选择 CSV 文件", en: "Choose CSV File" })}
            </Button>
          </div>

          {preview && (
            <div className="mt-4 rounded-xl border border-dashed border-primary/40 bg-secondary/40 p-4">
              <p className="text-sm">
                {t({ zh: "校验通过：", en: "Validation passed: " })}
                <strong>{preview.words.length}</strong>
                {t({ zh: " 个词条（A2 ", en: " entries (A2 " })}
                {preview.words.filter((w) => w.band === "A2").length} / B1{" "}
                {preview.words.filter((w) => w.band === "B1").length} / B2{" "}
                {preview.words.filter((w) => w.band === "B2").length}
                {preview.invalid > 0
                  ? t({
                      zh: `，跳过 ${preview.invalid} 个无效/重复行`,
                      en: `, ${preview.invalid} invalid/duplicate rows skipped`,
                    })
                  : ""}
                {t({ zh: "）", en: ")" })}
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
                    {t({
                      zh: `…共 ${preview.words.length} 个`,
                      en: `…${preview.words.length} in total`,
                    })}
                  </span>
                )}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {t({
                  zh: "确认后整体替换当前词表。",
                  en: "Confirming replaces the current word list entirely.",
                })}
              </p>
              <div className="mt-3 flex gap-2">
                <Button
                  size="sm"
                  disabled={importMutation.isPending}
                  onClick={() => void confirmImport()}
                >
                  {t({ zh: "预览无误，替换词表", en: "Looks Good, Replace" })}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setPreview(null)
                    if (fileRef.current) fileRef.current.value = ""
                  }}
                >
                  {t({ zh: "取消", en: "Cancel" })}
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
