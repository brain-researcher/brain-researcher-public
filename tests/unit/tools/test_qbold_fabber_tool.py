from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.tools.params.qbold_fabber import (
    build_qbold_fabber_command,
    qbold_fabber_from_payload,
)
from brain_researcher.services.tools.qbold_fabber_tool import QBoldFabberTool


def test_qbold_fabber_tool_writes_plan_and_command_preview(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "brain_researcher.services.tools.params.qbold_fabber.shutil.which",
        lambda _: "/opt/fabber_qbold",
    )

    input_file = tmp_path / "ase.nii.gz"
    mask_file = tmp_path / "mask.nii.gz"
    input_file.write_text("input", encoding="utf-8")
    mask_file.write_text("mask", encoding="utf-8")

    result = QBoldFabberTool()._run(
        input_file=str(input_file),
        mask_file=str(mask_file),
        output_dir=str(tmp_path / "out"),
        method="vb",
        model="qbold",
        te=0.032,
        echo_times=[0.012, 0.024, 0.036],
        tau_list=[0.008, 0.016],
        priors={"oef": 0.45},
        extra_args=["--verbose"],
    )

    assert result.status == "success"
    outputs = result.data["outputs"]
    plan_json = Path(outputs["plan_json"])
    command_preview = Path(outputs["command_preview"])
    assert plan_json.exists()
    assert command_preview.exists()

    plan = json.loads(plan_json.read_text(encoding="utf-8"))
    assert plan["environment"]["binary_available"] is True
    assert plan["planned_command"][0] == "/opt/fabber_qbold"
    assert "--mask" in plan["planned_command"]
    assert "--infer-oef" in plan["planned_command"]
    assert "--verbose" in plan["planned_command"]
    assert plan["expected_outputs"]["oef_map"].endswith("qbold_oef_map.nii.gz")
    assert result.data["summary"]["backend_available"] is True
    assert result.data["summary"]["method"] == "vb"
    assert result.data["summary"]["echo_times_count"] == 3
    assert result.data["summary"]["tau_list_count"] == 2


def test_qbold_fabber_tool_reports_missing_backend_but_still_plans(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "brain_researcher.services.tools.params.qbold_fabber.shutil.which",
        lambda _: None,
    )

    input_file = tmp_path / "ase.csv"
    input_file.write_text("x", encoding="utf-8")

    result = QBoldFabberTool()._run(
        input_file=str(input_file),
        output_dir=str(tmp_path / "planned"),
        infer_oef=False,
        infer_dbv=False,
        infer_r2p=True,
    )

    assert result.status == "success"
    summary = result.data["summary"]
    assert summary["backend_available"] is False
    assert summary["resolved_executable"] == "fabber_qbold"
    assert summary["planned_command"][0] == "fabber_qbold"
    assert "--no-infer-oef" in summary["planned_command"]
    assert "--no-infer-dbv" in summary["planned_command"]
    assert "--infer-r2p" in summary["planned_command"]


def test_qbold_fabber_command_builder_uses_parameter_payload() -> None:
    params = qbold_fabber_from_payload(
        {
            "input_file": "/tmp/input.nii.gz",
            "mask_file": "/tmp/mask.nii.gz",
            "echo_times": "0.01,0.02",
            "tau_list": [0.005, 0.010],
            "priors": {"dbv": 0.02},
            "extra_args": "--save-std --save-mean",
        }
    )
    command = build_qbold_fabber_command(params, executable="/opt/fabber_qbold")

    assert command[:6] == [
        "/opt/fabber_qbold",
        "--data",
        "/tmp/input.nii.gz",
        "--output",
        str(Path.cwd() / "qbold_fabber"),
        "--model",
    ]
    assert "--mask" in command
    assert "--echo-times" in command
    assert "--tau-list" in command
    assert "--prior" in command
    assert "--save-std" in command
    assert "--save-mean" in command


def test_qbold_fabber_tool_executes_when_backend_is_available(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "brain_researcher.services.tools.params.qbold_fabber.shutil.which",
        lambda _: "/opt/fabber_qbold",
    )

    def _fake_run(cmd, **kwargs):
        out_dir = Path(kwargs["cwd"])
        for name in [
            "qbold_oef_map.nii.gz",
            "qbold_dbv_map.nii.gz",
            "qbold_r2p_map.nii.gz",
            "qbold_posterior_summary.json",
            "qbold_fabber.log",
        ]:
            (out_dir / name).write_text(name, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="fabber ok\n", stderr="")

    import subprocess

    monkeypatch.setattr(
        "brain_researcher.services.tools.params.qbold_fabber.subprocess.run",
        _fake_run,
    )

    input_file = tmp_path / "ase.nii.gz"
    input_file.write_text("input", encoding="utf-8")

    result = QBoldFabberTool()._run(
        input_file=str(input_file),
        output_dir=str(tmp_path / "out"),
        dry_run=False,
    )

    assert result.status == "success"
    summary = result.data["summary"]
    outputs = result.data["outputs"]
    assert summary["mode"] == "executed"
    assert summary["dry_run"] is False
    assert summary["returncode"] == 0
    assert "oef_map" in summary["materialized_output_keys"]
    assert Path(outputs["execution_report"]).exists()
    assert Path(outputs["stdout"]).exists()
    assert Path(outputs["stderr"]).exists()
    assert Path(outputs["expected_outputs"]["oef_map"]).exists()
    assert Path(outputs["materialized_outputs"]["oef_map"]).exists()
