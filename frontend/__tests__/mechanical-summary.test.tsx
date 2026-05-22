import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MechanicalSummary, type StructuralMetrics } from "@/components/mechanical-summary";

function makeMetrics(overrides: Partial<StructuralMetrics> = {}): StructuralMetrics {
  return {
    maxDisplacement: 0.000286,
    maxAxialForce: 50000,
    criticalElementId: 2,
    criticalAxialForce: 50000,
    columnCount: 6,
    failedElements: [],
    ...overrides,
  };
}

describe("MechanicalSummary", () => {
  it("shows empty state when no metrics", () => {
    render(<MechanicalSummary metrics={null} />);
    expect(screen.getByText("Structural Mechanics")).toBeInTheDocument();
    expect(screen.getByText(/Run structural analysis/)).toBeInTheDocument();
  });

  it("shows max displacement in mm", () => {
    render(<MechanicalSummary metrics={makeMetrics({ maxDisplacement: 0.0025 })} />);
    expect(screen.getByText("2.500")).toBeInTheDocument();
    expect(screen.getByText("mm")).toBeInTheDocument();
  });

  it("shows max axial force in kN", () => {
    render(<MechanicalSummary metrics={makeMetrics({ maxAxialForce: 75000 })} />);
    expect(screen.getByText("75.0")).toBeInTheDocument();
    expect(screen.getByText("kN")).toBeInTheDocument();
  });

  it("shows critical element when identified", () => {
    render(<MechanicalSummary metrics={makeMetrics({ criticalElementId: 5 })} />);
    expect(screen.getByText("Element #5")).toBeInTheDocument();
    expect(screen.getByText(/Critical Column/)).toBeInTheDocument();
  });

  it("hides critical element section when null", () => {
    render(
      <MechanicalSummary
        metrics={makeMetrics({ criticalElementId: null, criticalAxialForce: null })}
      />
    );
    expect(screen.queryByText(/Critical Column/)).not.toBeInTheDocument();
  });

  it("shows column count", () => {
    render(<MechanicalSummary metrics={makeMetrics({ columnCount: 8 })} />);
    expect(screen.getByText(/of 8 columns analyzed/)).toBeInTheDocument();
  });

  it("shows demolition targets when failed elements exist", () => {
    render(<MechanicalSummary metrics={makeMetrics({ failedElements: [2, 5] })} />);
    expect(screen.getByText(/Demolition Targets/)).toBeInTheDocument();
    expect(screen.getByText("#2")).toBeInTheDocument();
    expect(screen.getByText("#5")).toBeInTheDocument();
  });

  it("hides demolition targets when empty", () => {
    render(<MechanicalSummary metrics={makeMetrics({ failedElements: [] })} />);
    expect(screen.queryByText(/Demolition Targets/)).not.toBeInTheDocument();
  });

  it("shows critical axial force in kN", () => {
    render(
      <MechanicalSummary metrics={makeMetrics({ criticalElementId: 3, criticalAxialForce: 80000 })} />
    );
    expect(screen.getByText(/80\.0 kN/)).toBeInTheDocument();
  });
});
