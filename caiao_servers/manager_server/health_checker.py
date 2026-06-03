"""CAIAO health checker — runtime health pings, restart policy evaluation.

The health checker queries the gateway's REST endpoints for runtime state.
It does NOT directly access subprocess handles — that's the hub's job.
The checker is the analysis layer; the hub is the execution layer.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def evaluate_health(hub_state: dict[str, Any], manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate a single server's health from its hub state and manifest.

    Args:
        hub_state: The server's state dict from the hub.
        manifest: The server's caiao.yaml manifest (optional).

    Returns a health report dict.
    """
    state = hub_state.get("state", "unknown")
    pid = hub_state.get("pid")
    started_at = hub_state.get("started_at")
    crash_count = hub_state.get("crash_count", 0)
    last_error = hub_state.get("last_error")

    report = {
        "state": state,
        "healthy": state in ("running", "hibernating"),
        "pid": pid,
    }

    if started_at:
        uptime_s = int(time.time() - started_at)
        report["uptime_seconds"] = uptime_s
        report["uptime_display"] = _format_uptime(uptime_s)

    if crash_count > 0:
        report["crash_count"] = crash_count
        report["healthy"] = False
        if last_error:
            report["last_error"] = str(last_error)[:500]

    if manifest:
        health_config = manifest.get("health", {})
        timeout_ms = health_config.get("timeout_ms", 5000)
        max_restarts = health_config.get("max_restarts", 3)
        report["timeout_ms"] = timeout_ms
        report["max_restarts"] = max_restarts

        if crash_count >= max_restarts:
            report["healthy"] = False
            report["restart_policy"] = "exhausted"

    if state == "crashed":
        report["healthy"] = False
        report.setdefault("recommendation", "Manual intervention required — max restarts may be exceeded")
    elif state == "degraded":
        report["healthy"] = False
        report.setdefault("recommendation", "Server is running but some tools are failing")
    elif state == "stopped":
        report["healthy"] = False
        report.setdefault("recommendation", "Server was manually stopped")
    elif state == "hibernating":
        report.setdefault("recommendation", "Server will start on first tool call")

    return report


def evaluate_all_health(
    hub_health: dict[str, Any],
    manifests: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate health for all servers.

    Args:
        hub_health: Full health dict from gateway (server_name -> state).
        manifests: Dict of server_name -> manifest data.

    Returns a summary report.
    """
    reports = {}
    healthy_count = 0
    unhealthy_count = 0

    for server_name, state in hub_health.items():
        manifest = manifests.get(server_name)
        report = evaluate_health(state, manifest)
        reports[server_name] = report
        if report["healthy"]:
            healthy_count += 1
        else:
            unhealthy_count += 1

    return {
        "servers": reports,
        "total": len(reports),
        "healthy": healthy_count,
        "unhealthy": unhealthy_count,
        "healthy_ratio": round(healthy_count / max(len(reports), 1), 2),
    }


def evaluate_restart_policy(state: dict, manifest: dict | None = None) -> str:
    """Determine what action to take for a server based on its state and policy.

    Returns one of: 'noop', 'restart', 'stop', 'alert'.
    """
    current_state = state.get("state", "unknown")
    crash_count = state.get("crash_count", 0)

    if current_state in ("running", "hibernating", "starting"):
        return "noop"

    if current_state == "stopped":
        return "noop"

    if current_state == "crashed":
        max_restarts = 3
        if manifest:
            max_restarts = manifest.get("health", {}).get("max_restarts", 3)
        if crash_count < max_restarts:
            return "restart"
        return "alert"

    if current_state == "degraded":
        restart_on_crash = True
        if manifest:
            restart_on_crash = manifest.get("health", {}).get("restart_on_crash", True)
        return "restart" if restart_on_crash else "alert"

    return "noop"


def format_health_summary(report: dict[str, Any]) -> str:
    """Format a health evaluation report as a human-readable string."""
    lines = []
    state = report.get("state", "unknown")
    healthy = "HEALTHY" if report.get("healthy") else "UNHEALTHY"
    lines.append(f"  State: {state} ({healthy})")
    if report.get("pid"):
        lines.append(f"  PID: {report['pid']}")
    if report.get("uptime_display"):
        lines.append(f"  Uptime: {report['uptime_display']}")
    if report.get("crash_count"):
        lines.append(f"  Crashes: {report['crash_count']}")
    if report.get("last_error"):
        lines.append(f"  Last error: {report['last_error'][:200]}")
    if report.get("recommendation"):
        lines.append(f"  → {report['recommendation']}")
    return "\n".join(lines)


def _format_uptime(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s}s"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"
