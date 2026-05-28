from brain_researcher.services.tools.params import (
    FSLMELODICParameters,
    build_fsl_melodic_command,
)


def test_fsl_melodic_command_tokens():
    params = FSLMELODICParameters(
        input_files=("/data/sub-01_bold.nii.gz",),
        output_dir="/out/melodic",
        tr=2.0,
        approach="tensor",
        dimensionality="manual",
        n_components=25,
        mask="/masks/brain.nii.gz",
        bg_threshold=0.5,
        var_norm=True,
        output_all=True,
        report=True,
        extra_args=("--mmthresh=0.5",),
    )

    cmd = build_fsl_melodic_command(params, include_executable=True)
    assert cmd[0] == "melodic"
    assert "-i" in cmd
    assert "/data/sub-01_bold.nii.gz" in cmd
    assert "-o" in cmd and "/out/melodic" in cmd
    assert "-a" in cmd and "tensor" in cmd
    assert "-d" in cmd and "25" in cmd
    assert "-m" in cmd and "/masks/brain.nii.gz" in cmd
    assert "--bgthreshold" in cmd
    assert "--Oall" in cmd
    assert cmd[-1] == "--mmthresh=0.5"


def test_fsl_melodic_command_without_exec():
    params = FSLMELODICParameters(
        input_files="/data/bold.nii.gz",
        output_dir="/out",
        tr=1.5,
    )

    cmd = build_fsl_melodic_command(params, include_executable=False)
    assert cmd[0] == "-i"
    assert "melodic" not in cmd[:2]
