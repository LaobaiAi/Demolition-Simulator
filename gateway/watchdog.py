"""Gateway watchdog — monitors and auto-restarts the gateway if it crashes."""
import subprocess
import time
import sys
import os
import urllib.request
import urllib.error

GATEWAY_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(GATEWAY_DIR, "venv", "Scripts", "python.exe")
MAIN = os.path.join(GATEWAY_DIR, "main.py")
HEALTH_URL = "http://localhost:8000/health"
CHECK_INTERVAL = 15


def is_alive() -> bool:
    try:
        urllib.request.urlopen(HEALTH_URL, timeout=5)
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def main():
    print("[watchdog] Starting gateway watchdog...")
    process = None
    while True:
        if process is not None:
            ret = process.poll()
            if ret is not None:
                print(f"[watchdog] Gateway exited with code {ret}, restarting...")
                process = None

        if process is None:
            print("[watchdog] Launching gateway...")
            process = subprocess.Popen(
                [PYTHON, MAIN],
                cwd=GATEWAY_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Wait briefly then check health
            time.sleep(5)
            if not is_alive():
                print("[watchdog] Gateway not responding after launch, killing and retrying...")
                process.kill()
                process = None
                time.sleep(2)
                continue
            print("[watchdog] Gateway is healthy.")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[watchdog] Shutting down.")
        if process := locals().get("process"):
            process.terminate()
