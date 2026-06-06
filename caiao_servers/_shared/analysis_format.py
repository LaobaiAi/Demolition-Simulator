"""Shared analysis result format — standard field names and unit conventions.

Solver-agnostic format that all analysis tools should converge toward.
Currently used for documentation and validation; full normalization is
phased in per-solver as backwards-compatible changes.

STANDARD FORMAT (v1):
{
  "format_version": "1.0",
  "solver": "anaStruct|OpenSees|PyNite|FAPP",
  "node_displacements": [
    {"node_id": int, "ux_m": float, "uy_m": float, "uz_m": float}
  ],
  "element_forces": [
    {"element_id": int, "axial_max_N": float, "shear_max_N": float, "moment_max_Nm": float}
  ],
  "max_displacement_m": float,
  "max_axial_force_N": float
}

CONVERSION FACTORS (use these, never hardcode):
  M_TO_MM  = 1000.0   # meters → millimeters
  N_TO_KN  = 0.001    # newtons → kilonewtons
"""

M_TO_MM = 1000.0
N_TO_KN = 0.001


def annotate_result(raw: dict, solver_name: str) -> dict:
    """Add format_version and solver fields to a raw analysis result.

    Safe to call on any existing solver output — adds metadata without
    changing existing field names or units.  Callers can check
    format_version to decide which field names to read.
    """
    out = dict(raw)
    out.setdefault("format_version", "1.0")
    out["solver"] = solver_name
    return out
