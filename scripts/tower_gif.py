"""Lightweight collapse GIF from an extract_tower_frames npz (tower shell only).

Reads X (Nx3), conn (Ex4, -1 padded), t (F), U (FxNx3) from the npz; deformed
position = X + U[f]. Data is Y-up; render mapping [x, -z, y] keeps the tower
vertical (same convention as render_tower_frames.py). One fixed color scale
across all frames (nodal displacement magnitude, viridis quantized to 7
levels + white background = 8-entry palette). Side view elev=8 azim=-25, no
ground/axes/text. Frames are uniformly sampled across the timeline and
cropped to the union of content so the tower fills the frame.

GIF is written by a minimal GIF89a encoder with a fixed global color table
(Pillow's GIF writer remaps palettes, so it is not used for saving).

Usage:
  python tower_gif.py [npz_path] [--out PATH] [--width 480] [--nframes 6]
                      [--dur 1000] [--umax AUTO]
"""

import argparse
import os
import struct

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

DEFAULT_NPZ = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "abaqus_projects", "cooling_tower_r18_rerun", "_tower_frames", "data.npz")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tower_gifs")
ELEV, AZIM = 8.0, -25.0
N_LEVELS = 7  # colormap levels; entry N_LEVELS = white background (8 entries total)
BG_INDEX = N_LEVELS


def load(npz):
    d = np.load(npz)
    return d["X"], d["conn"], d["t"], d["U"]


def render_limits(X, U):
    P = (X[None, :, :] + U)[:, :, [0, 2, 1]]
    P[:, :, 1] *= -1.0
    lo = P.reshape(-1, 3).min(axis=0)
    hi = P.reshape(-1, 3).max(axis=0)
    m = 0.04 * (hi - lo).max()
    return lo - m, hi + m


def build_palette(umax):
    cmap = plt.get_cmap("viridis")
    lev = (cmap(np.linspace(0.0, 1.0, N_LEVELS))[:, :3] * 255.0).round().astype(np.uint8)
    palette = np.vstack([lev, [[255, 255, 255]]]).astype(np.uint8)
    face_rgb = np.hstack([lev / 255.0, np.ones((N_LEVELS, 1))]).astype(np.float32)
    return palette, face_rgb


def render_frame(f, X, conn, U, lim, umax, face_rgb, canvas):
    lo, hi = lim
    P = X + U[f]
    P = P[:, [0, 2, 1]]
    P[:, 1] *= -1.0
    umag = np.sqrt((U[f] ** 2).sum(axis=1))
    mask = conn >= 0
    fm = ((umag[conn] * mask).sum(axis=1) / mask.sum(axis=1)).ravel()
    q = np.clip(np.floor(fm / umax * N_LEVELS).astype(np.int32), 0, N_LEVELS - 1)
    fc = face_rgb[q]
    faces = [P[row[row >= 0]] for row in conn]

    canvas.clear()
    ax = canvas.add_subplot(111, projection="3d")
    ax.set_proj_type("ortho")
    ax.view_init(ELEV, AZIM)
    ax.add_collection3d(Poly3DCollection(faces, facecolors=fc,
                                         edgecolors="none", zorder=2))
    ax.add_collection3d(Poly3DCollection(faces, facecolors="none",
                                         edgecolors=(0.0, 0.0, 0.0, 0.35),
                                         linewidths=0.3, zorder=3))
    ax.set_xlim(lo[0], hi[0])
    ax.set_ylim(lo[1], hi[1])
    ax.set_zlim(lo[2], hi[2])
    ax.set_box_aspect(tuple(hi - lo))
    ax.set_axis_off()
    canvas.subplots_adjust(left=0.0, right=1.0, top=1.0, bottom=0.0)
    canvas.canvas.draw()
    return np.asarray(canvas.canvas.buffer_rgba())[:, :, :3].astype(np.int16)


def quantize(img, palette):
    dist = ((img[:, :, None, :] - palette[None, None, :, :]) ** 2).sum(axis=-1)
    return dist.argmin(axis=-1).astype(np.uint8)


def lzw_encode(indices, min_code_size=3):
    """GIF LZW compression over the flat pixel stream (early-change code sizes)."""
    clear = 1 << min_code_size
    end = clear + 1
    code_size = min_code_size + 1
    next_code = end + 1
    table = {bytes((i,)): i for i in range(clear)}
    out = bytearray()
    bitbuf = 0
    nbits = 0

    def emit(code):
        nonlocal bitbuf, nbits
        bitbuf |= code << nbits
        nbits += code_size
        while nbits >= 8:
            out.append(bitbuf & 0xFF)
            bitbuf >>= 8
            nbits -= 8

    emit(clear)
    s = bytes((indices[0],))
    for b in indices[1:]:
        c = bytes((b,))
        if s + c in table:
            s = s + c
        else:
            emit(table[s])
            if next_code < 4096:
                table[s + c] = next_code
                next_code += 1
                # encoder's table runs one entry ahead of the decoder's
                # (decoder cannot add for its first code after clear), so the
                # encoder must grow the code size one code late to stay in sync
                if next_code == (1 << code_size) + 1 and code_size < 12:
                    code_size += 1
            s = c
    emit(table[s])
    emit(end)
    if nbits > 0:
        out.append(bitbuf & 0xFF)
    return bytes(out)


def write_gif(path, frames, palette, duration_ms):
    h, w = frames[0].shape
    out = bytearray()
    out += b"GIF89a"
    out += struct.pack("<HH", w, h)
    out += bytes([0x80 | (3 << 4) | (len(palette).bit_length() - 2)])  # GCT present, 2^(n+1) entries
    out += bytes([BG_INDEX, 0])
    out += palette.tobytes()
    for idx in frames:
        # Graphic Control Extension: disposal 2, delay, no transparency
        out += b"\x21\xF9\x04"
        out += bytes([0x08])
        out += struct.pack("<H", duration_ms)
        out += b"\x00\x00"
        # Image descriptor: full canvas, no local table
        out += b"\x2C"
        out += struct.pack("<HHHH", 0, 0, w, h)
        out += b"\x00"
        comp = lzw_encode(idx.ravel())
        out += bytes([3])  # LZW minimum code size (8 colors)
        for i in range(0, len(comp), 255):
            chunk = comp[i:i + 255]
            out += bytes([len(chunk)]) + chunk
        out += b"\x00"
    out += b"\x3B"
    with open(path, "wb") as fh:
        fh.write(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("npz", nargs="?", default=DEFAULT_NPZ)
    ap.add_argument("--out")
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--step", type=int, default=0,
                    help="take every Nth frame (mutually exclusive with --nframes)")
    ap.add_argument("--nframes", type=int, default=6,
                    help="uniformly sampled frame count across the whole timeline")
    ap.add_argument("--dur", type=int, default=1000)
    ap.add_argument("--umax", type=float, default=0.0,
                    help="fixed color-scale max in meters (0 = auto from data)")
    args = ap.parse_args()

    X, conn, t, U = load(args.npz)
    umax = args.umax or float(np.sqrt((U ** 2).sum(axis=-1)).max())
    umax = float(np.ceil(umax))
    palette, face_rgb = build_palette(umax)
    lim = render_limits(X, U)

    fig = plt.figure(figsize=(args.width / 100.0, args.width / 100.0), dpi=100)
    if args.step and args.step > 1:
        idxs = list(range(0, U.shape[0], args.step))
    else:
        idxs = np.linspace(0, U.shape[0] - 1, args.nframes).round().astype(int).tolist()
    frames = []
    bbox = None
    for f in idxs:
        rgba = render_frame(f, X, conn, U, lim, umax, face_rgb, fig)
        idx = quantize(rgba, palette)
        mask = idx != BG_INDEX
        if mask.any():
            ys, xs = np.nonzero(mask)
            b = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
            bbox = b if bbox is None else (
                min(bbox[0], b[0]), min(bbox[1], b[1]),
                max(bbox[2], b[2]), max(bbox[3], b[3]))
        frames.append(idx)
        print("frame %d/%d (t=%.2fs) done" % (f + 1, U.shape[0], float(t[f])), flush=True)

    if bbox is not None:
        frames = [fr[bbox[1]:bbox[3], bbox[0]:bbox[2]] for fr in frames]

    os.makedirs(OUT_DIR, exist_ok=True)
    out = args.out or os.path.join(OUT_DIR, "tower_r18b.gif")
    write_gif(out, frames, palette, args.dur)
    print("saved %s frames=%d size=%dKB dur=%dms umax=%.0fm bbox=%s" % (
        out, len(frames), os.path.getsize(out) // 1024, args.dur, umax, bbox), flush=True)


if __name__ == "__main__":
    main()
