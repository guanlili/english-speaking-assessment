import { useMutation } from "@tanstack/react-query"
import { useMemo, useState } from "react"
import { type StudentImportResult, StudentsService } from "@/client"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"
import { localizedDetail } from "@/utils"

function StudentImportDialog({
  classroomId,
  classroomCode,
  open,
  onOpenChange,
  onDone,
}: {
  classroomId: string
  classroomCode: string
  open: boolean
  onOpenChange: (v: boolean) => void
  onDone: () => void
}) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { t } = useI18n()
  const [text, setText] = useState("")
  const [result, setResult] = useState<StudentImportResult | null>(null)

  const lines = useMemo(
    () =>
      text
        .split("\n")
        .map((l) => l.trim())
        .filter(Boolean)
        .map((l) => {
          const [username, ...rest] = l.split(/\s+/)
          return {
            username: username ?? "",
            full_name: rest.join(" ") || username,
          }
        }),
    [text],
  )

  const mutation = useMutation({
    mutationFn: () =>
      StudentsService.importStudents({
        studentImportRequest: { classroom_id: classroomId, lines },
      }),
    onSuccess: (res) => {
      setResult(res)
      const joined = res.joined ?? 0
      const already = res.already_enrolled ?? 0
      if (res.created + res.merged + joined > 0) {
        showSuccessToast(
          t({
            zh: `导入完成：新建 ${res.created}、绑定历史档案 ${res.merged}、加入本班 ${joined}${res.skipped ? `、跳过 ${res.skipped}` : ""}`,
            en: `Import done: ${res.created} created, ${res.merged} linked to existing profiles, ${joined} joined this class${res.skipped ? `, ${res.skipped} skipped` : ""}`,
          }),
        )
        onDone()
      } else if (already > 0 && res.skipped === 0) {
        showSuccessToast(
          t({
            zh: "名单内学生都已在班级中，无需改动",
            en: "Everyone on the roster is already in this class",
          }),
        )
        onDone()
      } else {
        showErrorToast(
          t({
            zh: "没有导入任何学生，请检查名单",
            en: "No students were imported; please check the roster",
          }),
        )
      }
    },
    onError: (error) =>
      showErrorToast(
        t({
          zh: `导入失败：${error.message}`,
          en: `Import failed: ${error.message}`,
        }),
      ),
  })

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v)
        if (!v) {
          setText("")
          setResult(null)
        }
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {t({
              zh: `导入学生（${classroomCode}）`,
              en: `Import Students (${classroomCode})`,
            })}
          </DialogTitle>
          <DialogDescription>
            {t({
              zh: "每行「学号 姓名」（空格或制表符分隔）；账号初始密码统一为默认密码 brs123456，与历史匿名学生同名时自动绑定其练习数据。学号已在其他班的：姓名一致即同一学生，将加入本班且不重置密码；姓名不一致会拒绝，请先核对名单。",
              en: 'One "Student ID Name" per line (separated by spaces or tabs). Accounts start with the default password brs123456, and names matching past anonymous students are automatically linked to their practice data. If a student ID already exists in another class with the same name, the student joins this class and their password is untouched; mismatched names are rejected — double-check the roster first.',
            })}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <Textarea
            rows={8}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t({
              zh: "2026001 李雷\n2026002 韩梅梅\n2026003 林涛",
              en: "2026001 Li Lei\n2026002 Han Meimei\n2026003 Lin Tao",
            })}
            aria-label={t({ zh: "学生名单", en: "Student roster" })}
          />
          <div className="text-sm text-muted-foreground">
            {t({ zh: "将导入", en: "Importing" })}{" "}
            <span className="font-medium text-foreground">{lines.length}</span>{" "}
            {t({ zh: "名学生", en: "student(s)" })}
          </div>
          {result && (
            <div className="rounded-md border bg-muted/40 p-3 text-sm">
              <p>
                {t({
                  zh: `新建 ${result.created} · 绑定历史 ${result.merged} · 加入本班 ${result.joined ?? 0} · 已在班内 ${result.already_enrolled ?? 0} · 跳过 ${result.skipped}`,
                  en: `${result.created} created · ${result.merged} linked · ${result.joined ?? 0} joined this class · ${result.already_enrolled ?? 0} already in class · ${result.skipped} skipped`,
                })}
              </p>
              {result.rows.some(
                (r) =>
                  r.status === "joined_existing" ||
                  r.status === "already_enrolled",
              ) && (
                <ul className="mt-2 list-inside list-disc text-muted-foreground">
                  {result.rows
                    .filter(
                      (r) =>
                        r.status === "joined_existing" ||
                        r.status === "already_enrolled",
                    )
                    .map((r) => (
                      <li key={r.username}>
                        {r.status === "joined_existing"
                          ? t({
                              zh: `${r.username}（${r.full_name}）：使用原有账号加入本班，密码不变`,
                              en: `${r.username} (${r.full_name}): joined this class with the existing account; password unchanged`,
                            })
                          : t({
                              zh: `${r.username}（${r.full_name}）：已在本班，未改动`,
                              en: `${r.username} (${r.full_name}): already in this class, unchanged`,
                            })}
                      </li>
                    ))}
                </ul>
              )}
              {result.rows.some((r) => r.error) && (
                <ul className="mt-2 list-inside list-disc text-destructive">
                  {result.rows
                    .filter((r) => r.error)
                    .map((r) => (
                      <li key={r.username}>
                        {t({
                          zh: `${r.username}：${localizedDetail(r.error ?? "")}`,
                          en: `${r.username}: ${localizedDetail(r.error ?? "")}`,
                        })}
                      </li>
                    ))}
                </ul>
              )}
            </div>
          )}
        </div>
        <DialogFooter className="flex-row gap-2">
          <LoadingButton
            disabled={lines.length === 0}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {t({ zh: "导入", en: "Import" })}
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default StudentImportDialog
