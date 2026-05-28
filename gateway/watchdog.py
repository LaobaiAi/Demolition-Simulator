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
STARTUP_TIMEOUT = 30
LOG_FILE = os.path.join(GATEWAY_DIR, "gateway_stderr.log")


def is_alive() -> bool:
    try:
        urllib.request.urlopen(HEALTH_URL, timeout=5)
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def _open_log():
    fh = open(LOG_FILE, "a", encoding="utf-8")
    print(f"\n--- Gateway launched at {time.strftime('%Y-%m-%d %H:%M:%S')} ---", file=fh)
    fh.flush()
    return fh


def main():
    print("[watchdog] Starting gateway watchdog...")
    process = None
    log_fh = None
    while True:
        if process is not None:
            ret = process.poll()
            if ret is not None:
                print(f"[watchdog] Gateway exited with code {ret}, restarting...")
                process = None
                if log_fh:
                    log_fh.close()
                    log_fh = None

        if process is None:
            print("[watchdog] Launching gateway...")
            log_fh = _open_log()
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            process = subprocess.Popen(
                [PYTHON, MAIN],
                cwd=GATEWAY_DIR,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                env=env,
            )

            # Progressive health check (every 2s, up to STARTUP_TIMEOUT)
            print("[watchdog] Waiting for gateway to start...")
            started = False
            for i in range(STARTUP_TIMEOUT // 2):
                time.sleep(2)
                if process.poll() is not None:
                    print(f"[watchdog] Gateway exited prematurely during startup, restarting...")
                    process = None
                    break
                if is_alive():
                    started = True
                    print(f"[watchdog] Gateway is healthy (after ~{((i + 1) * 2)}s).")
                    break
                if (i + 1) % 5 == 0:
                    print(f"[watchdog] Still waiting... ({((i + 1) * 2)}s elapsed)")

            if process is None:
                # Process exited during startup
                if log_fh:
                    log_fh.close()
                    log_fh = None
                time.sleep(2)
                continue

            if not started:
                print(f"[watchdog] Gateway not responding after {STARTUP_TIMEOUT}s, killing and retrying...")
                process.kill()
                process = None
                if log_fh:
                    log_fh.close()
                    log_fh = None
                time.sleep(2)
                continue

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[watchdog] Shutting down.")
