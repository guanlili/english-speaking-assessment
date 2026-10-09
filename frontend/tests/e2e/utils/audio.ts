// A real PCM file lets the browser decode and advance playback, rather than
// replacing play() with a stub that would conceal a broken source URL.
export function wav() {
  const sampleRate = 8000
  const samples = sampleRate * 4
  const data = Buffer.alloc(44 + samples * 2)
  data.write("RIFF", 0)
  data.writeUInt32LE(data.length - 8, 4)
  data.write("WAVEfmt ", 8)
  data.writeUInt32LE(16, 16)
  data.writeUInt16LE(1, 20)
  data.writeUInt16LE(1, 22)
  data.writeUInt32LE(sampleRate, 24)
  data.writeUInt32LE(sampleRate * 2, 28)
  data.writeUInt16LE(2, 32)
  data.writeUInt16LE(16, 34)
  data.write("data", 36)
  data.writeUInt32LE(samples * 2, 40)
  for (let i = 0; i < samples; i++)
    data.writeInt16LE(
      Math.round(1000 * Math.sin((i * 440 * Math.PI * 2) / sampleRate)),
      44 + i * 2,
    )
  return data
}
