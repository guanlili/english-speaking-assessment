import { useI18n } from "@/lib/i18n"
import DeleteConfirmation from "./DeleteConfirmation"

const DeleteAccount = () => {
  const { t } = useI18n()
  return (
    <div className="max-w-md mt-4 rounded-lg border border-destructive/50 p-4">
      <h3 className="font-semibold text-destructive">
        {t({ zh: "删除账号", en: "Delete Account" })}
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">
        {t({
          zh: "永久删除你的账号及其全部相关数据。",
          en: "Permanently delete your account and all associated data.",
        })}
      </p>
      <DeleteConfirmation />
    </div>
  )
}

export default DeleteAccount
