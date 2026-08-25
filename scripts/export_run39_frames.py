"""Export run39 collapse animation as PNG frames 0..50 (pre-contact only).

writeAVI hangs in this Abaqus 2026 setup, so export per-frame PNGs instead;
the host then composes an MP4 with imageio (see export_run39_mp4.py).
Runs in a CAE GUI session:
    abq2026.bat cae script=scripts/export_run39_frames.py
Frame 51 (ground contact) is excluded so the video ends with the tower intact.
"""
from abaqusConstants import DEFORMED, NODAL, INVARIANT, NONE, PNG
from odbAccess import openOdb
import os

ODB_PATH = r"D:\GitHub Dev\Demolition-Simulator\abaqus_projects\concrete_stack_run39\results\stack_job_run.odb"
OUT_DIR = r"D:\GitHub Dev\Demolition-Simulator\abaqus_projects\concrete_stack_run39\frames_precontact"
LOG = r"D:\GitHub Dev\Demolition-Simulator\abaqus_projects\concrete_stack_run39\export_log.txt"
LAST_FRAME = 50  # t=7.50s, tip 3.7m above ground, tower intact


def log(msg):
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def main():
    log("start")
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        odb = openOdb(ODB_PATH, readOnly=True)
        log("odb opened")
    except Exception as e:
        log("FATAL open: %s" % e)
        return
    vp = None
    for v in session.viewports.values():
        vp = v
        break
    if vp is None:
        log("FATAL no viewport")
        return
    try:
        vp.setValues(displayedObject=odb)
        vp.odbDisplay.setPrimaryVariable(
            variableLabel="U",
            outputPosition=NODAL,
            refinement=(INVARIANT, "Magnitude"),
        )
        vp.odbDisplay.display.setValues(plotState=(DEFORMED,))
        vp.view.setValues(session.views["Front"])
        vp.view.fitView()
        vp.setValues(width=1280, height=720)
        vp.animationController.setValues(animationType=NONE)
        log("viewport configured")
        step_name = list(odb.steps.keys())[-1]
        for f in range(LAST_FRAME + 1):
            vp.odbDisplay.setFrame(step=step_name, frame=f)
            fp = os.path.join(OUT_DIR, "frame_%03d.png" % f)
            session.printToFile(
                fileName=fp, format=PNG, canvasObjects=(vp,)
            )
            if f % 10 == 0:
                log("saved %s" % fp)
        log("done frames 0..%d" % LAST_FRAME)
    except Exception as e:
        log("FAILED: %s" % e)
    finally:
        try:
            odb.close()
        except Exception:
            pass


main()
