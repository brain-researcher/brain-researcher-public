from brain_researcher.services.tools.fitlins_tool import (
    FitLinsTool,
    _apply_hrf_variant,
    _base_confounds_families,
    _extract_fitlins_params,
)


def test_apply_hrf_variant_glover_clears_fir_fields():
    run_node = {
        "Transformations": {
            "Instructions": [
                {
                    "Name": "Convolve",
                    "Model": "fir",
                    "Derivative": True,
                    "Dispersion": True,
                    "FirDelays": [0, 2, 4],
                    "Window": 20,
                    "BinSize": 2,
                }
            ]
        }
    }

    _apply_hrf_variant(run_node, 0, "glover")
    step = run_node["Transformations"]["Instructions"][0]

    assert step["Model"] == "glover"
    assert step["Derivative"] is False
    assert step["Dispersion"] is False
    assert "FirDelays" not in step
    assert "Window" not in step
    assert "BinSize" not in step


def test_apply_hrf_variant_spm_time_dispersion_sets_derivative_and_dispersion():
    run_node = {
        "Transformations": {
            "Instructions": [
                {
                    "Name": "Convolve",
                    "Model": "spm",
                }
            ]
        }
    }

    _apply_hrf_variant(run_node, 0, "spm_time_dispersion")
    step = run_node["Transformations"]["Instructions"][0]

    assert step["Model"] == "spm"
    assert step["Derivative"] is True
    assert step["Dispersion"] is True


def test_fitlins_create_bids_model_normalizes_canonical_alias():
    model = FitLinsTool()._create_bids_model(
        bids_dir="/tmp/ds",
        hrf_model="canonical",
    )
    convolve = model["Nodes"][0]["Transformations"]["Instructions"][1]
    assert convolve["Model"] == "spm"



def test_fitlins_confound_strategy_includes_physio_and_pupil_terms():
    tool = FitLinsTool()

    physio = tool._get_confound_strategy("physio")
    pupil = tool._get_confound_strategy("pupil")
    full = tool._get_confound_strategy("full")

    assert "cardiac_retroicor_sin1" in physio
    assert "pupil_filtered_z" in pupil
    assert "pupil_blink_fraction" in full


def test_extract_fitlins_params_detects_physio_and_pupil_confounds():
    model = {
        "Nodes": [
            {
                "Level": "Run",
                "Model": {
                    "Type": "glm",
                    "X": [
                        "trial_type.condition1",
                        "cardiac_retroicor_sin1",
                        "pupil_filtered_z",
                        "motion_outlier01",
                    ],
                },
                "Transformations": {
                    "Instructions": [
                        {"Name": "Convolve", "Model": "spm"}
                    ]
                },
            }
        ]
    }

    params = _extract_fitlins_params(model)
    assert "cardiac_retroicor_sin1" in params["confounds_terms"]
    assert "pupil_filtered_z" in params["confounds_terms"]


def test_base_confounds_families_can_enable_physio_and_pupil_extensions():
    flags = _base_confounds_families("24mot_physio_pupil")

    assert flags["confounds_motion_6"] is True
    assert flags["confounds_motion_24"] is True
    assert flags["confounds_physio"] is True
    assert flags["confounds_pupil"] is True
