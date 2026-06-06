"""
export_scene_gltf.py — Export current Blender scene to GLTF for WebGL viewing.

Reads scene_base.blend (or current scene), exports to output/gltf/
with embedded textures. Used by the CAIAO pipeline after building.

Environment variables:
  BLENDER_OUTPUT_DIR — where scene_base.blend lives and gltf/ subdir is created
"""
import os
import sys

import bpy

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_THIS_DIR)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)


def main():
    output_dir = os.environ.get("BLENDER_OUTPUT_DIR", os.path.join(_PROJECT_DIR, "output", "blend"))
    blend_path = os.path.join(output_dir, "scene_base.blend")

    if os.path.exists(blend_path):
        bpy.ops.wm.open_mainfile(filepath=blend_path)
        print(f"[GLTF] Loaded: {blend_path}")

    gltf_dir = os.path.join(output_dir, "gltf")
    os.makedirs(gltf_dir, exist_ok=True)

    # Select all mesh objects
    for obj in bpy.data.objects:
        obj.select_set(obj.type == 'MESH')

    gltf_path = os.path.join(gltf_dir, "scene.gltf")
    bpy.ops.export_scene.gltf(
        filepath=gltf_path,
        export_format='GLTF_SEPARATE',
        export_texture_dir="textures",
        export_texcoords=True,
        export_normals=True,
        export_materials='EXPORT',
        use_selection=False,
        export_yup=True,
    )
    print(f"[GLTF] Exported: {gltf_path}")
    print(f"[GLTF_OK] {gltf_path}")

    bin_paths = [os.path.join(gltf_dir, f) for f in os.listdir(gltf_dir) if f.endswith('.bin')]

    file_sizes = {}
    for f in [gltf_path] + bin_paths:
        if os.path.exists(f):
            file_sizes[os.path.basename(f)] = os.path.getsize(f)
    print(f"[GLTF_FILES] {file_sizes}")


if __name__ == "__main__":
    main()
