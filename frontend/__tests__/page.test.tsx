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
    expect(screen.getByText("XuanwuAI Console")).toBeInTheDocument();
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

  it("renders tools from API", async () => {
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
    expect(await screen.findByText("add")).toBeInTheDocument();
    expect(screen.getByText("Add two numbers")).toBeInTheDocument();
    expect(screen.getByText("demo_calculator")).toBeInTheDocument();
  });
});
