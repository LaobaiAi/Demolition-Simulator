"""Task 4 verification: probe MP4 metadata (duration, resolution, fps, size)."""

import os
import re
import subprocess
import sys

sys.path.insert(0, r"D:\GitHub Dev\Demolition-Simulator\gateway\venv\Lib\site-packages")
import imageio_ffmpeg

RESOURCE_DIR = r"D:\GitHub Dev\Demolition-Simulator\frontend\public\resource\Abaqus"
FILES = ["cooling_tower_collapse.mp4", "cooling_tower_collapse_top.mp4"]

ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
for name in FILES:
    path = os.path.join(RESOURCE_DIR, name)
    if not os.path.exists(path):
        print("%s: MISSING" % name, flush=True)
        continue
    proc = subprocess.run([ffmpeg, "-i", path], capture_output=True, text=True)
    info = proc.stderr
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info)
    v = re.search(r"Video: (\S+).*?(\d{2,5})x(\d{2,5}).*?([\d.]+) fps", info)
    duration = None
    if dur:
        h, m, s = map(float, dur.groups())
        duration = h * 3600 + m * 60 + s
    size = os.path.getsize(path)
    if v:
        print("%s: %.2fs %s %sx%s @%sfps size=%d" % (
            name, duration or -1.0, v.group(1), v.group(2), v.group(3),
            v.group(4), size), flush=True)
    else:
        print("%s: %.2fs size=%d info=%s" % (name, duration or -1.0, size,
                                             info[:400]), flush=True)
