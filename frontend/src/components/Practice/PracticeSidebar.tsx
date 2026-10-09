import {
  ChartLine,
  Headphones,
  MessageCircle,
  Shield,
  Sparkles,
} from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { useI18n } from "@/lib/i18n"
import { TERMS } from "@/lib/terms"

/** 练习页右侧栏：小提示卡 + 今天的路线 + 隐私说明（桌面端显示）。 */
export default function PracticeSidebar({
  isQuestion,
  allDone,
}: {
  isQuestion: boolean
  allDone: boolean
}) {
  const { t } = useI18n()
  return (
    <aside className="grid gap-4">
      <Card className="border-secondary bg-secondary/60">
        <CardContent className="space-y-2 py-4">
          <p className="flex items-center gap-1.5 text-sm font-semibold">
            <Sparkles className="size-4 text-primary" />{" "}
            {t({ zh: "一个小小的提示", en: "A little tip" })}
          </p>
          {isQuestion ? (
            <>
              <p className="text-sm text-muted-foreground">
                {t({
                  zh: "不用寻找「标准答案」。试试这个顺序，让你的表达更完整。",
                  en: 'There\'s no "right answer" to find. Try this order to make your answer more complete.',
                })}
              </p>
              <p className="font-serif text-xl">I think… because…</p>
              <p className="text-xs text-muted-foreground">
                {t({
                  zh: "我的观点 → 一个理由 → 一个小例子",
                  en: "My opinion → one reason → one small example",
                })}
              </p>
            </>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">
                {t({
                  zh: "先听完整句子，再跟着意群停顿。比起说得快，说得自然更重要。",
                  en: "Listen to the whole sentence first, then pause with its chunks. Sounding natural beats speaking fast.",
                })}
              </p>
              <p className="font-serif text-xl">Listen. Pause. Speak.</p>
              <p className="text-xs text-muted-foreground">
                {t({
                  zh: "听一遍 · 想一想 · 大胆说",
                  en: "Listen once · think · speak boldly",
                })}
              </p>
            </>
          )}
        </CardContent>
      </Card>

      <Card className="hidden lg:block">
        <CardContent className="py-4">
          <p className="mb-3 text-sm font-semibold">
            {t({ zh: "今天的路线", en: "Today's route" })}
          </p>
          {[
            {
              icon: Headphones,
              title: t(TERMS.typeRepeat),
              sub: t({ zh: "3 个短句", en: "3 sentences" }),
              active: !isQuestion,
            },
            {
              icon: MessageCircle,
              title: t(TERMS.typeQa),
              sub: t({ zh: "2 个问题", en: "2 questions" }),
              active: isQuestion,
            },
            {
              icon: ChartLine,
              title: t({ zh: "看看收获", en: "See your gains" }),
              sub: t({
                zh: "全部完成后一起看",
                en: "View together after finishing",
              }),
              active: allDone,
            },
          ].map((step) => (
            <div
              key={step.title}
              className={
                step.active
                  ? "flex items-center gap-2.5 py-2.5 text-sm font-semibold text-primary"
                  : "flex items-center gap-2.5 py-2.5 text-sm text-muted-foreground"
              }
            >
              <span
                className={
                  step.active
                    ? "grid size-7 place-items-center rounded-full bg-secondary text-primary"
                    : "grid size-7 place-items-center rounded-full bg-background text-muted-foreground"
                }
              >
                <step.icon className="size-3.5" />
              </span>
              <span>
                {step.title}
                <span className="block text-[10px] font-normal text-muted-foreground">
                  {step.sub}
                </span>
              </span>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="hidden lg:block">
        <CardContent className="flex items-start gap-2 py-3.5 text-xs text-muted-foreground">
          <Shield className="mt-0.5 size-3.5 shrink-0 text-primary" />
          {t({
            zh: "每次录音只有你自己和本课授权老师能回听。说错了没关系，再录一次就好。",
            en: "Only you and your classroom's authorized teacher can play back your recordings. Mistakes are fine — just record again.",
          })}
        </CardContent>
      </Card>
    </aside>
  )
}
