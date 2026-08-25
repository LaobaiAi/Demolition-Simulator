import ctypes
import subprocess
import sys

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def main():
    if len(sys.argv) < 2:
        print("usage: python scripts/run_with_wake.py <command> [args...]")
        return 2
    ctypes.windll.kernel32.SetThreadExecutionState(ES_SYSTEM_REQUIRED | ES_CONTINUOUS)
    try:
        return subprocess.call(sys.argv[1:])
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)


if __name__ == "__main__":
    sys.exit(main())
