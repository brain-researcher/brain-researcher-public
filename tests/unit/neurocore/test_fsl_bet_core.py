from brain_researcher.services.tools.params import (
    FSLBETParameters,
    build_fsl_bet_command,
    fsl_bet_from_payload,
)


def test_fsl_bet_command_tokens():
    params = FSLBETParameters(
        input_file="/data/t1.nii.gz",
        output_file="/out/t1_brain.nii.gz",
        fractional_intensity=0.45,
        gradient_threshold=0.1,
        generate_mask=True,
        generate_skull=True,
        reduce_bias=True,
        robust_center=True,
        center_coordinates=(10, 20, 30),
        radius=60,
        extra_flags=("-test",),
    )

    cmd = build_fsl_bet_command(params, include_executable=True)
    assert cmd[0] == "bet"
    assert cmd[1:3] == ["/data/t1.nii.gz", "/out/t1_brain.nii.gz"]
    assert "-m" in cmd and "-s" in cmd
    assert "-c" in cmd and "-r" in cmd
    assert cmd[-1] == "-test"


def test_fsl_bet_from_payload():
    payload = {
        "input_file": "/in/t2.nii.gz",
        "output_file": "/out/t2_brain.nii.gz",
        "fractional_intensity": 0.3,
        "center_coordinates": [1, 2, 3],
    }
    params = fsl_bet_from_payload(payload)
    assert params.center_coordinates == (1.0, 2.0, 3.0)
    cmd = build_fsl_bet_command(params, include_executable=False)
    assert cmd[0] == "/in/t2.nii.gz"
