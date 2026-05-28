import '@testing-library/jest-dom'
import 'whatwg-fetch'
import { vi } from 'vitest'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (typeof window !== 'undefined' && !(window as any).ResizeObserver) {
  ;(window as any).ResizeObserver = ResizeObserverMock as any
}

if (!(globalThis as any).ResizeObserver) {
  ;(globalThis as any).ResizeObserver = ResizeObserverMock as any
}

if (!(globalThis as any).jest) {
  ;(globalThis as any).jest = vi
}

if (typeof window !== 'undefined' && window.HTMLElement) {
  const proto = window.HTMLElement.prototype as any
  if (!proto.setPointerCapture) {
    proto.setPointerCapture = () => {}
  }
  if (!proto.releasePointerCapture) {
    proto.releasePointerCapture = () => {}
  }
  if (!proto.hasPointerCapture) {
    proto.hasPointerCapture = () => false
  }
  if (!proto.scrollIntoView) {
    proto.scrollIntoView = () => {}
  }
}
