import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { useState } from "react"
import { createRoot } from "react-dom/client"
import AttemptAudio from "@/components/Practice/AttemptAudio"
import { I18nProvider } from "@/lib/i18n"
import "@/index.css"

const queryClient = new QueryClient()
function Players() {
  const [second, setSecond] = useState(false)
  return (
    <main className="space-y-4 p-4">
      <section data-testid="primary-player">
        <AttemptAudio attemptId="saved-attempt" />
      </section>
      <button type="button" onClick={() => setSecond(!second)}>
        {second ? "Unmount second player" : "Mount second player"}
      </button>
      {second && (
        <section data-testid="second-player">
          <AttemptAudio attemptId="saved-attempt" />
        </section>
      )}
    </main>
  )
}
createRoot(document.getElementById("root")!).render(
  <I18nProvider>
    <QueryClientProvider client={queryClient}>
      <Players />
    </QueryClientProvider>
  </I18nProvider>,
)
