import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach } from 'vitest';

class ResizeObserverStub {
  observe() {
    // jsdom has no layout: nothing ever resizes
  }
  unobserve() {
    // see observe
  }
  disconnect() {
    // see observe
  }
}
globalThis.ResizeObserver = ResizeObserverStub;

window.matchMedia = (query) =>
  ({
    matches: false,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }) as unknown as MediaQueryList;

beforeEach(() => {
  localStorage.setItem('senda-lang', 'en');
});

afterEach(() => {
  cleanup();
  localStorage.clear();
});
