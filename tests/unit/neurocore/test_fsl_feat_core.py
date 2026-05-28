from brain_researcher.services.tools.params import (
    FSLFEATParameters,
    build_fsl_feat_command,
    build_fsl_feat_env,
)


def test_fsl_feat_command_with_exec():
    params = FSLFEATParameters(
        fsf_path="/design/first_level.fsf",
        working_dir="/work",
        env={"FSLDIR": "/opt/fsl"},
        extra_args=("-force",),
    )

    cmd = build_fsl_feat_command(params, include_executable=True)
    assert cmd[:2] == ["feat", "/design/first_level.fsf"]
    assert cmd[-1] == "-force"

    env = build_fsl_feat_env(params)
    assert env["FSLDIR"] == "/opt/fsl"


def test_fsl_feat_command_without_exec():
    params = FSLFEATParameters(fsf_path="/design.fsf")
    cmd = build_fsl_feat_command(params, include_executable=False)
    assert cmd == ["/design.fsf"]
