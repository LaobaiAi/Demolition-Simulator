"""Demo: generate frame -> analyze -> report results.

Shows the full pipeline using FrameGenerator and anaStruct.
Run directly: python demo_generate_analyze.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "caiao_servers", "frame_generator"))

from core import FrameGenerator, FrameGeneratorConfig


def demo_generate_and_analyze():
    print("=" * 60)
    print("Frame Generator Demo - Steel Frame")
    print("=" * 60)

    cfg = FrameGeneratorConfig(
        num_bays_x=3,
        num_stories=4,
        span_x_m=6.0,
        story_height_m=3.0,
        material_type="steel",
        steel_grade="Q355",
        dead_load_kpa=5.0,
        live_load_kpa=2.0,
        base_support="fixed",
    )

    gen = FrameGenerator(cfg)
    structure = gen.generate_2d()

    print(f"\n[Model] Frame: {cfg.num_bays_x} bays x {cfg.num_stories} stories")
    print(f"   Material: {cfg.steel_grade} steel")
    print(f"   Span: {cfg.span_x_m}m, Story height: {cfg.story_height_m}m")
    print(f"   Base support: {cfg.base_support}")
    print(f"\n[Stats]")
    print(f"   Nodes: {len(structure['nodes'])}")
    print(f"   Elements: {len(structure['elements'])}")
    print(f"   Supports: {len(structure['supports'])}")
    print(f"   Loads: {len(structure['loads'])}")

    columns = sum(1 for e in structure["elements"] if e["id"] < cfg.num_stories * (cfg.num_bays_x + 1))
    beams = len(structure["elements"]) - columns
    print(f"   Columns: {columns}, Beams: {beams}")

    print(f"\n[Nodes] First 3:")
    for node in structure["nodes"][:3]:
        print(f"   Node {node['id']}: ({node['x']:.1f}, {node['y']:.1f})")

    try:
        print("\n[Analysis] Running anaStruct...")
        from anastruct import SystemElements
        ss = SystemElements()

        node_coords = {n["id"]: (n["x"], n["y"]) for n in structure["nodes"]}
        elem_map = {}
        for elem in structure["elements"]:
            n1 = node_coords[elem["node_i"]]
            n2 = node_coords[elem["node_j"]]
            aid = ss.add_element(location=[n1, n2], EA=elem["E"] * elem["A"], EI=elem["E"] * elem["I"], g=0)
            elem_map[aid] = elem["id"]

        coord_to_ana = {}
        for oid, coord in node_coords.items():
            aid = ss.find_node_id(coord)
            if aid is not None:
                coord_to_ana[oid] = aid

        for s in structure["supports"]:
            aid = coord_to_ana.get(s["node_id"])
            if aid is not None:
                ss.add_support_fixed(node_id=aid)

        for ld in structure["loads"]:
            aid = coord_to_ana.get(ld["node_id"])
            if aid is not None:
                if ld["Fy"] != 0:
                    ss.point_load(node_id=aid, Fy=ld["Fy"])

        ss.solve()

        max_disp = 0
        for nid in sorted(node_coords.keys()):
            aid = coord_to_ana.get(nid)
            if aid is not None:
                d = ss.get_node_displacements(node_id=aid)
                uy = abs(float(d["uy"]))
                if uy > max_disp:
                    max_disp = uy

        print(f"   -> Analysis converged!")
        print(f"   Max displacement: {max_disp * 1000:.1f} mm")

        max_N = 0
        for aid in range(1, len(ss.element_map) + 1):
            try:
                r = ss.get_element_results(element_id=aid, verbose=False)
                N = max(abs(float(r["Nmax"])), abs(float(r["Nmin"])))
                if N > max_N:
                    max_N = N
            except Exception:
                pass

        print(f"   Max axial force: {max_N / 1000:.1f} kN")

    except ImportError:
        print("\n   anaStruct not available. Install: pip install anastruct")
    except Exception as e:
        print(f"\n   Analysis error: {e}")

    print("\n" + "=" * 60)
    print("Demo complete!")
    print("=" * 60)


def demo_concrete_frame():
    print("\n" + "=" * 60)
    print("Frame Generator Demo - Concrete Frame")
    print("=" * 60)

    cfg = FrameGeneratorConfig(
        num_bays_x=2,
        num_stories=3,
        span_x_m=7.0,
        story_height_m=3.5,
        material_type="concrete",
        concrete_grade="C30",
        dead_load_kpa=6.0,
        live_load_kpa=3.0,
    )

    gen = FrameGenerator(cfg)
    structure = gen.generate_2d()

    print(f"\n[Model] {cfg.num_bays_x} bays x {cfg.num_stories} stories")
    print(f"   Material: C30 Concrete, Span: {cfg.span_x_m}m")
    print(f"   Elements: {len(structure['elements'])}")
    print(f"   Column section: {structure['metadata']['column_section']}")
    print(f"   Beam section: {structure['metadata']['beam_section']}")


def demo_natural_language():
    print("\n" + "=" * 60)
    print("Frame Generator Demo - Natural Language")
    print("=" * 60)

    from core import generate_from_natural

    description = "3x4 frame 5 stories 3m height 6m span Q355 steel"
    print(f"\n[Input] \"{description}\"")
    result = generate_from_natural(description)
    m = result["metadata"]
    print(f"-> Generated: {m['bays']} bays, {m['stories']} stories")
    print(f"   Material: {m['material']}, Span: {m['span_m']}m")
    print(f"   Elements: {m['elements_total']}")


if __name__ == "__main__":
    demo_generate_and_analyze()
    demo_concrete_frame()
    demo_natural_language()
