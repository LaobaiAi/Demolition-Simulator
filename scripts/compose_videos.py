"""Host-side video composition: PNG frame sequences -> MP4 via imageio-ffmpeg.

Run with the gateway venv python (imageio-ffmpeg bundles a static ffmpeg).
"""

import glob
import os
import subprocess

FFMPEG = r"D:\GitHub Dev\Demolition-Simulator\gateway\venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
ROOT = r"D:\GitHub Dev\Demolition-Simulator\frontend\public\resource\Abaqus"
SIDE_DIR = os.path.join(ROOT, "frames", "side")
TOP_DIR = os.path.join(ROOT, "frames", "top")
DURATION_S = 8.5
DUP = 3


def compose(src, out):
    n = len(glob.glob(os.path.join(src, "f_*.png")))
    if n == 0:
        raise RuntimeError("no frames in " + src)
    in_fps = round(n / DURATION_S, 3)
    out_fps = round(in_fps * DUP, 3)
    cmd = [FFMPEG, "-y", "-framerate", str(in_fps),
           "-i", os.path.join(src, "f_%03d.png"),
           "-vf", "fps=%s,scale=1280:720" % out_fps,
           "-c:v", "libx264", "-preset", "medium", "-crf", "19",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-3000:])
    return n, in_fps, out_fps, os.path.getsize(out)


def main():
    n_side, in_fps, out_fps, sz_side = compose(SIDE_DIR, os.path.join(ROOT, "cooling_tower_collapse.mp4"))
    print("side: %d frames in@%.3f out@%.3f fps -> %d bytes" % (n_side, in_fps, out_fps, sz_side), flush=True)
    n_top, in_fps, out_fps, sz_top = compose(TOP_DIR, os.path.join(ROOT, "cooling_tower_collapse_top.mp4"))
    print("top: %d frames in@%.3f out@%.3f fps -> %d bytes" % (n_top, in_fps, out_fps, sz_top), flush=True)


main()
