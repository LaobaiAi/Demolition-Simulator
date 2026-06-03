"""Shared low-level Blender utilities imported by all pipeline scripts.

Uses bpy.data API (not bpy.ops) for geometry creation — no undo stack,
no depsgraph evaluation, no UI context pollution.
"""

import math
import os

import bpy

# ── Paths ────────────────────────────────────────────────────────────────────

_PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(_PIPELINE_DIR, "scripts")
DATA_DIR = os.path.join(_PIPELINE_DIR, "data")
OUTPUT_DIR = os.path.join(_PIPELINE_DIR, "output")
BLEND_DIR = os.environ.get("BLENDER_OUTPUT_DIR", os.path.join(OUTPUT_DIR, "blend"))

os.makedirs(BLEND_DIR, exist_ok=True)


def get_pipeline_paths():
    """Standard paths for pipeline scripts."""
    return {
        "pipeline_dir": _PIPELINE_DIR,
        "data_dir": DATA_DIR,
        "scripts_dir": SCRIPTS_DIR,
        "output_dir": OUTPUT_DIR,
        "blend_dir": BLEND_DIR,
    }


# ── Mesh cache ───────────────────────────────────────────────────────────────

_mesh_cache = {}


def _cube_key(dimensions):
    return tuple(round(d, 4) for d in dimensions)


def _get_or_create_cube_mesh(dimensions):
    """Return a unit-cube mesh scaled to the given (x, y, z) dimensions.

    Same-dimension meshes are shared across all objects — 139 objects may
    share only 5-10 mesh data blocks depending on parameter variety.
    """
    key = _cube_key(dimensions)
    cached = _mesh_cache.get(key)
    if cached and cached.users >= 0:  # mesh may have been removed by clear_scene
        return cached

    mesh = bpy.data.meshes.new(f"CubeMesh_{key[0]:.2f}x{key[1]:.2f}x{key[2]:.2f}")
    verts = [
        (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
        (-0.5, -0.5,  0.5), (0.5, -0.5,  0.5), (0.5, 0.5,  0.5), (-0.5, 0.5,  0.5),
    ]
    faces = [
        (0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
        (2, 6, 7, 3), (0, 3, 7, 4), (1, 5, 6, 2),
    ]
    mesh.from_pydata(verts, [], faces)

    mat = [
        [dimensions[0], 0, 0, 0],
        [0, dimensions[1], 0, 0],
        [0, 0, dimensions[2], 0],
        [0, 0, 0, 1],
    ]
    mesh.transform(mat)
    mesh.update()

    _mesh_cache[key] = mesh
    return mesh


def add_cube(name, location, scale, material=None):
    """Create a mesh cube with given dimensions at location, with optional material.

    Uses low-level data API — no undo stack, no depsgraph flush.
    'scale' is the final object dimensions (width, depth, height).
    """
    mesh = _get_or_create_cube_mesh(scale)
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    bpy.context.collection.objects.link(obj)
    if material:
        obj.data.materials.append(material)
        obj.color = material.diffuse_color
    return obj


def add_cylinder(name, radius, depth, location, rotation_euler, material=None):
    """Create a mesh cylinder with given radius/depth at location.

    Uses low-level data API. rotation_euler is (rx, ry, rz) in radians.
    """
    mesh = bpy.data.meshes.new(name)
    verts = []
    faces = []
    segments = 16

    # Bottom and top center vertices
    verts.append((0, 0, -depth / 2))   # 0: bottom center
    verts.append((0, 0,  depth / 2))   # 1: top center

    # Ring vertices
    for i in range(segments):
        angle = 2 * math.pi * i / segments
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        verts.append((x, y, -depth / 2))  # 2+i: bottom ring
        verts.append((x, y,  depth / 2))  # 2+segments+i: top ring

    # Bottom cap
    for i in range(segments):
        faces.append((0, 2 + (i + 1) % segments, 2 + i))
    # Top cap
    for i in range(segments):
        faces.append((1, 2 + segments + i, 2 + segments + (i + 1) % segments))
    # Side faces
    for i in range(segments):
        next_i = (i + 1) % segments
        faces.append((2 + i, 2 + next_i, 2 + segments + next_i, 2 + segments + i))

    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    obj.rotation_euler = rotation_euler
    bpy.context.collection.objects.link(obj)
    if material:
        obj.data.materials.append(material)
    return obj


# ── Materials ────────────────────────────────────────────────────────────────

def make_material(name, base_rgb, roughness=0.5, emission_strength=0.0, emission_color=None):
    """Create a Principled BSDF material with given base color and optional emission."""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = (*base_rgb, 1.0)
    bsdf.inputs['Roughness'].default_value = roughness
    if emission_strength > 0 and emission_color:
        bsdf.inputs['Emission Color'].default_value = emission_color
        bsdf.inputs['Emission Strength'].default_value = emission_strength
    out = nodes.new(type='ShaderNodeOutputMaterial')
    mat.node_tree.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    mat.diffuse_color = (*base_rgb, 1.0)
    return mat


# ── Scene helpers ────────────────────────────────────────────────────────────

def clear_scene():
    """Remove all objects, meshes, and materials from the scene. Low-level API."""
    _mesh_cache.clear()
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    for mat in list(bpy.data.materials):
        if mat.users == 0:
            bpy.data.materials.remove(mat)


def compute_scene_bounds(exclude_ground=True):
    """Return bounding box dict for all MESH objects in the scene.

    Returns None if no mesh objects found.
    """
    min_x = min_y = min_z = float('inf')
    max_x = max_y = max_z = float('-inf')

    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        if exclude_ground and obj.name == 'Ground':
            continue
        for vert in obj.data.vertices:
            wc = obj.matrix_world @ vert.co
            min_x = min(min_x, wc.x)
            max_x = max(max_x, wc.x)
            min_y = min(min_y, wc.y)
            max_y = max(max_y, wc.y)
            min_z = min(min_z, wc.z)
            max_z = max(max_z, wc.z)

    if min_x == float('inf'):
        return None

    return {
        'min_x': min_x, 'max_x': max_x,
        'min_y': min_y, 'max_y': max_y,
        'min_z': min_z, 'max_z': max_z,
        'width': max_x - min_x, 'depth': max_y - min_y, 'height': max_z - min_z,
        'cx': (min_x + max_x) / 2, 'cy': (min_y + max_y) / 2, 'cz': (min_z + max_z) / 2,
        'diagonal': math.sqrt(
            (max_x - min_x) ** 2 + (max_y - min_y) ** 2 + (max_z - min_z) ** 2
        ),
    }


def save_blend(filename):
    """Save current blend file to BLEND_DIR. Operator — unavoidable for .blend I/O."""
    path = os.path.join(BLEND_DIR, filename)
    bpy.ops.wm.save_as_mainfile(filepath=path)
    print(f"  [OK] 保存: {path}")
    return path
