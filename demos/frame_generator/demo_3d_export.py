"""Demo: generate 3D frame data for visualization/Unity export.

Outputs a complete 3D frame with columns, beams, slabs, and
Three.js-compatible rendering objects.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "caiao_servers", "frame_generator"))

from core import FrameGenerator, FrameGeneratorConfig


def demo_3d_export():
    print("=" * 60)
    print("3D Frame Generator Demo - Unity/Visualization Export")
    print("=" * 60)

    cfg = FrameGeneratorConfig(
        num_bays_x=3,
        num_bays_y=2,
        num_stories=3,
        span_x_m=6.0,
        span_y_m=5.0,
        story_height_m=3.0,
        material_type="concrete",
        concrete_grade="C30",
    )

    gen = FrameGenerator(cfg)
    model = gen.generate_3d()

    m = model["metadata"]
    print(f"\n[Model] 3D Frame: {m['grid']['xFrames']}x{m['grid']['ySpans']} grid, {m['grid']['stories']} stories")
    print(f"   Columns: {len(model['columns'])}")
    print(f"   Beams: {len(model['beams'])}")
    print(f"   Slabs: {len(model['slabs'])}")
    print(f"   Three.js objects: {len(model['threejsObjects'])}")

    print(f"\n[Sample] First column:")
    c = model["columns"][0]
    print(f"   {c['id']}: ({c['start'][0]}, {c['start'][1]}, {c['start'][2]}) -> ({c['end'][0]}, {c['end'][1]}, {c['end'][2]})")
    print(f"   Corner: {c['isCorner']}, Edge: {c['isEdge']}")

    print(f"\n[Sample] First beam:")
    b = model["beams"][0]
    print(f"   {b['id']}: direction={b['direction']}, Story {b['story']}")

    output_path = os.path.join(os.path.dirname(__file__), "output_3d_frame.json")
    with open(output_path, "w") as f:
        json.dump(model, f, indent=2)
    print(f"\n[Export] Saved to: {output_path} ({os.path.getsize(output_path) / 1024:.1f} KB)")

    print("\n" + "=" * 60)
    print("3D demo complete!")
    print("=" * 60)


if __name__ == "__main__":
    demo_3d_export()
