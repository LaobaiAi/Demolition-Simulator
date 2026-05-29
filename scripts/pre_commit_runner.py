"""
XuanwuAI Pre-commit Smart Runner

Detects which files are staged and runs only the relevant CI checks:
  - Python changes → pytest (gateway + caiao_servers)
  - TypeScript/TSX changes → tsc + ESLint + Vitest

Mirrors the checks in .github/workflows/ci.yml.
"""
import subprocess
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GIT = ["git"]

# ── Colour helpers ────────────────────────────────────────────────
def green(s):  return f"\033[32m{s}\033[0m"
def red(s):    return f"\033[31m{s}\033[0m"
def yellow(s): return f"\033[33m{s}\033[0m"
def bold(s):   return f"\033[1m{s}\033[0m"


def run(cmd: list[str], cwd=None, env=None) -> tuple[int, str]:
    """Run a command, return (exit_code, combined_output)."""
    try:
        r = subprocess.run(
            cmd, cwd=cwd, env=env or os.environ.copy(),
            capture_output=True, text=True, timeout=300,
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 1, "TIMEOUT after 300s"
    except FileNotFoundError:
        return 1, f"Command not found: {cmd[0]}"


def get_staged_files() -> list[str]:
    """Return list of staged file paths (relative to repo root)."""
    code, out = run(GIT + ["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    if code != 0:
        print(red("[FAIL] Could not list staged files."))
        sys.exit(1)
    return [f.strip() for f in out.split("\n") if f.strip()]


def get_venv_python() -> str:
    """Find the venv Python."""
    candidates = [
        ROOT / "gateway" / "venv" / "Scripts" / "python.exe",
        ROOT / "gateway" / "venv" / "bin" / "python",
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "python"


# ── Backend Check ─────────────────────────────────────────────────
def check_backend(files: list[str]) -> int:
    """Run pytest on gateway and relevant caiao_servers."""
    python_files = [f for f in files if f.endswith(".py")]
    if not python_files:
        print(green("[SKIP] No Python changes."))
        return 0

    gateway_changed = any(f.startswith("gateway/") for f in python_files)
    caiao_changed  = any(f.startswith("caiao_servers/") for f in python_files)

    if not gateway_changed and not caiao_changed:
        print(green("[SKIP] Python changes outside gateway/caiao_servers."))
        return 0

    python = get_venv_python()
    failed = 0

    # ── Gateway tests ──
    if gateway_changed:
        print(bold("\n--- Backend: gateway tests (pytest) ---"))
        gt = ROOT / "gateway" / "tests"
        code, out = run([python, "-m", "pytest", str(gt), "-v", "--tb=short"], cwd=str(ROOT / "gateway"))
        print(out)
        if code != 0:
            print(red(f"\n[FAIL] gateway pytest ({code})"))
            failed += 1
        else:
            print(green("\n[PASS] gateway pytest"))

    # ── CAIAO server tests ──
    if caiao_changed:
        caiao_dirs = [
            d for d in (ROOT / "caiao_servers").iterdir()
            if d.is_dir() and (d / "tests").is_dir()
        ]
        for cd in caiao_dirs:
            server_name = cd.name
            # Only test caiao servers whose files changed
            if not any(f.startswith(f"caiao_servers/{server_name}/") for f in python_files):
                continue
            print(bold(f"\n--- Backend: {server_name} tests (pytest) ---"))
            code, out = run([python, "-m", "pytest", str(cd / "tests"), "-v", "--tb=short"])
            print(out)
            if code != 0:
                print(red(f"\n[FAIL] {server_name} pytest ({code})"))
                failed += 1
            else:
                print(green(f"\n[PASS] {server_name} pytest"))

    return failed


# ── Frontend Check ─────────────────────────────────────────────────
def check_frontend(files: list[str]) -> int:
    """Run TypeScript type-check, ESLint, and Vitest."""
    frontend_files = [
        f for f in files
        if f.startswith("frontend/") and (
            f.endswith(".ts") or f.endswith(".tsx") or
            f.endswith(".js") or f.endswith(".jsx")
        )
    ]
    if not frontend_files:
        print(green("[SKIP] No frontend source changes."))
        return 0

    cwd = str(ROOT / "frontend")
    failed = 0
    # Detect npm (on Windows, prefer npm.cmd)
    npm = "npm.cmd" if os.name == "nt" else "npm"

    # ── TypeScript type-check ──
    print(bold("\n--- Frontend: type-check (tsc --noEmit) ---"))
    code, out = run(
        ["npx.cmd" if os.name == "nt" else "npx", "tsc", "--noEmit"],
        cwd=cwd,
    )
    if out:
        print(out)
    if code != 0:
        print(red(f"\n[FAIL] TypeScript type-check ({code})"))
        failed += 1
    else:
        print(green("\n[PASS] TypeScript type-check"))

    # ── ESLint ──
    print(bold("\n--- Frontend: lint (eslint) ---"))
    code, out = run([npm, "run", "lint"], cwd=cwd)
    if out:
        print(out)
    if code != 0:
        print(red(f"\n[FAIL] ESLint ({code})"))
        failed += 1
    else:
        print(green("\n[PASS] ESLint"))

    # ── Vitest ──
    print(bold("\n--- Frontend: tests (vitest) ---"))
    code, out = run([npm, "test"], cwd=cwd)
    if out:
        print(out)
    if code != 0:
        print(red(f"\n[FAIL] Vitest ({code})"))
        failed += 1
    else:
        print(green("\n[PASS] Vitest"))

    return failed


# ── Main ───────────────────────────────────────────────────────────
def main() -> int:
    files = get_staged_files()
    if not files:
        print(yellow("No staged files to check."))
        return 0

    print(f"Staged files: {len(files)}")
    failures = 0

    failures += check_backend(files)
    failures += check_frontend(files)

    print("")
    print("=" * 44)
    if failures == 0:
        print(green(bold(" ALL CHECKS PASSED ")))
        return 0
    else:
        print(red(bold(f" {failures} CHECK(S) FAILED — commit blocked ")))
        print(yellow("Fix the issues above and try again."))
        print(yellow("To bypass (NOT recommended):  git commit --no-verify"))
        return 1


if __name__ == "__main__":
    sys.exit(main())
