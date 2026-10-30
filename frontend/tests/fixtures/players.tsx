import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { useState } from "react"
import { createRoot } from "react-dom/client"
import AttemptAudio from "@/components/Practice/AttemptAudio"
import { useRecorder } from "@/hooks/useRecorder"
import { setupApiClient } from "@/lib/api-client"
import { I18nProvider } from "@/lib/i18n"

setupApiClient()

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
function RecorderHarness() {
  const [starts, setStarts] = useState(0)
  const [result, setResult] = useState("")
  const recorder = useRecorder({
    onStarted: () => setStarts((value) => value + 1),
    onComplete: (recording) => {
      void recording.blob.text().then(setResult)
    },
  })
  return (
    <main>
      <button type="button" onClick={() => void recorder.start()}>
        Start
      </button>
      <button type="button" onClick={recorder.stop}>
        Stop
      </button>
      <button type="button" onClick={recorder.reset}>
        Reset
      </button>
      <p data-testid="status">{recorder.status}</p>
      <p data-testid="starts">{starts}</p>
      <p data-testid="result">{result}</p>
      <p role="alert">{recorder.error}</p>
    </main>
  )
}
createRoot(document.getElementById("root")!).render(
  <I18nProvider>
    <QueryClientProvider client={queryClient}>
      {location.search.includes("recorder") ? <RecorderHarness /> : <Players />}
    </QueryClientProvider>
  </I18nProvider>,
)
