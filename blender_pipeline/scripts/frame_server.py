"""Blender Frame Server — persistent viewport streaming and command server.

Runs inside Blender (blender --python frame_server.py, no --background).
Provides the same capabilities as Unity's FrameServer.cs + SimulationController.cs:
  TCP :5007 — JSON command server (build_frame, demolish, reset)
  :5008 — HTTP/WebSocket BMP frame streaming (same protocol as Unity FrameServer)

Protocol compatibility with frontend/components/unity-video-panel.tsx
"""

import bpy
import bmesh
import struct
import socket
import threading
import hashlib
import base64
import json
import os
import io
import time
import math
import atexit
import sys
import tempfile
import traceback

try:
    from _common import add_cube, clear_scene, BLEND_DIR, setup_gradient_sky
except ImportError:
    BLEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output", "blend")
    os.makedirs(BLEND_DIR, exist_ok=True)

    def clear_scene():
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in list(bpy.data.meshes):
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        for mat in list(bpy.data.materials):
            if mat.users == 0:
                bpy.data.materials.remove(mat)

    def add_cube(name, location, scale):
        mesh = bpy.data.meshes.new(name)
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
            [scale[0], 0, 0, 0],
            [0, scale[1], 0, 0],
            [0, 0, scale[2], 0],
            [0, 0, 0, 1],
        ]
        mesh.transform(mat)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        obj.location = location
        bpy.context.collection.objects.link(obj)
        return obj


CMD_PORT = 5007
STREAM_PORT = 5008
CAPTURE_FPS = 0
STREAM_WIDTH = 1280
STREAM_HEIGHT = 720
RENDER_SAMPLES = 64

_latest_frame_bmp = None
_frame_seq = 0
_frame_lock = threading.Lock()
_is_running = True
_capture_timer = None
_ws_clients = []
_ws_clients_lock = threading.Lock()
_element_objects = {}
_cmd_queue = []
_cmd_queue_lock = threading.Lock()
_CMD_POLL_INTERVAL = 0.1

WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

COLS = {"column": (0.65, 0.56, 0.48, 1.0), "beam": (0.62, 0.66, 0.70, 1.0),
        "beam_x": (0.62, 0.66, 0.70, 1.0), "beam_y": (0.66, 0.70, 0.64, 1.0),
        "slab": (0.82, 0.78, 0.72, 1.0), "unknown": (0.55, 0.55, 0.60, 1.0)}


def make_material(name, rgba):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = rgba
    bsdf.inputs['Roughness'].default_value = 0.6
    out = nodes.new(type='ShaderNodeOutputMaterial')
    mat.node_tree.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    mat.diffuse_color = rgba
    return mat


def _get_element_name(elem):
    eid = elem.get("id", 0)
    etype = elem.get("type", "unknown")
    return f"EL_{etype}_{eid}"


def _ensure_camera():
    if bpy.context.scene.camera:
        return
    for obj in bpy.data.objects:
        if obj.type == 'CAMERA':
            bpy.context.scene.camera = obj
            return
    bpy.ops.object.camera_add(location=(15, -15, 10))
    cam = bpy.context.active_object
    cam.name = "MainCamera"
    bpy.context.scene.camera = cam
    cam.data.lens = 28.0
    cam.data.clip_end = 500.0


def _frame_camera_to_scene():
    min_x = min_y = min_z = float('inf')
    max_x = max_y = max_z = float('-inf')
    has_mesh = False
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or obj.name == 'Ground':
            continue
        has_mesh = True
        for v in obj.data.vertices:
            wc = obj.matrix_world @ v.co
            min_x = min(min_x, wc.x)
            max_x = max(max_x, wc.x)
            min_y = min(min_y, wc.y)
            max_y = max(max_y, wc.y)
            min_z = min(min_z, wc.z)
            max_z = max(max_z, wc.z)
    if not has_mesh:
        return
    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2
    cz = (min_z + max_z) / 2
    diag = math.sqrt((max_x - min_x) ** 2 + (max_y - min_y) ** 2 + (max_z - min_z) ** 2)
    if diag < 1:
        diag = 50
    dist = diag * 1.2
    cam = bpy.context.scene.camera
    if cam:
        cam.location = (cx + dist * 0.6, cy + dist * 0.6, cz + dist * 0.45)
        cam.data.lens = 24.0
        cam.data.clip_end = max(diag * 3, 500)
        constraint = cam.constraints[0] if cam.constraints else cam.constraints.new(type='TRACK_TO')
        empty_name = 'CameraTarget'
        target = bpy.data.objects.get(empty_name)
        if not target:
            target = bpy.data.objects.new(empty_name, None)
            bpy.context.collection.objects.link(target)
        target.location = (cx, cy, cz * 0.6)
        constraint.target = target


def _request_capture():
    """Schedule a render on the main thread."""
    def _do_capture():
        capture_frame()
    bpy.app.timers.register(_do_capture, first_interval=0.1)


def handle_build_frame(data):
    global _element_objects
    nodes_data = data.get("nodes", [])
    elements = data.get("elements", [])

    if not nodes_data or not elements:
        return {"status": "error", "message": "nodes and elements required"}

    nodes = {n["id"]: (n["x"], n["y"], n.get("z", 0)) for n in nodes_data}

    mats = {}
    for key, rgba in COLS.items():
        mats[key] = make_material(f"Mat_{key}", rgba)

    created = 0
    _element_objects = {}

    for elem in elements:
        eid = elem.get("id", 0)
        ni = elem.get("node_i")
        nj = elem.get("node_j")
        etype = elem.get("type", "unknown")

        if ni not in nodes or nj not in nodes:
            continue

        x1, y1, z1 = nodes[ni]
        x2, y2, z2 = nodes[nj]

        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        cz = (z1 + z2) / 2

        dx = x2 - x1
        dy = y2 - y1
        dz = z2 - z1
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length < 0.001:
            continue

        section = elem.get("section", {})
        if isinstance(section, str):
            radius = 0.25
        elif isinstance(section, dict):
            w = section.get("width", section.get("b", 0.3))
            h = section.get("height", section.get("h", 0.3))
            radius = max(w, h) * 0.8
        else:
            radius = 0.25

        name = _get_element_name(elem)
        mat = mats.get(etype, mats["unknown"])

        bpy.ops.mesh.primitive_cylinder_add(
            vertices=8, radius=radius, depth=length,
            location=(cx, cy, cz)
        )
        obj = bpy.context.active_object
        obj.name = name

        if abs(dz - length) < 0.001:
            pass
        elif abs(dy - length) < 0.001:
            obj.rotation_euler = (math.pi / 2, 0, 0)
        elif abs(dx - length) < 0.001:
            obj.rotation_euler = (0, math.pi / 2, 0)
        else:
            direction = (dx / length, dy / length, dz / length)
            z_axis = (0, 0, 1)
            if abs(direction[0]) < 0.001 and abs(direction[1]) < 0.001:
                pass
            else:
                rot_axis = (
                    -direction[1],
                    direction[0],
                    0
                )
                rot_axis_len = math.sqrt(rot_axis[0] ** 2 + rot_axis[1] ** 2)
                if rot_axis_len > 0.0001:
                    rot_axis = (rot_axis[0] / rot_axis_len, rot_axis[1] / rot_axis_len, 0)
                    angle = math.acos(direction[2])
                    obj.rotation_mode = 'AXIS_ANGLE'
                    obj.rotation_axis_angle = (angle, rot_axis[0], rot_axis[1], rot_axis[2])

        if mat:
            obj.data.materials.append(mat)
            obj.color = mat.diffuse_color
        obj["element_id"] = eid
        obj["element_type"] = etype
        _element_objects[eid] = obj
        created += 1

    _frame_camera_to_scene()
    _ensure_camera()

    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.overlay.show_overlays = False
                        space.overlay.show_axis_x = False
                        space.overlay.show_axis_y = False
                        space.overlay.show_axis_z = False
                        space.overlay.show_floor = False
                        space.overlay.show_cursor = False
                        space.overlay.show_object_origins = False
                        space.overlay.show_relationship_lines = False
                        space.shading.type = 'SOLID'
                        space.shading.color_type = 'MATERIAL'
                        space.shading.light = 'FLAT'
                        space.shading.show_specular_highlight = False
                        space.shading.background_type = 'VIEWPORT'
                        space.shading.background_color = (0.50, 0.70, 0.95)
                        space.shading.light = 'FLAT'
                        space.shading.show_specular_highlight = False
                        space.shading.show_object_outline = False

    print(f"[FrameServer] Built {created} elements from {len(elements)} input elements")
    _request_capture()
    return {"status": "ok", "element_count": created}


def handle_demolish(data):
    global _element_objects
    failed = data.get("failed_elements", [])
    removed = 0
    for eid in failed:
        if eid in _element_objects:
            obj = _element_objects[eid]
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
                removed += 1
            except Exception:
                pass
            del _element_objects[eid]
    print(f"[FrameServer] Demolished {removed} elements")
    _request_capture()
    return {"status": "ok", "removed": removed}


def handle_load_blend(data):
    path = data.get("path", "")
    if not path or not os.path.exists(path):
        return {"status": "error", "message": f"Blend file not found: {path}"}
    def _do_load():
        try:
            keep_names = {'MainCamera', 'Ground', 'Sun_Light', 'Fill_Light', 'CameraTarget'}
            for obj in list(bpy.data.objects):
                if obj.name not in keep_names and obj.type in ('MESH', 'CURVE', 'FONT', 'SURFACE'):
                    try:
                        bpy.data.objects.remove(obj, do_unlink=True)
                    except Exception:
                        pass
            with bpy.data.libraries.load(path, link=False) as (data_from, data_to):
                data_to.objects = data_from.objects
            for obj in data_to.objects:
                if obj is not None:
                    try:
                        bpy.context.collection.objects.link(obj)
                    except Exception:
                        pass
            _frame_camera_to_scene()
            _ensure_camera()
            _request_capture()
            mesh_count = len([o for o in bpy.data.objects if o.type == 'MESH'])
            _log(f"loaded {mesh_count} objects from {os.path.basename(path)}")
            print(f"[FrameServer] Loaded {mesh_count} objects from: {path}")
        except Exception as e:
            _log(f"load_blend_error: {e}")
            traceback.print_exc()
        return None
    bpy.app.timers.register(_do_load, first_interval=0.5)
    return {"status": "ok", "path": path, "message": "Importing objects into scene"}


def handle_reset(data):
    global _element_objects, _latest_frame_bmp, _frame_seq
    clear_scene()
    _element_objects = {}
    with _frame_lock:
        _latest_frame_bmp = None
        _frame_seq = 0
    _ensure_camera()
    print("[FrameServer] Scene reset")
    _request_capture()
    return {"status": "ok"}


def _process_cmd_queue():
    """Main-thread timer: drain command queue and execute handlers safely."""
    global _cmd_queue
    with _cmd_queue_lock:
        if not _cmd_queue:
            return _CMD_POLL_INTERVAL
        items = _cmd_queue
        _cmd_queue = []
    for data, conn in items:
        action = data.get("action", "")
        handler = _handlers.get(action)
        try:
            if handler:
                result = handler(data)
            else:
                result = {"status": "error", "message": f"Unknown action: {action}"}
        except Exception as e:
            result = {"status": "error", "message": str(e)}
            traceback.print_exc()
        try:
            response = json.dumps(result).encode("utf-8")
            conn.sendall(response)
            print(f"[FrameServer] CMD {action} → {result.get('status', '?')}")
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
    return _CMD_POLL_INTERVAL


_handlers = {
    "build_frame": handle_build_frame,
    "demolish": handle_demolish,
    "reset": handle_reset,
    "load_blend": handle_load_blend,
}


def cmd_server_thread():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", CMD_PORT))
        sock.listen(5)
        sock.settimeout(2.0)
        print(f"[FrameServer] TCP command server on :{CMD_PORT}")
    except OSError as e:
        print(f"[FrameServer] WARNING: Cannot bind TCP :{CMD_PORT} — {e}")
        return

    while _is_running:
        try:
            conn, addr = sock.accept()
        except socket.timeout:
            continue
        except Exception:
            break

        try:
            conn.settimeout(5.0)
            raw = conn.recv(65536)
            if raw:
                try:
                    data = json.loads(raw.decode("utf-8").strip())
                except json.JSONDecodeError:
                    conn.sendall(json.dumps({"status": "error", "message": "Invalid JSON"}).encode("utf-8"))
                    conn.close()
                    continue
                with _cmd_queue_lock:
                    _cmd_queue.append((data, conn))
        except socket.timeout:
            try:
                conn.close()
            except Exception:
                pass
        except Exception as e:
            print(f"[FrameServer] CMD accept error: {e}")
            try:
                conn.close()
            except Exception:
                pass

    try:
        sock.close()
    except Exception:
        pass


def _setup_render_settings():
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = STREAM_WIDTH
    scene.render.resolution_y = STREAM_HEIGHT
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.display_settings.display_device = 'sRGB'
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'


def capture_frame():
    global _latest_frame_bmp, _frame_seq
    if not _is_running:
        return

    tmpdir = tempfile.gettempdir()
    tmppath = os.path.join(tmpdir, "_blender_frame.png")

    try:
        scene = bpy.context.scene
        scene.render.engine = 'BLENDER_WORKBENCH'
        scene.render.resolution_x = STREAM_WIDTH
        scene.render.resolution_y = STREAM_HEIGHT
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = 'PNG'
        scene.render.filepath = tmppath

        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    for space in area.spaces:
                        if space.type == 'VIEW_3D':
                            space.shading.type = 'SOLID'
                            space.shading.color_type = 'MATERIAL'
                            space.shading.light = 'STUDIO'
                            space.shading.show_specular_highlight = True
                            space.shading.show_backface_culling = True
                            space.shading.studio_light = 'basic.sl'

        bpy.ops.render.opengl(write_still=True)

        if os.path.exists(tmppath):
            with open(tmppath, "rb") as f:
                png_data = f.read()
            bmp = _png_to_bmp(png_data, STREAM_WIDTH, STREAM_HEIGHT)
            if bmp:
                with _frame_lock:
                    _latest_frame_bmp = bmp
                    _frame_seq += 1
            try:
                os.remove(tmppath)
            except Exception:
                pass
    except Exception as e:
        print(f"[FrameServer] Capture error: {e}")
        traceback.print_exc()


def _png_to_bmp(png_data, width, height):
    try:
        import struct as _struct
        import zlib as _zlib

        if png_data[:8] != b'\x89PNG\r\n\x1a\n':
            return None

        pos = 8
        width_read = height_read = 0
        pixels = None

        while pos < len(png_data):
            chunk_len = _struct.unpack(">I", png_data[pos:pos + 4])[0]
            chunk_type = png_data[pos + 4:pos + 8]
            chunk_data = png_data[pos + 8:pos + 8 + chunk_len]
            pos += 12 + chunk_len

            if chunk_type == b'IHDR':
                width_read = _struct.unpack(">I", chunk_data[0:4])[0]
                height_read = _struct.unpack(">I", chunk_data[4:8])[0]
            elif chunk_type == b'IDAT':
                if pixels is None:
                    pixels = chunk_data
                else:
                    pixels += chunk_data
            elif chunk_type == b'IEND':
                break

        if pixels is None or width_read == 0:
            return None

        raw_data = _zlib.decompress(pixels)

        bytes_per_pixel = 3 if png_data.find(b'RGB') != -1 else 4
        has_alpha = bytes_per_pixel == 4
        row_size = width_read * bytes_per_pixel + (1 if not has_alpha else 0)

        rgba_rows = []
        pos = 0
        for y in range(height_read):
            if not has_alpha:
                filter_byte = raw_data[pos]
                pos += 1
            row = []
            for x in range(width_read):
                r = raw_data[pos]
                g = raw_data[pos + 1]
                b = raw_data[pos + 2]
                a = raw_data[pos + 3] if has_alpha else 255
                row.append((r, g, b, a))
                pos += bytes_per_pixel
            rgba_rows.append(row)

        if width_read != width or height_read != height:
            rgba_rows = _resize_rgba(rgba_rows, width_read, height_read, width, height)

        bmp_row_size = ((width * 3 + 3) // 4) * 4
        pixel_data_size = bmp_row_size * height
        file_size = 14 + 40 + pixel_data_size
        bmp = bytearray(file_size)

        bmp[0] = 0x42
        bmp[1] = 0x4D
        _struct.pack_into("<I", bmp, 2, file_size)
        _struct.pack_into("<I", bmp, 10, 54)
        _struct.pack_into("<I", bmp, 14, 40)
        _struct.pack_into("<I", bmp, 18, width)
        _struct.pack_into("<I", bmp, 22, height)
        _struct.pack_into("<H", bmp, 26, 1)
        _struct.pack_into("<H", bmp, 28, 24)
        _struct.pack_into("<I", bmp, 34, pixel_data_size)

        for y in range(height):
            row = rgba_rows[height - 1 - y]
            row_start = 54 + y * bmp_row_size
            for x in range(width):
                r, g, b, a = row[x]
                di = row_start + x * 3
                bmp[di] = b
                bmp[di + 1] = g
                bmp[di + 2] = r

        return bytes(bmp)
    except Exception as e:
        print(f"[FrameServer] PNG→BMP error: {e}")
        return None


def _resize_rgba(rgba_rows, src_w, src_h, dst_w, dst_h):
    result = []
    for y in range(dst_h):
        row = []
        src_y = y * src_h / dst_h
        for x in range(dst_w):
            src_x = x * src_w / dst_w
            si = int(src_y)
            sj = int(src_x)
            si = max(0, min(src_h - 1, si))
            sj = max(0, min(src_w - 1, sj))
            row.append(rgba_rows[si][sj])
        result.append(row)
    return result


def compute_ws_accept(key):
    sha1 = hashlib.sha1((key + WS_MAGIC).encode("ascii")).digest()
    return base64.b64encode(sha1).decode("ascii")


def send_ws_frame(sock, data):
    header = bytearray()
    header.append(0x82)
    length = len(data)
    if length < 126:
        header.append(length)
    elif length <= 0xFFFF:
        header.append(126)
        header.append((length >> 8) & 0xFF)
        header.append(length & 0xFF)
    else:
        header.append(127)
        for i in range(7, -1, -1):
            header.append((length >> (i * 8)) & 0xFF)
    sock.sendall(bytes(header))
    sock.sendall(data)


def handle_http_client(conn, addr):
    try:
        conn.settimeout(5.0)
        raw = conn.recv(8192)
        if not raw:
            conn.close()
            return

        request = raw.decode("ascii", errors="replace")
        lines = request.split("\r\n")
        first_line = lines[0] if lines else ""

        if first_line.startswith("GET /health"):
            serve_health(conn)
        elif "Upgrade: websocket" in request or "upgrade: websocket" in request:
            handle_ws_upgrade(conn, request)
        elif first_line.startswith("GET "):
            serve_http_frame(conn)
        elif first_line.startswith("HEAD "):
            resp = "HTTP/1.1 200 OK\r\nContent-Length: 0\r\nAccess-Control-Allow-Origin: *\r\n\r\n"
            conn.sendall(resp.encode("ascii"))
            conn.close()
        else:
            conn.close()
    except socket.timeout:
        conn.close()
    except Exception as e:
        print(f"[FrameServer] HTTP error: {e}")
        try:
            conn.close()
        except Exception:
            pass


def serve_health(conn):
    age = -1.0
    seq = 0
    with _frame_lock:
        seq = _frame_seq
    clients = 0
    with _ws_clients_lock:
        clients = len(_ws_clients)

    body = json.dumps({
        "status": "ok",
        "frame_seq": seq,
        "capture_fps": CAPTURE_FPS,
        "ws_clients": clients,
        "resolution": f"{STREAM_WIDTH}x{STREAM_HEIGHT}",
    })
    resp = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "\r\n"
        + body
    )
    conn.sendall(resp.encode("utf-8"))
    conn.close()


def serve_http_frame(conn):
    bmp = None
    with _frame_lock:
        bmp = _latest_frame_bmp

    if bmp:
        headers = (
            "HTTP/1.1 200 OK\r\n"
            f"Content-Type: image/bmp\r\n"
            f"Content-Length: {len(bmp)}\r\n"
            "Cache-Control: no-cache, no-store, must-revalidate\r\n"
            "Pragma: no-cache\r\n"
            "Expires: 0\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            "\r\n"
        )
        conn.sendall(headers.encode("ascii"))
        conn.sendall(bmp)
    else:
        body = '{"status":"no_frame"}'
        resp = (
            "HTTP/1.1 503 Service Unavailable\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            "\r\n"
            + body
        )
        conn.sendall(resp.encode("ascii"))
    conn.close()


def handle_ws_upgrade(conn, request):
    key = None
    for line in request.split("\r\n"):
        if line.lower().startswith("sec-websocket-key:"):
            key = line.split(":", 1)[1].strip()
            break

    if not key:
        conn.close()
        return

    accept = compute_ws_accept(key)
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        "\r\n"
    )
    conn.sendall(response.encode("ascii"))

    with _ws_clients_lock:
        _ws_clients.append(conn)
    print(f"[FrameServer] WS client connected (total: {len(_ws_clients)})")

    last_seq = -1
    try:
        conn.settimeout(1.0)
        while _is_running:
            bmp = None
            seq = 0
            with _frame_lock:
                bmp = _latest_frame_bmp
                seq = _frame_seq

            if bmp and seq != last_seq:
                try:
                    send_ws_frame(conn, bmp)
                    last_seq = seq
                except (socket.error, BrokenPipeError, ConnectionResetError):
                    break

            time.sleep(0.15)
    except Exception:
        pass
    finally:
        with _ws_clients_lock:
            if conn in _ws_clients:
                _ws_clients.remove(conn)
        try:
            conn.close()
        except Exception:
            pass
        print(f"[FrameServer] WS client disconnected (remaining: {len(_ws_clients)})")


def stream_server_thread():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", STREAM_PORT))
        sock.listen(10)
        sock.settimeout(2.0)
        print(f"[FrameServer] Stream server on :{STREAM_PORT} ({CAPTURE_FPS} FPS, {STREAM_WIDTH}x{STREAM_HEIGHT})")
    except OSError as e:
        print(f"[FrameServer] WARNING: Cannot bind stream :{STREAM_PORT} — {e}")
        return

    while _is_running:
        try:
            conn, addr = sock.accept()
        except socket.timeout:
            continue
        except Exception:
            break

        t = threading.Thread(target=handle_http_client, args=(conn, addr), daemon=True)
        t.start()

    with _ws_clients_lock:
        for c in _ws_clients:
            try:
                c.close()
            except Exception:
                pass
        _ws_clients.clear()
    try:
        sock.close()
    except Exception:
        pass


def _register_capture_timer():
    def _capture_wrapper():
        capture_frame()
        return 1.0 / CAPTURE_FPS

    bpy.app.timers.register(_capture_wrapper, first_interval=1.0)
    print(f"[FrameServer] Frame capture registered @ {CAPTURE_FPS} FPS")


def _cleanup():
    global _is_running
    _is_running = False
    time.sleep(0.3)
    with _ws_clients_lock:
        for c in _ws_clients:
            try:
                c.close()
            except Exception:
                pass
        _ws_clients.clear()
    print("[FrameServer] Cleanup complete")


def _delayed_start():
    _log("delayed_start_begin")
    atexit.register(_cleanup)

    try:
        layout_screen = bpy.data.screens.get('Layout')
        if layout_screen:
            for window in bpy.context.window_manager.windows:
                window.screen = layout_screen
            _log("switched_to_layout")
    except Exception as e:
        _log(f"layout_switch_error: {e}")

    bpy.app.timers.register(_process_cmd_queue, first_interval=0.2)

    cmd = threading.Thread(target=cmd_server_thread, daemon=True, name="BlenderCMD")
    cmd.start()

    stream = threading.Thread(target=stream_server_thread, daemon=True, name="BlenderStream")
    stream.start()

    _ensure_camera()

    removed_lights = 0
    for obj in list(bpy.data.objects):
        if obj.type == 'LIGHT':
            bpy.data.objects.remove(obj, do_unlink=True)
            removed_lights += 1
    removed_meshes = 0
    for obj in list(bpy.data.objects):
        if obj.type in ('MESH', 'CURVE', 'META', 'FONT', 'SURFACE'):
            bpy.data.objects.remove(obj, do_unlink=True)
            removed_meshes += 1
    _log(f"cleaned: lights={removed_lights} meshes={removed_meshes}")

    try:
        setup_gradient_sky()
    except NameError:
        world = bpy.context.scene.world
        if not world:
            world = bpy.data.worlds.new('World')
            bpy.context.scene.world = world
        world.use_nodes = True
        wn = world.node_tree.nodes
        wl = world.node_tree.links
        wn.clear()
        geom = wn.new(type='ShaderNodeNewGeometry')
        sep = wn.new(type='ShaderNodeSeparateXYZ')
        wl.new(geom.outputs['Incoming'], sep.inputs['Vector'])
        map_range = wn.new(type='ShaderNodeMapRange')
        map_range.inputs['From Min'].default_value = -1.0
        map_range.inputs['From Max'].default_value = 1.0
        map_range.inputs['To Min'].default_value = 0.0
        map_range.inputs['To Max'].default_value = 1.0
        wl.new(sep.outputs['Z'], map_range.inputs['Value'])
        ramp = wn.new(type='ShaderNodeValToRGB')
        ramp.color_ramp.interpolation = 'B_SPLINE'
        while len(ramp.color_ramp.elements) < 5:
            ramp.color_ramp.elements.new(0.0)
        ramp.color_ramp.elements[0].position = 0.00
        ramp.color_ramp.elements[0].color = (0.475, 0.490, 0.451, 1.0)
        ramp.color_ramp.elements[1].position = 0.35
        ramp.color_ramp.elements[1].color = (0.627, 0.651, 0.608, 1.0)
        ramp.color_ramp.elements[2].position = 0.48
        ramp.color_ramp.elements[2].color = (0.820, 0.863, 0.925, 1.0)
        ramp.color_ramp.elements[3].position = 0.55
        ramp.color_ramp.elements[3].color = (0.702, 0.820, 0.949, 1.0)
        ramp.color_ramp.elements[4].position = 1.00
        ramp.color_ramp.elements[4].color = (0.478, 0.675, 0.925, 1.0)
        wl.new(map_range.outputs['Result'], ramp.inputs['Fac'])
        bg = wn.new(type='ShaderNodeBackground')
        bg.inputs['Strength'].default_value = 1.0
        wl.new(ramp.outputs['Color'], bg.inputs['Color'])
        out = wn.new(type='ShaderNodeOutputWorld')
        wl.new(bg.outputs['Background'], out.inputs['Surface'])
    _log("world_set")

    try:
        _build_demo_frame()
        obj_count = len(bpy.data.objects)
        _log(f"demo_built: objects={obj_count}")
    except Exception as e:
        _log(f"demo_error: {e}")
        traceback.print_exc()

    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    for region in area.regions:
                        if region.type == 'WINDOW':
                            try:
                                with bpy.context.temp_override(area=area, region=region):
                                    bpy.ops.view3d.view_all(center=True)
                                _log("view_all_ok")
                            except Exception as e:
                                _log(f"view_all_error: {e}")
                            break
                    break
    except Exception as e:
        _log(f"view_all_fatal: {e}")

    _request_capture()
    _setup_viewport()

    try:
        blend_path = os.path.join(BLEND_DIR, "demo_scene.blend")
        bpy.ops.wm.save_as_mainfile(filepath=blend_path)
        _log(f"saved: {blend_path}")
    except Exception as e:
        _log(f"save_error: {e}")

    try:
        bpy.context.view_layer.update()
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass

    _log("delayed_start_done")
    return None


def _build_demo_frame():
    nodes_data = [
        {"id": 1, "x": 0, "y": 0, "z": 0},
        {"id": 2, "x": 6, "y": 0, "z": 0},
        {"id": 3, "x": 0, "y": 6, "z": 0},
        {"id": 4, "x": 6, "y": 6, "z": 0},
        {"id": 5, "x": 0, "y": 0, "z": 4},
        {"id": 6, "x": 6, "y": 0, "z": 4},
        {"id": 7, "x": 0, "y": 6, "z": 4},
        {"id": 8, "x": 6, "y": 6, "z": 4},
    ]
    elements_data = [
        {"id": 1, "node_i": 1, "node_j": 2, "type": "beam", "section": {"width": 0.3, "height": 0.5}},
        {"id": 2, "node_i": 3, "node_j": 4, "type": "beam", "section": {"width": 0.3, "height": 0.5}},
        {"id": 3, "node_i": 1, "node_j": 3, "type": "beam", "section": {"width": 0.3, "height": 0.5}},
        {"id": 4, "node_i": 2, "node_j": 4, "type": "beam", "section": {"width": 0.3, "height": 0.5}},
        {"id": 5, "node_i": 1, "node_j": 5, "type": "column", "section": {"width": 0.4, "height": 0.4}},
        {"id": 6, "node_i": 2, "node_j": 6, "type": "column", "section": {"width": 0.4, "height": 0.4}},
        {"id": 7, "node_i": 3, "node_j": 7, "type": "column", "section": {"width": 0.4, "height": 0.4}},
        {"id": 8, "node_i": 4, "node_j": 8, "type": "column", "section": {"width": 0.4, "height": 0.4}},
        {"id": 9, "node_i": 5, "node_j": 6, "type": "beam", "section": {"width": 0.3, "height": 0.5}},
        {"id": 10, "node_i": 7, "node_j": 8, "type": "beam", "section": {"width": 0.3, "height": 0.5}},
        {"id": 11, "node_i": 5, "node_j": 7, "type": "beam", "section": {"width": 0.3, "height": 0.5}},
        {"id": 12, "node_i": 6, "node_j": 8, "type": "beam", "section": {"width": 0.3, "height": 0.5}},
    ]
    handle_build_frame({"nodes": nodes_data, "elements": elements_data})

    bpy.ops.mesh.primitive_plane_add(size=50, location=(3, 3, -0.05))
    floor_mat = bpy.data.materials.new('Ground')
    floor_mat.diffuse_color = (0.38, 0.44, 0.36, 1.0)
    floor_obj = bpy.context.active_object
    floor_obj.data.materials.append(floor_mat)
    floor_obj.color = floor_mat.diffuse_color
    floor_obj.name = 'Ground'

    sun_data = bpy.data.lights.new(name='Sun_Light', type='SUN')
    sun_data.energy = 3.5
    sun_data.angle = 0.05
    sun_obj = bpy.data.objects.new(name='Sun_Light', object_data=sun_data)
    bpy.context.collection.objects.link(sun_obj)
    sun_obj.location = (25, 20, 30)

    fill_data = bpy.data.lights.new(name='Fill_Light', type='SUN')
    fill_data.energy = 1.0
    fill_data.angle = 0.1
    fill_obj = bpy.data.objects.new(name='Fill_Light', object_data=fill_data)
    bpy.context.collection.objects.link(fill_obj)
    fill_obj.location = (-10, -10, 10)


def _log(msg):
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output", "blend", "_startup.log"), "a") as f:
            f.write(str(msg) + "\n")
    except Exception:
        pass


def _setup_viewport():
    configured = 0
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    for space in area.spaces:
                        if space.type == 'VIEW_3D':
                            space.shading.type = 'SOLID'
                            space.shading.color_type = 'MATERIAL'
                            space.shading.light = 'STUDIO'
                            space.shading.show_specular_highlight = True
                            space.shading.show_backface_culling = True
                            space.shading.studio_light = 'basic.sl'
                            configured += 1
    except Exception as e:
        _log(f"viewport_error: {e}")
    if configured == 0:
        _log("viewport_retry")
        return 0.5
    _log(f"viewport_ok: {configured}")
    return None


if __name__ == "__main__":
    _setup_viewport()
    bpy.app.timers.register(_setup_viewport, first_interval=0.5)
    bpy.app.timers.register(_delayed_start, first_interval=1.5)
