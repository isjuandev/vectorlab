import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  sessionStorage.clear();
});

// jsdom no implementa estas APIs del navegador.
class ResizeObserverStub {
  constructor(private cb: ResizeObserverCallback) {}
  observe(el: Element) {
    this.cb([{ contentRect: { width: 800, height: 600 } } as ResizeObserverEntry], this as unknown as ResizeObserver);
    void el;
  }
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
URL.createObjectURL = vi.fn(() => "blob:mock") as typeof URL.createObjectURL;
URL.revokeObjectURL = vi.fn();

// Decodificación simulada: las imágenes "cargan" con 100x80 salvo src "blob:broken".
class ImageStub {
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  naturalWidth = 100;
  naturalHeight = 80;
  set src(v: string) {
    setTimeout(() => (v === "blob:broken" ? this.onerror?.() : this.onload?.()), 0);
  }
}
globalThis.Image = ImageStub as unknown as typeof Image;
