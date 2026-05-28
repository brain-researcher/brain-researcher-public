from brain_researcher.services.tools.params import (
    FreeSurferReconAllParameters,
    build_freesurfer_command,
    build_freesurfer_env,
)


def test_freesurfer_command_tokens():
    params = FreeSurferReconAllParameters(
        subject_id="sub-01",
        subjects_dir="/subjects",
        t1_image="/data/t1.nii.gz",
        stage="all",
        t2_image="/data/t2.nii.gz",
        hippocampal_subfields=True,
        brainstem=True,
        thalamus=True,
        parallel=True,
        n_threads=8,
        use_gpu=True,
        license_file="/licenses/fs_license.txt",
        flags=("-noskullstrip",),
    )

    cmd = build_freesurfer_command(params, include_executable=True)
    assert cmd[0] == "recon-all"
    assert "-subjid" in cmd
    assert "-all" in cmd
    assert "-i" in cmd
    assert "-hippocampal-subfields" in cmd
    assert "-brainstem-structures" in cmd
    assert "-parallel" in cmd
    assert "-openmp" in cmd
    assert cmd[-1] == "-noskullstrip"

    env = build_freesurfer_env(params)
    assert env["SUBJECTS_DIR"] == "/subjects"
    assert env["FS_LICENSE"] == "/licenses/fs_license.txt"
    assert env["OMP_NUM_THREADS"] == "8"
    assert env["FS_CUDA"] == "1"


def test_freesurfer_command_without_executable():
    params = FreeSurferReconAllParameters(
        subject_id="sub-02",
        subjects_dir="/subjects",
        t1_image="/data/t1.nii.gz",
    )

    cmd = build_freesurfer_command(params, include_executable=False)
    assert cmd[0] == "-all"
    assert "recon-all" not in cmd
