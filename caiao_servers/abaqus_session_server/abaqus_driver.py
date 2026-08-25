"""Abaqus Kernel Driver — runs INSIDE the Abaqus CAE noGUI kernel as a persistent session.

This script is launched by server.py via:
    abq2026.bat cae noGUI=abaqus_driver.py

It keeps the Abaqus kernel process alive (so the shared model database `mdb` persists
across tool calls) and executes tools by polling task files written by server.py:

    <workdir>/task_<id>.json   -> request   {"id","tool","arguments"}
    <workdir>/result_<id>.json -> response  {"id","success","result"} | {"id","error",...}
    <workdir>/exit.flag        -> when present, driver shuts down gracefully

Communication directory comes from env var ABAQUS_DRIVER_WORKDIR (set by server.py).
"""

import glob
import json
import os
import sys
import time
import traceback

# Make sibling abaqus_session.py importable no matter the kernel's cwd / sys.path.
# NOTE: Abaqus noGUI runs this script via exec(), so `__file__` is NOT defined;
# server.py always sets ABAQUS_DRIVER_SERVERDIR, which is used first.
_SERVER_DIR = os.environ.get("ABAQUS_DRIVER_SERVERDIR")
if not _SERVER_DIR:
    try:
        _SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        _SERVER_DIR = os.getcwd()
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

# This import must happen inside the Abaqus kernel process — which is exactly where
# this script runs. It reuses all 15 tool handlers (HANDLERS) unchanged.
from abaqus import mdb  # noqa: E402
from abaqusConstants import *  # noqa: E402,F401,F403
from abaqus_session import HANDLERS  # noqa: E402

_WORKDIR = os.environ.get("ABAQUS_DRIVER_WORKDIR") or os.getcwd()
_EXIT_FLAG = os.path.join(_WORKDIR, "exit.flag")
_READY_FLAG = os.path.join(_WORKDIR, "ready.flag")
_POLL_INTERVAL = 0.5  # seconds


def _log(msg):
    """Write to a file instead of stdout: under noGUI the kernel stdout may be
    buffered or swallowed, but a file is immediately visible to server.py."""
    try:
        with open(os.path.join(_WORKDIR, "driver.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def _process_task(task_path):
    """Execute one request file and write its result file."""
    req_id = os.path.basename(task_path).replace("task_", "").replace(".json", "")
    result_path = os.path.join(_WORKDIR, "result_{}.json".format(req_id))

    try:
        with open(task_path, "r", encoding="utf-8") as f:
            request = json.load(f)

        tool_name = request.get("tool", "")
        arguments = request.get("arguments", {}) or {}
        handler = HANDLERS.get(tool_name)

        if handler is None:
            response = {"id": req_id, "error": "Unknown tool: {}".format(tool_name)}
        else:
            try:
                result = handler(arguments)
                response = {"id": req_id, "success": True, "result": result}
            except Exception as exc:  # keep the kernel alive after a tool error
                response = {
                    "id": req_id,
                    "success": False,
                    "error": "{}: {}".format(tool_name, exc),
                    "traceback": traceback.format_exc(),
                }

        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(response, f, ensure_ascii=False, indent=2)
        _log("done: {} ({})".format(req_id, tool_name))
    finally:
        try:
            os.remove(task_path)
        except OSError:
            pass


def main():
    os.makedirs(_WORKDIR, exist_ok=True)
    # Signal readiness ONLY after all imports succeeded and we are about to enter
    # the task loop — this is the "kernel actually works" proof server.py waits for.
    with open(_READY_FLAG, "w", encoding="utf-8") as f:
        f.write("ready")
    _log("driver started, polling " + _WORKDIR)
    while True:
        if os.path.exists(_EXIT_FLAG):
            break
        tasks = sorted(glob.glob(os.path.join(_WORKDIR, "task_*.json")))
        for task_path in tasks:
            _process_task(task_path)
        time.sleep(_POLL_INTERVAL)


main()
