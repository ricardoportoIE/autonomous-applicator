"""Require complete runtime coverage for every Python application module."""

import ast
import json
from pathlib import Path
from typing import Any


def protocol_declarations(source: str) -> set[int]:
    """Coverage.py excludes signature-only Protocols; allow no executable method bodies."""
    allowed: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ClassDef) or not any(
            isinstance(base, ast.Name) and base.id == "Protocol" for base in node.bases
        ):
            continue
        if all(
            isinstance(method, ast.FunctionDef)
            and not method.decorator_list
            and len(method.body) == 1
            and isinstance(method.body[0], ast.Expr)
            and isinstance(method.body[0].value, ast.Constant)
            and method.body[0].value.value is Ellipsis
            for method in node.body
        ):
            allowed.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return allowed


def type_import_declarations(source: str) -> set[int]:
    """Allow only import declarations guarded by typing's unmodified TYPE_CHECKING."""
    tree = ast.parse(source)
    bindings = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and any((alias.asname or alias.name) == "TYPE_CHECKING" for alias in node.names)
    ]
    if len(bindings) != 1 or not isinstance(bindings[0], ast.ImportFrom):
        return set()
    declaration = bindings[0]
    if declaration.module != "typing" or not any(
        alias.name == "TYPE_CHECKING" and alias.asname is None for alias in declaration.names
    ):
        return set()
    if any(
        isinstance(node, ast.Name)
        and node.id == "TYPE_CHECKING"
        and not isinstance(node.ctx, ast.Load)
        or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name == "TYPE_CHECKING"
        for node in ast.walk(tree)
    ):
        return set()
    allowed: set[int] = set()
    for node in tree.body:
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "TYPE_CHECKING"
            and not node.orelse
            and all(isinstance(item, (ast.Import, ast.ImportFrom)) for item in node.body)
        ):
            allowed.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return allowed


def validate_report(root: Path, report: dict[str, Any]) -> tuple[int, int, int]:
    inventory = {
        path.relative_to(root).as_posix(): path
        for path in (root / "src" / "applicator").rglob("*.py")
    }
    measured = {name.replace("\\", "/"): value for name, value in report["files"].items()}
    if not inventory or set(inventory) != set(measured):
        raise ValueError("Coverage inventory does not match every authored backend module")
    statements = branches = 0
    for name, path in inventory.items():
        record = measured[name]
        summary = record["summary"]
        source = path.read_text(encoding="utf-8")
        excluded = set(record["excluded_lines"])
        substantive = {line for line in excluded if source.splitlines()[line - 1].strip()}
        if (
            substantive - (protocol_declarations(source) | type_import_declarations(source))
            or "pragma: no cover" in source
            or "pragma: no branch" in source
        ):
            raise ValueError(f"Runtime coverage exclusions are not permitted: {name}")
        if (
            record["missing_lines"]
            or record["missing_branches"]
            or summary["missing_lines"]
            or summary["missing_branches"]
        ):
            raise ValueError(f"Backend coverage must be 100% for each module: {name}")
        if (
            summary["covered_lines"] != summary["num_statements"]
            or summary["covered_branches"] != summary["num_branches"]
        ):
            raise ValueError(f"Inconsistent coverage counters: {name}")
        statements += summary["num_statements"]
        branches += summary["num_branches"]
    return len(inventory), statements, branches


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    report = json.loads(
        (root / "test-results" / "backend-coverage.json").read_text(encoding="utf-8")
    )
    if not report["meta"]["branch_coverage"]:
        raise ValueError("Backend branch measurement is required")
    modules, statements, branches = validate_report(root, report)
    print(
        f"Backend: {modules} modules, {statements}/{statements} statements and {branches}/{branches} branch outcomes; 100% in every module."
    )


if __name__ == "__main__":
    main()
