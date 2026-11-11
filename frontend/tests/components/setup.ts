import "@testing-library/jest-dom/vitest"

/**
 * jsdom 缺少部分浏览器 API，组件里用到的这些需要在测试环境补齐，
 * 否则渲染阶段就会抛 TypeError，测的不是组件逻辑而是环境缺失。
 */

// 录音 / 音频链路用到的 mocks：jsdom 不实现 MediaRecorder 与 getUserMedia
if (!globalThis.MediaRecorder) {
  class FakeMediaRecorder {
    static isTypeSupported() {
      return true
    }
    state = "inactive"
    ondataavailable: ((e: unknown) => void) | null = null
    onstop: (() => void) | null = null
    onerror: ((e: unknown) => void) | null = null
    constructor(public stream: unknown) {}
    start() {
      this.state = "recording"
    }
    stop() {
      this.state = "inactive"
      this.onstop?.()
    }
    pause() {}
    resume() {}
  }
  globalThis.MediaRecorder =
    FakeMediaRecorder as unknown as typeof MediaRecorder
}

if (!globalThis.URL.createObjectURL) {
  globalThis.URL.createObjectURL = () => "blob:mock"
  globalThis.URL.revokeObjectURL = () => {}
}

// ResizeObserver：radix / 自定义布局组件会用到
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
}

// matchMedia：主题切换与响应式判定会用到
if (!globalThis.matchMedia) {
  globalThis.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof matchMedia
}
