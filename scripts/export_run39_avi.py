"""Export run39 collapse animation as AVI, stopping at the pre-contact frame.

Runs in a CAE GUI session (writeAVI needs a display):
    abq2026.bat cae script=scripts/export_run39_avi.py
Frames 0..50 (t=0.00-7.50s) are exported; the ground-contact frame 51 is
excluded so the video ends with the tower still intact.
"""
from abaqusConstants import DEFORMED, NODAL, INVARIANT, NONE
from odbAccess import openOdb

ODB_PATH = r"D:\GitHub Dev\Demolition-Simulator\abaqus_projects\concrete_stack_run39\results\stack_job_run.odb"
AVI_PATH = r"D:\GitHub Dev\Demolition-Simulator\abaqus_projects\concrete_stack_run39\run39_precontact.avi"
LAST_FRAME = 50  # t=7.50s, tip 3.7m above ground, tower intact


def main():
    try:
        odb = openOdb(ODB_PATH, readOnly=True)
    except Exception as e:
        print("export: FATAL openOdb failed: %s" % e)
        return
    vp = None
    for v in session.viewports.values():
        vp = v
        break
    if vp is None:
        print("export: no viewport")
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
        vp.animationController.setValues(
            frameSequence=tuple(range(LAST_FRAME + 1))
        )
        session.writeAVI(
            fileName=AVI_PATH, compression="none", quality=100
        )
        print("export: AVI written to %s (frames 0..%d)" % (AVI_PATH, LAST_FRAME))
    except Exception as e:
        print("export: FAILED: %s" % e)
    finally:
        try:
            odb.close()
        except Exception:
            pass


main()
