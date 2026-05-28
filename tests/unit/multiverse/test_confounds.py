from brain_researcher.core.multiverse.confounds import (
    confounds_families_to_patterns,
    extract_confounds_family_flags,
)


def test_confounds_family_flags_recognize_physio_and_pupil_terms():
    flags = extract_confounds_family_flags(
        [
            "cardiac_retroicor_sin1",
            "respiratory_signal_z",
            "pupil_filtered_z",
            "pupil_blink_fraction",
        ]
    )

    assert flags["confounds_physio"] is True
    assert flags["confounds_pupil"] is True

    patterns = confounds_families_to_patterns(flags)
    assert "cardiac_retroicor_*" in patterns
    assert "respiratory_signal_*" in patterns
    assert "pupil_filtered_z" in patterns
    assert "pupil_blink_fraction" in patterns
