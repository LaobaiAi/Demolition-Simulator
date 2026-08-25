"""Abaqus CAE GUI startup script: open the run17 chimney-collapse ODB and show
the deformed last frame from a side view, for interactive inspection.

Runs inside a CAE GUI session (no noGUI flag):
    abq2026.bat cae script=scripts/open_stack_run17_cae.py
The GUI stays open after the script finishes; the user can rotate/inspect freely.

Every stage is guarded: on any failure the ODB is still opened and displayed so
the user can operate the GUI manually.
"""

from abaqusConstants import DEFORMED, NODAL, INVARIANT, NONE
from odbAccess import openOdb

ODB_PATH = r"D:\GitHub Dev\Demolition-Simulator\abaqus_projects\concrete_stack_run17\results\stack_job_run.odb"


def _get_viewport():
    vps = session.viewports
    if "Viewport: 1" in vps:
        return vps["Viewport: 1"]
    names = [n for n in vps.keys()]
    if names:
        return vps[names[0]]
    return None


def _stop_animation(vp):
    try:
        vp.animationController.setValues(animationType=NONE)
    except Exception as e:
        try:
            vp.animationController.stop()
        except Exception as e2:
            print("open_stack_cae: animation stop skipped: %s / %s" % (e, e2))


def _jump_last_frame(vp, step_names, step):
    last_idx = len(step.frames) - 1
    for attempt in ("index", "name"):
        try:
            if attempt == "index":
                vp.odbDisplay.setFrame(
                    step=len(step_names) - 1, frame=last_idx
                )
            else:
                vp.odbDisplay.setFrame(step=step.name, frame=last_idx)
            print(
                "open_stack_cae: last frame %d of step %s (via %s)"
                % (last_idx, step.name, attempt)
            )
            return
        except Exception as e:
            print(
                "open_stack_cae: setFrame via %s failed: %s" % (attempt, e)
            )


def _show(odb, vp):
    step_names = list(odb.steps.keys())
    print("open_stack_cae: steps = %s" % step_names)
    step = odb.steps[step_names[-1]]
    try:
        vp.setValues(displayedObject=odb)
    except Exception as e:
        print("open_stack_cae: setValues(displayedObject) failed: %s" % e)
    try:
        vp.odbDisplay.setPrimaryVariable(
            variableLabel="U",
            outputPosition=NODAL,
            refinement=(INVARIANT, "Magnitude"),
        )
    except Exception as e:
        print("open_stack_cae: setPrimaryVariable failed: %s" % e)
    try:
        vp.odbDisplay.display.setValues(plotState=(DEFORMED,))
    except Exception as e:
        print("open_stack_cae: plotState DEFORMED failed: %s" % e)
    try:
        vp.view.setValues(session.views["Front"])
    except Exception as e:
        print("open_stack_cae: Front view failed (keeping default): %s" % e)
    try:
        vp.view.fitView()
    except Exception as e:
        print("open_stack_cae: view.fitView failed: %s" % e)
    _jump_last_frame(vp, step_names, step)
    _stop_animation(vp)
    _jump_last_frame(vp, step_names, step)


def main():
    odb = None
    try:
        odb = openOdb(ODB_PATH, readOnly=True)
        print("open_stack_cae: opened %s" % ODB_PATH)
    except Exception as e:
        print("open_stack_cae: FATAL openOdb failed: %s" % e)
        return
    try:
        vp = _get_viewport()
        if vp is None:
            print("open_stack_cae: no viewport available; ODB open in session")
        else:
            _show(odb, vp)
    except Exception as e:
        print("open_stack_cae: viewport stage failed: %s" % e)
    print("open_stack_cae: done - ODB open in GUI, ready for manual inspection")


main()
