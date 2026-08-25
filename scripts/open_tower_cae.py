# -*- coding: utf-8 -*-
# Open cooling tower run 15 ODB in Abaqus/CAE GUI (readOnly), deformed view at last frame.
# Run via: abq2026.bat cae script=scripts/open_tower_cae.py
import sys
import os

ODB_PATH = r"D:\GitHub Dev\Demolition-Simulator\abaqus_projects\cooling_tower_fine\results\tower_job_run.odb"
LOG_PATH = r"D:\GitHub Dev\Demolition-Simulator\scripts\open_tower_cae_gui.log"


def log(msg):
    with open(LOG_PATH, "a") as f:
        f.write(msg + "\n")


def open_and_show():
    from abaqus import session
    import visualization
    vp = session.viewports['Viewport: 1']
    log("opening odb readOnly: " + ODB_PATH)
    odb = session.openOdb(ODB_PATH, readOnly=True)
    vp.setValues(displayedObject=odb)
    log("displayedObject set")
    return vp, odb


def main():
    try:
        vp, odb = open_and_show()
        from abaqusConstants import DEFORMED
        vp.odbDisplay.display.setValues(plotState=(DEFORMED,))
        last_step = odb.steps.keys()[-1]
        frame_idx = len(odb.steps[last_step].frames) - 1
        vp.odbDisplay.setFrame(step=last_step, frame=frame_idx)
        vp.view.fitView()
        log("ok: deformed shown, step=%s frame=%d" % (last_step, frame_idx))
    except Exception as e:
        log("error: %r" % (e,))
        try:
            vp, odb = open_and_show()
            log("fallback ok: ODB opened and displayed")
        except Exception as e2:
            log("fallback failed: %r" % (e2,))


if __name__ == "__main__":
    log("=== open_tower_cae start ===")
    try:
        main()
    except Exception as e:
        log("fatal: %r" % (e,))
    log("script finished")
