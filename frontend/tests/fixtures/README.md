`players.tsx` mounts the production AttemptAudio component under one QueryClient,
independently of teacher-list UI changes. Playwright starts this isolated Vite
host on 127.0.0.1:5176; it is not included in the production build.

`recorded-tone.wav` is a non-silent 3-second oscillator stream recorded by a real
Chromium MediaRecorder as WebM/Opus, then converted by ffmpeg to mono 16 kHz PCM
WAV. It provides a portable playback fixture when Linux WebKit has no
MediaRecorder. Tests force that fallback locally as well as detecting capability.

The component host uses its own Vite dependency cache, so it can run beside the app dev server without invalidating the app’s optimized dependencies.
