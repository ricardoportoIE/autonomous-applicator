"""The coverage gate must reject incomplete inventories, branches and runtime exclusions."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "backend_coverage_gate",
    Path(__file__).resolve().parents[1] / "scripts" / "check_backend_coverage.py",
)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


@pytest.fixture
def measured(tmp_path):
    folder = tmp_path / "src" / "applicator"
    folder.mkdir(parents=True)
    path = folder / "example.py"
    path.write_text("answer = 42\n", encoding="utf-8")
    record = {
        "summary": {
            "num_statements": 1,
            "covered_lines": 1,
            "missing_lines": 0,
            "num_branches": 2,
            "covered_branches": 2,
            "missing_branches": 0,
        },
        "missing_lines": [],
        "missing_branches": [],
        "excluded_lines": [],
    }
    report = {"meta": {"branch_coverage": True}, "files": {"src/applicator/example.py": record}}
    return tmp_path, path, report


@pytest.mark.parametrize("windows", [False, True])
def test_gate_accepts_complete_coverage_with_portable_paths(measured, windows):
    root, _, report = measured
    if windows:
        report["files"]["src\\applicator\\example.py"] = report["files"].pop(
            "src/applicator/example.py"
        )
    assert gate.validate_report(root, report) == (1, 1, 2)


@pytest.mark.parametrize(
    "fault",
    [
        "missing_module",
        "extra_module",
        "unmeasured_module",
        "missing_line",
        "missing_branch",
        "counter_line",
        "counter_branch",
        "counter_missing",
        "runtime_exclusion",
        "ignore_line",
        "ignore_branch",
        "executable_protocol",
    ],
)
def test_gate_rejects_missing_execution_and_hidden_runtime_paths(measured, fault):
    root, path, report = measured
    record = report["files"]["src/applicator/example.py"]
    if fault == "missing_module":
        report["files"].clear()
    elif fault == "extra_module":
        report["files"]["src/applicator/other.py"] = copy.deepcopy(record)
    elif fault == "unmeasured_module":
        (path.parent / "unmeasured.py").write_text("value = 1\n", encoding="utf-8")
    elif fault == "missing_line":
        record["missing_lines"] = [1]
    elif fault == "missing_branch":
        record["missing_branches"] = [[1, 2]]
    elif fault == "counter_line":
        record["summary"]["covered_lines"] = 0
    elif fault == "counter_branch":
        record["summary"]["covered_branches"] = 1
    elif fault == "counter_missing":
        record["summary"]["missing_branches"] = 1
    elif fault == "runtime_exclusion":
        record["excluded_lines"] = [1]
    elif fault.startswith("ignore"):
        path.write_text(
            "answer = 42  # pragma: no " + ("cover" if fault == "ignore_line" else "branch") + "\n",
            encoding="utf-8",
        )
    else:
        path.write_text(
            "class Provider(Protocol):\n    def submit(self):\n        return 'sent'\n",
            encoding="utf-8",
        )
        record["excluded_lines"] = [1, 2, 3]
    with pytest.raises(ValueError):
        gate.validate_report(root, report)


def test_only_signature_protocols_and_blank_lines_can_be_excluded(measured):
    root, path, report = measured
    path.write_text(
        "from typing import Protocol\nclass Provider(Protocol):\n    def submit(self) -> str: ...\n\n",
        encoding="utf-8",
    )
    report["files"]["src/applicator/example.py"]["excluded_lines"] = [2, 3, 4]
    assert gate.validate_report(root, report) == (1, 1, 2)
    assert (
        gate.protocol_declarations(
            "class Provider(Protocol):\n    @staticmethod\n    def submit(): ...\n"
        )
        == set()
    )


def test_canonical_annotation_imports_are_not_runtime_exclusions(measured):
    root, path, report = measured
    source = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from .store import Store\n"
    path.write_text(source, encoding="utf-8")
    report["files"]["src/applicator/example.py"]["excluded_lines"] = [2, 3]
    assert gate.type_import_declarations(source) == {2, 3}
    assert gate.validate_report(root, report) == (1, 1, 2)


@pytest.mark.parametrize(
    "source",
    [
        "if TYPE_CHECKING:\n    import example\n",
        "from other import TYPE_CHECKING\nif TYPE_CHECKING:\n    import example\n",
        "from typing import TYPE_CHECKING as tc\nif tc:\n    import example\n",
        "import other as TYPE_CHECKING\nif TYPE_CHECKING:\n    import example\n",
        "from typing import TYPE_CHECKING\nTYPE_CHECKING=True\nif TYPE_CHECKING:\n    import example\n",
        "from typing import TYPE_CHECKING\nimport other as TYPE_CHECKING\nif TYPE_CHECKING:\n    import example\n",
        "from typing import TYPE_CHECKING\ndef TYPE_CHECKING(): pass\nif TYPE_CHECKING:\n    import example\n",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    send_application()\n",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import example\n    send_application()\n",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import example\nelse:\n    send_application()\n",
        "from typing import TYPE_CHECKING\nif not TYPE_CHECKING:\n    import example\n",
        "from typing import TYPE_CHECKING\ndef runtime():\n    if TYPE_CHECKING:\n        import example\n",
    ],
)
def test_annotation_exception_rejects_runtime_or_shadowed_type_guards(measured, source):
    root, path, report = measured
    path.write_text(source, encoding="utf-8")
    report["files"]["src/applicator/example.py"]["excluded_lines"] = list(
        range(2, len(source.splitlines()) + 1)
    )
    assert gate.type_import_declarations(source) == set()
    with pytest.raises(ValueError, match="Runtime coverage exclusions"):
        gate.validate_report(root, report)


@pytest.mark.parametrize("branches", [True, False])
def test_cli_reports_counts_and_rejects_line_only_measurement(
    measured, monkeypatch, capsys, branches
):
    root, _, report = measured
    report["meta"]["branch_coverage"] = branches
    (root / "test-results").mkdir()
    (root / "test-results" / "backend-coverage.json").write_text(
        json.dumps(report), encoding="utf-8"
    )
    monkeypatch.setattr(gate, "__file__", str(root / "scripts" / "check_backend_coverage.py"))
    if branches:
        gate.main()
        assert (
            "1/1 statements and 2/2 branch outcomes; 100% in every module"
            in capsys.readouterr().out
        )
    else:
        with pytest.raises(ValueError, match="branch measurement"):
            gate.main()
