"""Kernel noGUI: analyze the instance-library run-10 (70m) ODB with its geometry.

Imports analyze_tower_odb and overrides the 90m constants with the run-10 (v3)
70m values, then runs the same per-frame analysis so the instance's per-band
deletion pattern can be compared with the 90m rounds.

Run: abq2026.bat cae noGUI=analyze_instance_odb.py
"""

import os
import sys

sys.path.insert(0, r"D:\GitHub Dev\Demolition-Simulator\scripts")

import analyze_tower_odb as A

A.ODB_PATH = r"C:\Users\99005\AppData\Local\Temp\tower_collapse_4shdyzvy\tower_job_run.odb"
A.OUT_PATH = (r"D:\GitHub Dev\Demolition-Simulator\abaqus_projects"
              r"\cooling_tower_90m\instance_run10_analyze.json")
A.HEIGHT = 70.0
A.BASE_RADIUS = 28.5
A.TOP_RING_Y0 = 68.5
A.N_THETA = 128
A.N_NODES = A.N_STATIONS * A.N_THETA
A.BANDS = [("RootBottom", 0.0, 5.0),
           ("RootUpper", 5.0, 10.0),
           ("Opening", 10.0, 22.0),
           ("Mid", 22.0, A.TOP_RING_Y0),
           ("TopRing", A.TOP_RING_Y0, A.HEIGHT)]

if __name__ == "__main__":
    raise SystemExit(A.main())
