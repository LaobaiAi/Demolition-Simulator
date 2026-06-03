"""IFC export for structural models using IfcOpenShell.

Maps the standard structure JSON format (nodes, elements, loads, supports) to
an IFC 2x3 TC1 hierarchy: IfcProject -> IfcSite -> IfcBuilding -> IfcBuildingStorey.
"""

from __future__ import annotations

import math
import os
from typing import Any

TYPE_TO_IFC: dict[str, str] = {
    "column": "IfcColumn",
    "beam": "IfcBeam",
    "wall": "IfcWall",
    "slab": "IfcSlab",
}


def export_to_ifc(
    structure_json: dict[str, Any],
    filepath: str = "output.ifc",
    export_format: str = "ifc",
) -> dict[str, Any]:
    """Export a structure dict to IFC format.

    Creates the IFC hierarchy: IfcProject -> IfcSite -> IfcBuilding -> IfcBuildingStorey.
    Maps column->IfcColumn, beam->IfcBeam, wall->IfcWall, slab->IfcSlab.

    Args:
        structure_json: Standard structure dict with nodes, elements.
        filepath: Output .ifc file path.
        export_format: 'ifc' for STEP physical file, 'xml' for ifcXML.

    Returns:
        Status dict with filepath and element count, or error if IfcOpenShell
        is not installed.
    """
    try:
        import ifcopenshell
        import ifcopenshell.api as api
    except ImportError:
        return {"status": "error", "message": "IfcOpenShell not installed"}

    nodes = structure_json.get("nodes", [])
    elements = structure_json.get("elements", [])

    if not nodes:
        return {"status": "error", "message": "No nodes in structure"}

    try:
        f = api.run("project.create_file")
        api.run("root.create_entity", file=f, ifc_class="IfcProject", name="XuanwuAI Project")
        api.run("unit.assign_unit", file=f)

        ctx = api.run("context.add_context", file=f, context_type="Model")
        api.run(
            "context.add_context", file=f,
            context_type="Model", context_identifier="Body",
            target_view="MODEL_VIEW",
        )

        # Spatial hierarchy: Project -> Site -> Building
        site = api.run("root.create_entity", file=f, ifc_class="IfcSite", name="Site")
        project = f.by_type("IfcProject")[0]
        api.run("aggregate.assign_object", file=f, relating_object=project, products=[site])

        building = api.run("root.create_entity", file=f, ifc_class="IfcBuilding", name="Building")
        api.run("aggregate.assign_object", file=f, relating_object=site, products=[building])

        # Storey levels from node Y coordinates (our Y = vertical)
        levels = sorted(set(round(n.get("y", 0), 2) for n in nodes))
        storeys: dict[float, Any] = {}
        for level in levels:
            name = f"Story_{levels.index(level)}"
            s = api.run("root.create_entity", file=f, ifc_class="IfcBuildingStorey", name=name)
            s.Elevation = level
            storeys[level] = s
        api.run("aggregate.assign_object", file=f, relating_object=building, products=list(storeys.values()))

        # Body context for shape representations
        body_ctx = None
        for c in f.by_type("IfcGeometricRepresentationContext"):
            if getattr(c, "ContextIdentifier", None) == "Body":
                body_ctx = c
                break
        if body_ctx is None:
            body_ctx = ctx

        node_map = {n["id"]: n for n in nodes}
        element_count = 0

        for elem in elements:
            el_type = elem.get("type", "")
            ifc_class = TYPE_TO_IFC.get(el_type)
            if ifc_class is None:
                continue

            ni = node_map.get(elem["node_i"])
            nj = node_map.get(elem["node_j"])
            if ni is None or nj is None:
                continue

            mx = (ni["x"] + nj["x"]) / 2.0
            my = (ni["y"] + nj["y"]) / 2.0
            mz = (ni["z"] + nj["z"]) / 2.0

            dx = nj["x"] - ni["x"]
            dy = nj["y"] - ni["y"]
            dz = nj["z"] - ni["z"]
            length = math.sqrt(dx * dx + dy * dy + dz * dz)
            if length < 0.001:
                continue

            # Section dimensions from element data
            width = 0.3
            depth = 0.3
            sec = elem.get("section", "")
            if sec and "x" in str(sec).lower():
                try:
                    parts = str(sec).lower().split("x")
                    w = float(parts[0])
                    d = float(parts[1])
                    if w > 5:
                        w /= 1000.0
                    if d > 5:
                        d /= 1000.0
                    width, depth = w, d
                except (ValueError, IndexError):
                    pass

            if el_type == "wall":
                thickness = elem.get("thickness_m", elem.get("thickness", 0.2))
                width = thickness
                depth = max(thickness, length * 0.1)

            if el_type == "slab":
                depth = elem.get("slab_thickness", elem.get("thickness_m", 0.15))
                width = length

            # Placement: our Y-up -> IFC Z-up
            point = f.create_entity("IfcCartesianPoint", (mx, mz, my))
            axis = f.create_entity("IfcAxis2Placement3D", point, None, None)
            placement = f.create_entity("IfcLocalPlacement", RelativePlacement=axis)

            # Extruded solid
            origin = f.create_entity("IfcCartesianPoint", (0.0, 0.0, 0.0))
            z_axis = f.create_entity("IfcDirection", (0.0, 0.0, 1.0))
            profile_place = f.create_entity("IfcAxis2Placement3D", origin, z_axis, None)

            profile = f.create_entity(
                "IfcRectangleProfileDef",
                ProfileType="AREA",
                ProfileName=None,
                Position=f.create_entity("IfcAxis2Placement2D",
                                         f.create_entity("IfcCartesianPoint", (0.0, 0.0))),
                XDim=float(width),
                YDim=float(depth),
            )

            extrude_dir = f.create_entity("IfcDirection", (0.0, 0.0, 1.0))
            solid = f.create_entity(
                "IfcExtrudedAreaSolid", profile, profile_place, extrude_dir, length,
            )

            product = api.run(
                "root.create_entity", file=f, ifc_class=ifc_class,
                name=f"{el_type}_{elem['id']}",
            )
            product.ObjectPlacement = placement

            if body_ctx:
                shape = f.create_entity(
                    "IfcShapeRepresentation", body_ctx, "Body", "SweptSolid", [solid],
                )
                prod_def = f.create_entity("IfcProductDefinitionShape", None, None, [shape])
                product.Representation = prod_def

            base_y = ni["y"]
            nearest = min(storeys.keys(), key=lambda k: abs(k - base_y))
            api.run(
                "aggregate.assign_object", file=f,
                relating_object=storeys[nearest], products=[product],
            )
            element_count += 1

        safe_name = os.path.basename(filepath)
        exports_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "exports")
        os.makedirs(exports_dir, exist_ok=True)
        actual_path = os.path.join(exports_dir, safe_name)
        if export_format.lower() in ("xml", "ifcxml"):
            actual_path = os.path.join(exports_dir, safe_name.rsplit(".", 1)[0] + ".ifcXML")
        f.write(actual_path)

        return {
            "status": "success",
            "file_path": os.path.abspath(actual_path),
            "element_count": element_count,
            "story_count": len(storeys),
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}
