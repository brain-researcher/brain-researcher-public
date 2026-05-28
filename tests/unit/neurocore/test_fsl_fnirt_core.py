from brain_researcher.services.tools.params import (
    FSLFNIRTParameters,
    build_fsl_fnirt_command,
    fsl_fnirt_from_payload,
)


def test_fsl_fnirt_command_tokens():
    params = FSLFNIRTParameters(
        in_file="/data/sub-01_T1w.nii.gz",
        ref_file="/tpl/MNI152_T1_2mm.nii.gz",
        output_dir="/out",
        out_file="/out/sub-01_fnirt.nii.gz",
        field_file="/out/sub-01_warp.nii.gz",
        jacobian_file="/out/sub-01_jac.nii.gz",
        affine_file="/xfm/sub-01_flirt.mat",
        warp_resolution="10,10,10",
        spline_order=3,
        regularization_lambda="10,5,2,1",
        regularization_model="membrane_energy",
        max_iterations="5,5,5,5",
        subsample_levels="4,2,1,1",
        intensity_mapping=True,
        intensity_mapping_order=5,
        ref_mask="/tpl/mask.nii.gz",
        in_mask="/data/mask.nii.gz",
        apply_ref_mask=1,
        apply_in_mask=1,
        use_gradient_images=True,
        jacobian_range="0.01,100",
        verbose=True,
        debug=True,
    )

    cmd = build_fsl_fnirt_command(params, include_executable=True)
    assert cmd[0] == "fnirt"
    assert any(token.startswith("--in=/data/sub-01_T1w.nii.gz") for token in cmd)
    assert "--miter=5,5,5,5" in cmd
    assert "--subsamp=4,2,1,1" in cmd
    assert "--regmod=membrane_energy" in cmd
    assert "--verbose" in cmd


def test_fsl_fnirt_from_payload():
    payload = {
        "in_file": "/in.nii.gz",
        "ref_file": "/ref.nii.gz",
        "output_dir": "/out",
        "warp_resolution": "12,12,12",
        "intensity_mapping": True,
        "intensity_mapping_order": 7,
    }
    params = fsl_fnirt_from_payload(payload)
    assert params.intensity_mapping is True
    cmd = build_fsl_fnirt_command(params, include_executable=False)
    assert any(token.startswith("--warpres=12,12,12") for token in cmd)
