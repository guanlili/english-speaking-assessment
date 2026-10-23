import type { DashboardContent } from "@/client"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useI18n } from "@/lib/i18n"

type Item = { label: string; value: number }

function Group({ title, items }: { title: string; items: Item[] }) {
  return (
    <div className="rounded-xl border p-4">
      <p className="text-xs font-medium text-muted-foreground">{title}</p>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2">
        {items.map((item) => (
          <div
            key={item.label}
            className="flex items-baseline justify-between gap-2"
          >
            <dt className="text-sm text-muted-foreground">{item.label}</dt>
            <dd className="text-sm font-semibold tabular-nums">{item.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

/** 资产与账号：题库/词汇/账号/课堂四组存量计数。 */
function ContentAssetsCard({
  content,
  pending,
}: {
  content: DashboardContent | undefined
  pending: boolean
}) {
  const { t } = useI18n()

  if (pending || !content) {
    return (
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-40" />
        ))}
      </div>
    )
  }

  const groups: Array<{ title: string; items: Item[] }> = [
    {
      title: t({ zh: "题库内容", en: "Question bank" }),
      items: [
        {
          label: t({ zh: "朗读篇目", en: "Passages" }),
          value: content.passages,
        },
        {
          label: t({ zh: "复述句", en: "Repeat sentences" }),
          value: content.repeat_sentences,
        },
        {
          label: t({ zh: "情景问答", en: "Q&A items" }),
          value: content.scenario_questions,
        },
        {
          label: t({ zh: "说明页", en: "Instructions" }),
          value: content.instructions,
        },
        { label: t({ zh: "单元", en: "Units" }), value: content.units },
      ],
    },
    {
      title: t({ zh: "词汇", en: "Vocabulary" }),
      items: [
        {
          label: t({ zh: "词库", en: "Word books" }),
          value: content.vocab_books,
        },
        { label: t({ zh: "词条", en: "Words" }), value: content.vocab_words },
        {
          label: t({ zh: "五级词库", en: "Leveled source" }),
          value: content.vocab_level_entries,
        },
      ],
    },
    {
      title: t({ zh: "账号", en: "Accounts" }),
      items: [
        {
          label: t({ zh: "管理员", en: "Admins" }),
          value: content.users_admin,
        },
        {
          label: t({ zh: "教师", en: "Teachers" }),
          value: content.users_teacher,
        },
        {
          label: t({ zh: "学生账号", en: "Student accounts" }),
          value: content.student_accounts,
        },
        {
          label: t({ zh: "学生档案", en: "Student profiles" }),
          value: content.student_profiles,
        },
        {
          label: t({ zh: "待改密学生", en: "Pending password change" }),
          value: content.students_must_change_password,
        },
      ],
    },
    {
      title: t({ zh: "课堂与发布", en: "Classrooms" }),
      items: [
        {
          label: t({ zh: "课堂总数", en: "Total" }),
          value: content.classrooms_total,
        },
        {
          label: t({ zh: "启用中", en: "Active" }),
          value: content.classrooms_active,
        },
        {
          label: t({ zh: "累计发布", en: "Publishes" }),
          value: content.publishes,
        },
        {
          label: t({ zh: "其中模考", en: "Exam publishes" }),
          value: content.publishes_exam,
        },
      ],
    },
  ]

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {t({ zh: "资产与账号", en: "Content & accounts" })}
        </CardTitle>
        <CardDescription>
          {t({
            zh: "全平台存量计数，不随时间范围变化。",
            en: "Platform-wide totals, independent of the selected range.",
          })}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {groups.map((g) => (
            <Group key={g.title} {...g} />
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

export default ContentAssetsCard
