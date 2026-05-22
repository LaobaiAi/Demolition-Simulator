import "@testing-library/jest-dom/vitest";

// Mock scrollIntoView for jsdom
Element.prototype.scrollIntoView = () => {};

// Mock WebSocket
class MockWebSocket {
  static OPEN = 1;
  readyState = 1;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  send = () => {};
  close = () => {};
}
(global as any).WebSocket = MockWebSocket;
