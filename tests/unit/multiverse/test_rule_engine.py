from brain_researcher.core.multiverse.rule_engine import generate_variants


def test_generate_variants_with_axis_overrides():
    variants = generate_variants(
        priors={},
        max_models=4,
        use_priors=False,
        seed=0,
        axis_overrides={
            "hrf_basis": ["canonical", "derivs", "glover", "fir"],
            "confounds": ["24mot"],
            "high_pass": ["100"],
        },
    )

    assert len(variants) == 4
    assert {v["hrf"] for v in variants} == {"canonical", "derivs", "glover", "fir"}
    assert {v["confounds"] for v in variants} == {"24mot"}
    assert {v["high_pass"] for v in variants} == {100}



def test_generate_variants_imply_physio_and_pupil_families_from_confounds_axis():
    variants = generate_variants(
        priors={},
        max_models=3,
        use_priors=False,
        seed=0,
        axis_overrides={
            "hrf_basis": ["canonical"],
            "confounds": ["24mot_physio_pupil"],
            "high_pass": ["128"],
        },
    )

    assert len(variants) == 1
    families = variants[0]["confounds_families"]
    assert families["confounds_motion_24"] is True
    assert families["confounds_physio"] is True
    assert families["confounds_pupil"] is True
