import json

from typer.testing import CliRunner


def _parse_json_output(text: str) -> dict:
    # Extract JSON-like block from Rich JSON output
    start = text.find("{")
    end = text.rfind("}")
    assert start != -1 and end != -1

    return json.loads(text[start : end + 1])


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def test_tools_list_and_gen():
    from brain_researcher.cli.main import app

    runner = CliRunner()
    # list tools
    res = runner.invoke(app, ["tools", "list"], prog_name="brain-researcher")
    assert res.exit_code == 0
    assert '"tools"' in res.output

    # generate FSL BET command (module mode)
    res2 = runner.invoke(
        app,
        [
            "tools",
            "gen",
            "-t",
            "fsl",
            "-c",
            "bet",
            "-i",
            "input.nii.gz",
            "-o",
            "output.nii.gz",
            "-p",
            '{"f":0.5}',
        ],
        prog_name="brain-researcher",
    )
    assert res2.exit_code == 0
    # should contain a command and instructions fields
    assert '"command"' in res2.output
    assert '"instructions"' in res2.output


def test_tools_gen_cvmfs_mode():
    from brain_researcher.cli.main import app
    from brain_researcher.services.tools.neurodesk_tools import NEURODESK_TOOLS

    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "tools",
            "gen",
            "-t",
            "fsl",
            "-c",
            "bet",
            "-i",
            "input.nii.gz",
            "-o",
            "output.nii.gz",
            "--mode",
            "cvmfs",
        ],
        prog_name="brain-researcher",
    )
    assert res.exit_code == 0
    out = _normalize_whitespace(res.output)
    # Ensure apptainer call and expected container path
    assert "apptainer exec" in out
    assert f"/containers/fsl_{NEURODESK_TOOLS['fsl'].version}" in out
    assert " bet " in out or '"bet"' in out


def test_tools_gen_mrtrix3_mrinfo_and_afni_skullstrip():
    from brain_researcher.cli.main import app
    from brain_researcher.services.tools.neurodesk_tools import NEURODESK_TOOLS

    runner = CliRunner()
    # MRtrix3 mrinfo
    res_mrt = runner.invoke(
        app,
        [
            "tools",
            "gen",
            "-t",
            "mrtrix3",
            "-c",
            "mrinfo",
            "-i",
            "dwi.mif",
            "--mode",
            "module",
        ],
        prog_name="brain-researcher",
    )
    assert res_mrt.exit_code == 0
    out_mrt = _normalize_whitespace(res_mrt.output)
    assert (
        f"module load {NEURODESK_TOOLS['mrtrix3'].module_name}/"
        f"{NEURODESK_TOOLS['mrtrix3'].version}"
    ) in out_mrt
    assert "mrinfo dwi.mif" in out_mrt

    # AFNI 3dSkullStrip
    res_afni = runner.invoke(
        app,
        [
            "tools",
            "gen",
            "-t",
            "afni",
            "-c",
            "3dSkullStrip",
            "-i",
            "in.nii.gz",
            "-o",
            "out.nii.gz",
        ],
        prog_name="brain-researcher",
    )
    assert res_afni.exit_code == 0
    out_afni = _normalize_whitespace(res_afni.output)
    assert (
        f"module load {NEURODESK_TOOLS['afni'].module_name}/"
        f"{NEURODESK_TOOLS['afni'].version}"
    ) in out_afni
    assert "3dSkullStrip in.nii.gz out.nii.gz" in out_afni


def test_tools_gen_ants_registration_and_batch():
    from brain_researcher.cli.main import app
    from brain_researcher.services.tools.neurodesk_tools import NEURODESK_TOOLS

    runner = CliRunner()
    # ANTs antsRegistration
    res_ants = runner.invoke(
        app,
        [
            "tools",
            "gen",
            "-t",
            "ants",
            "-c",
            "antsRegistration",
            "-i",
            "moving.nii.gz",
            "-o",
            "output.nii.gz",
            "-p",
            '{"d":3}',
        ],
        prog_name="brain-researcher",
    )
    assert res_ants.exit_code == 0
    out_ants = _normalize_whitespace(res_ants.output)
    assert (
        f"module load {NEURODESK_TOOLS['ants'].module_name}/"
        f"{NEURODESK_TOOLS['ants'].version}"
    ) in out_ants
    assert "antsRegistration moving.nii.gz" in out_ants
    assert "output.nii.gz" in out_ants

    # Batch generation (two simple steps)
    commands = {
        "commands": [
            {
                "tool_name": "fsl",
                "command": "bet",
                "input_files": ["in.nii.gz"],
                "output_path": "out.nii.gz",
            },
            {
                "tool_name": "mrtrix3",
                "command": "mrinfo",
                "input_files": ["dwi.mif"],
            },
        ]
    }
    spec = json.dumps(commands)
    res_batch = runner.invoke(
        app,
        [
            "tools",
            "batch",
            spec,
            "--name",
            "demo",
        ],
        prog_name="brain-researcher",
    )
    assert res_batch.exit_code == 0
    out_batch = res_batch.output
    # Expect a bash shebang and our commands in the script
    assert "#!/bin/bash" in out_batch
    assert "bet in.nii.gz out.nii.gz" in out_batch
    assert "mrinfo dwi.mif" in out_batch


def test_tools_gen_fslmaths_and_ants_applytransforms_and_batch_parallel():
    from brain_researcher.cli.main import app
    from brain_researcher.services.tools.neurodesk_tools import NEURODESK_TOOLS

    runner = CliRunner()

    # fslmaths add
    res_fslm = runner.invoke(
        app,
        [
            "tools",
            "gen",
            "-t",
            "fsl",
            "-c",
            "fslmaths",
            "-i",
            "a.nii.gz",
            "-o",
            "c.nii.gz",
            "-p",
            '{"add":"b.nii.gz"}',
        ],
        prog_name="brain-researcher",
    )
    assert res_fslm.exit_code == 0
    out_fslm = _normalize_whitespace(res_fslm.output)
    assert "module load fsl/" in out_fslm
    assert "fslmaths a.nii.gz" in out_fslm
    # Rich JSON pretty-print may break flag and value across lines
    assert ("-add" in out_fslm) or ("--add" in out_fslm)
    assert "b.nii.gz" in out_fslm
    assert "c.nii.gz" in out_fslm

    # ANTs antsApplyTransforms with flags
    spec_params = '{"d":3,"i":"mov.nii.gz","r":"ref.nii.gz","t":"tx1.h5"}'
    res_apply = runner.invoke(
        app,
        [
            "tools",
            "gen",
            "-t",
            "ants",
            "-c",
            "antsApplyTransforms",
            "-i",
            "mov.nii.gz",
            "-o",
            "warp_out.nii.gz",
            "-p",
            spec_params,
        ],
        prog_name="brain-researcher",
    )
    assert res_apply.exit_code == 0
    out_apply = _normalize_whitespace(res_apply.output)
    assert (
        f"module load {NEURODESK_TOOLS['ants'].module_name}/"
        f"{NEURODESK_TOOLS['ants'].version}"
    ) in out_apply
    assert "antsApplyTransforms" in out_apply
    assert "-d 3" in out_apply
    assert "-i mov.nii.gz" in out_apply
    assert "-r ref.nii.gz" in out_apply
    assert "-t tx1.h5" in out_apply
    assert "warp_out.nii.gz" in out_apply

    # Batch parallel
    commands = {
        "commands": [
            {
                "tool_name": "fsl",
                "command": "bet",
                "input_files": ["in.nii.gz"],
                "output_path": "out.nii.gz",
            },
            {"tool_name": "mrtrix3", "command": "mrinfo", "input_files": ["dwi.mif"]},
        ]
    }
    res_batch = runner.invoke(
        app,
        [
            "tools",
            "batch",
            json.dumps(commands),
            "--parallel",
        ],
        prog_name="brain-researcher",
    )
    assert res_batch.exit_code == 0
    out_batch = res_batch.output
    assert "#!/bin/bash" in out_batch
    # Commands placed in background and a wait present
    assert " &\n" in out_batch or " &" in out_batch
    assert "wait" in out_batch
