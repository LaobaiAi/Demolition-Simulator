import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import Home from "@/app/page";

// Mock the fetch for /tools endpoint
global.fetch = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Home page", () => {
  it("renders the XuanwuAI Console title", () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ tools: [] }),
    });

    render(<Home />);
    expect(document.title).toBe("XuanwuAI Console");
  });

  it("renders the system status indicator", () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ tools: [] }),
    });

    render(<Home />);
    expect(screen.getByText("System Status")).toBeInTheDocument();
  });

  it("renders the visualization panel placeholder", () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ tools: [] }),
    });

    render(<Home />);
    expect(screen.getByText("Visualization Panel")).toBeInTheDocument();
  });

  it("shows idle status by default", () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ tools: [] }),
    });

    render(<Home />);
    expect(screen.getByText("idle")).toBeInTheDocument();
  });

  it("renders the message input", () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ tools: [] }),
    });

    render(<Home />);
    expect(
      screen.getByPlaceholderText("e.g. Analyze a 2-story 2-bay frame")
    ).toBeInTheDocument();
  });

  it("shows quick action buttons when no messages", () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ tools: [] }),
    });

    render(<Home />);
    expect(screen.getByText("Analyze a 2-story 2-bay frame")).toBeInTheDocument();
    expect(screen.getByText("Analyze a 4-story 3-bay frame")).toBeInTheDocument();
  });

  it("fetches tools from API on mount", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        tools: [
          {
            name: "add",
            description: "Add two numbers",
            input_schema: {},
            server: "demo_calculator",
          },
        ],
      }),
    });

    render(<Home />);
    // Tools are loaded into state; verify fetch was called
    await new Promise((r) => setTimeout(r, 500));
    expect(global.fetch).toHaveBeenCalled();
  });
});
