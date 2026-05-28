from brain_researcher.core.multiverse.spec_family import generate_spec_family


def test_spec_family_deterministic_and_coverage():
    priors = {
        "hrf_basis": {"canonical": 0.6, "derivs": 0.4},
        "confounds": {"6mot": 0.5, "24mot": 0.5},
        "high_pass": {"100": 0.5, "128": 0.5},
        "confounds_acompcor": {"present": 0.5, "absent": 0.5},
    }

    specs_a = generate_spec_family(priors, k=6, seed=0)
    specs_b = generate_spec_family(priors, k=6, seed=0)

    assert [s["variant_id"] for s in specs_a] == [s["variant_id"] for s in specs_b]

    hrf = {s["decision_points"]["hrf_basis"] for s in specs_a}
    conf = {s["decision_points"]["confounds"] for s in specs_a}
    hp = {s["decision_points"]["high_pass"] for s in specs_a}

    assert "canonical" in hrf and "derivs" in hrf
    assert "6mot" in conf and "24mot" in conf
    assert 100 in hp and 128 in hp


def test_spec_family_axis_overrides_enforced():
    specs = generate_spec_family(
        {},
        k=4,
        seed=0,
        axis_overrides={
            "hrf_basis": ["canonical", "derivs", "glover", "fir"],
            "confounds": ["24mot"],
            "high_pass": ["100"],
        },
    )

    hrf = {s["decision_points"]["hrf_basis"] for s in specs}
    conf = {s["decision_points"]["confounds"] for s in specs}
    hp = {s["decision_points"]["high_pass"] for s in specs}

    assert hrf == {"canonical", "derivs", "glover", "fir"}
    assert conf == {"24mot"}
    assert hp == {100}


def test_spec_family_defaults_include_extended_hrf_basis():
    specs = generate_spec_family({}, k=4, seed=0)
    assert {s["decision_points"]["hrf_basis"] for s in specs} == {
        "canonical",
        "derivs",
        "glover",
        "fir",
    }



def test_spec_family_confounds_axis_can_cover_physio_and_pupil_modes():
    specs = generate_spec_family({}, k=9, seed=0)

    by_confounds = {s["decision_points"]["confounds"]: s["decision_points"] for s in specs}

    assert "24mot_physio" in by_confounds
    assert "24mot_pupil" in by_confounds
    assert "24mot_physio_pupil" in by_confounds
    assert by_confounds["24mot_physio"]["confounds_families"]["confounds_physio"] is True
    assert by_confounds["24mot_pupil"]["confounds_families"]["confounds_pupil"] is True
    assert by_confounds["24mot_physio_pupil"]["confounds_families"]["confounds_physio"] is True
    assert by_confounds["24mot_physio_pupil"]["confounds_families"]["confounds_pupil"] is True
