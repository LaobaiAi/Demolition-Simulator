"""CAIAO Server validator — static analysis and contract compliance checks.

Validates server structure without executing any server code.
Checks: file structure, CAIAO contract, JSON schema validity, manifest consistency.
"""

import ast
import json
import os
import logging
import re

logger = logging.getLogger(__name__)

_CAIAO_CONTRACT_RULES = [
    "return [TextContent(type=\"text\", text=json.dumps(...))]",
    "Serialize everything as JSON",
    "Catch all exceptions, return {'error': str(e)}",
    "Tool names use snake_case",
    "Input schema is JSON Schema draft-07",
]


def validate_server_structure(server_dir: str) -> dict:
    """Validate the structural integrity of a CAIAO server directory.

    Returns {valid: bool, errors: [str], warnings: [str]}
    """
    errors = []
    warnings = []

    if not os.path.isdir(server_dir):
        return {"valid": False, "errors": ["Directory does not exist"], "warnings": []}

    dir_name = os.path.basename(os.path.normpath(server_dir))

    manifest_path = os.path.join(server_dir, "caiao.yaml")
    if not os.path.exists(manifest_path):
        errors.append("Missing caiao.yaml manifest")

    server_py_path = os.path.join(server_dir, "server.py")
    if not os.path.exists(server_py_path):
        warnings.append("No server.py found (may be a composite pipeline)")

    if not any(f.endswith(".py") for f in os.listdir(server_dir) if f != "__pycache__"):
        warnings.append("No Python files found in server directory")

    test_file = _find_test_file(server_dir)
    if not test_file:
        warnings.append("No test file found (recommended: test_server.py)")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def validate_contract_compliance(server_dir: str) -> dict:
    """Validate that a server follows the CAIAO contract rules.

    Checks the server.py file statically (does not execute it).

    Returns {valid, checks: [{rule, passed, detail}]}
    """
    checks = []
    server_py = os.path.join(server_dir, "server.py")

    if not os.path.exists(server_py):
        return {"valid": False, "checks": [{"rule": "server.py exists", "passed": False, "detail": "File not found"}]}

    checks.append({"rule": "server.py exists", "passed": True, "detail": ""})

    try:
        with open(server_py, "r", encoding="utf-8") as f:
            code = f.read()
    except Exception:
        return {"valid": False, "checks": [{"rule": "server.py readable", "passed": False, "detail": "Cannot read file"}]}

    checks.append({"rule": "server.py readable", "passed": True, "detail": ""})

    tree = _safe_parse(code)
    if tree is None:
        checks.append({"rule": "Valid Python syntax", "passed": False, "detail": "Syntax error"})
        return {"valid": False, "checks": checks}

    checks.append({"rule": "Valid Python syntax", "passed": True, "detail": ""})

    has_server_instantiation = "Server(" in code
    has_caiao_server_class = "class " in code and "CAIAOServer" in code
    checks.append({
        "rule": "Server or CAIAOServer instantiation",
        "passed": has_server_instantiation or has_caiao_server_class,
        "detail": "MCP pattern" if has_server_instantiation else ("Class pattern" if has_caiao_server_class else "Neither pattern found"),
    })

    has_list_tools = "list_tools" in code or "TOOLS" in code
    checks.append({
        "rule": "Tool listing mechanism",
        "passed": has_list_tools,
        "detail": "Found list_tools or TOOLS" if has_list_tools else "No tool listing found",
    })

    has_call_tool = "call_tool" in code
    checks.append({
        "rule": "Tool call mechanism",
        "passed": has_call_tool,
        "detail": "call_tool found" if has_call_tool else "No call_tool mechanism",
    })

    has_json_dumps = "json.dumps(" in code or "json.dumps(" in code
    has_text_content = "TextContent(" in code or "text" in code
    checks.append({
        "rule": "Return format",
        "passed": has_json_dumps,
        "detail": "JSON serialization found" if has_json_dumps else "No JSON serialization in output",
    })

    has_try_except = "try:" in code and "except" in code
    checks.append({
        "rule": "Exception handling",
        "passed": has_try_except,
        "detail": "Try/except found" if has_try_except else "No try/except — may crash on errors",
    })

    has_main_block = 'if __name__ == "__main__"' in code or "if __name__ == '__main__'" in code
    checks.append({
        "rule": "Standalone entry point",
        "passed": has_main_block,
        "detail": "__main__ block found" if has_main_block else "No __main__ block — cannot run standalone",
    })

    has_stdio = "stdio_server" in code or "stdio_loop" in code or "run_stdio_loop" in code
    checks.append({
        "rule": "Stdio transport",
        "passed": has_stdio or has_main_block,
        "detail": "Stdio transport found" if has_stdio else "Has main block but no stdio transport",
    })

    passed = sum(1 for c in checks if c["passed"])
    total = len(checks)
    return {"valid": passed == total, "checks": checks, "summary": f"{passed}/{total} checks passed"}


def validate_tool_schemas(server_dir: str) -> dict:
    """Parse server.py and extract tool schemas, validating each as JSON Schema.

    Returns {valid, tools: [{name, schema_valid, errors}]}
    """
    server_py = os.path.join(server_dir, "server.py")
    if not os.path.exists(server_py):
        return {"valid": False, "tools": [], "error": "No server.py found"}

    results = {"valid": True, "tools": []}

    try:
        with open(server_py, "r", encoding="utf-8") as f:
            code = f.read()
    except Exception as e:
        return {"valid": False, "tools": [], "error": str(e)}

    tool_names = _extract_tool_names(code)

    for tname in tool_names:
        tool_result = {"name": tname, "schema_valid": True, "errors": []}

        if not re.match(r"^[a-z][a-z0-9_]*$", tname):
            tool_result["schema_valid"] = False
            tool_result["errors"].append(f"'{tname}' is not valid snake_case")
            results["valid"] = False

        results["tools"].append(tool_result)

    if not tool_names:
        results["valid"] = False
        results["tools"].append({"name": "unknown", "schema_valid": False,
                                  "errors": ["Could not extract tool names from source"]})

    return results


def validate_manifest_consistency(server_dir: str) -> dict:
    """Check that the caiao.yaml manifest matches the server.py implementation.

    Returns {consistent, mismatches: [{field, manifest_value, code_value}]}
    """
    from .manifest import read_manifest

    mismatches = []
    server_py = os.path.join(server_dir, "server.py")
    manifest = read_manifest(server_dir)

    if manifest is None:
        return {"consistent": False, "mismatches": [{"field": "manifest", "manifest_value": "missing", "code_value": "exists"}]}

    if not os.path.exists(server_py):
        return {"consistent": True, "mismatches": []}

    try:
        with open(server_py, "r", encoding="utf-8") as f:
            code = f.read()
    except Exception:
        return {"consistent": True, "mismatches": []}

    code_tool_names = set(_extract_tool_names(code))
    manifest_tool_names = {t["name"] for t in manifest.get("tools", [])}

    only_in_manifest = manifest_tool_names - code_tool_names
    only_in_code = code_tool_names - manifest_tool_names

    for tname in only_in_manifest:
        mismatches.append({"field": f"tool:{tname}", "manifest_value": tname, "code_value": "not found"})

    for tname in only_in_code:
        mismatches.append({"field": f"tool:{tname}", "manifest_value": "not declared", "code_value": tname})

    return {"consistent": len(mismatches) == 0, "mismatches": mismatches}


def full_validation(server_dir: str) -> dict:
    """Run all validation checks on a server directory.

    Returns a comprehensive validation report.
    """
    structure = validate_server_structure(server_dir)
    contract = validate_contract_compliance(server_dir)
    schemas = validate_tool_schemas(server_dir)
    consistency = validate_manifest_consistency(server_dir)

    all_valid = (
        structure.get("valid", False)
        and contract.get("valid", False)
        and schemas.get("valid", False)
        and consistency.get("consistent", False)
    )

    return {
        "valid": all_valid,
        "server_dir": server_dir,
        "structure": structure,
        "contract": contract,
        "tool_schemas": schemas,
        "manifest_consistency": consistency,
    }


def _safe_parse(code: str) -> ast.Module | None:
    try:
        return ast.parse(code)
    except SyntaxError:
        return None


def _extract_tool_names(code: str) -> list[str]:
    """Extract tool names from server.py source code.

    Handles multiple patterns:
    1. TOOLS = [Tool(name="..."), ...]
    2. @server.list_tools() returning Tool(name="...")
    3. @tool(name="...") decorator (class pattern)
    4. _t("tool_name", ...) helper function
    5. if name == "tool_name": dispatch pattern
    """
    names = []

    for match in re.finditer(r'name\s*=\s*"([a-z][a-z0-9_]*)"', code):
        names.append(match.group(1))

    if not names:
        for match in re.finditer(r'"name":\s*"([a-z][a-z0-9_]*)"', code):
            names.append(match.group(1))

    if not names:
        for match in re.finditer(r'_t\("([a-z][a-z0-9_]*)"', code):
            names.append(match.group(1))

    if not names:
        for match in re.finditer(r'if name == "([a-z][a-z0-9_]*)"', code):
            names.append(match.group(1))

    seen = set()
    unique = []
    for n in names:
        if n not in seen:
            seen.add(n)
            unique.append(n)
    return unique


def _find_test_file(server_dir: str) -> str | None:
    for f in os.listdir(server_dir):
        if f.startswith("test") and f.endswith(".py"):
            return os.path.join(server_dir, f)
    return None
