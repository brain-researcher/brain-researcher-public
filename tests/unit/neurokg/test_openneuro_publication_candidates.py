from brain_researcher.services.neurokg.etl.loaders.openneuro_loader.publication_candidates import (
    RawPublicationCandidate,
    build_candidate_report,
    build_publication_seed,
    build_search_plans,
)


def test_build_publication_seed_dedupes_openneuro_dois() -> None:
    seed = build_publication_seed(
        kg_id="ds:openneuro:ds006661",
        label="Rapid decoding of neural information representation",
        properties={
            "dataset_id": "ds:openneuro:ds006661",
            "source_repo_id": "ds006661",
            "source_version": "doi:10.18112/openneuro.ds006661.v1.0.2",
            "primary_url": "https://doi.org/doi:10.18112/openneuro.ds006661.v1.0.2",
            "alias": ["ds006661"],
        },
    )

    assert seed.source_repo_id == "ds006661"
    assert seed.openneuro_dois == ("10.18112/openneuro.ds006661.v1.0.2",)


def test_build_search_plans_includes_required_strategies() -> None:
    seed = build_publication_seed(
        kg_id="ds:openneuro:ds001293",
        label="Multi-resolution 7T fMRI data on the representation of visual orientation",
        properties={
            "dataset_id": "ds:openneuro:ds001293",
            "source_repo_id": "ds001293",
            "alias": ["ds001293"],
        },
    )

    strategies = [plan.strategy for plan in build_search_plans(seed)]

    assert "exact_title_match" in strategies
    assert "legacy_openfmri_match" in strategies
    assert "related_descriptor" in strategies
    assert "related_analysis" in strategies


def test_build_candidate_report_merges_and_ranks_candidates() -> None:
    seed = build_publication_seed(
        kg_id="ds:openneuro:ds001293",
        label="Ultra high-field (7 T) multi-resolution fMRI data for orientation decoding in visual cortex",
        properties={
            "dataset_id": "ds:openneuro:ds001293",
            "source_repo_id": "ds001293",
            "alias": ["ds001293"],
        },
    )

    report = build_candidate_report(
        seed,
        {
            "exact_title_match": [
                RawPublicationCandidate(
                    title="Ultra high-field (7 T) multi-resolution fMRI data for orientation decoding in visual cortex",
                    doi="10.1016/j.dib.2017.05.014",
                    pmid="28616455",
                    pmcid=None,
                    year=2017,
                    journal="Data in Brief",
                    url="https://pubmed.ncbi.nlm.nih.gov/28616455/",
                    legacy_accession="ds000113c",
                    candidate_kind="exact_title_match",
                    match_confidence=0.97,
                    rationale="Exact title match to the dataset descriptor paper.",
                )
            ],
            "legacy_openfmri_match": [
                RawPublicationCandidate(
                    title="Ultra high-field (7 T) multi-resolution fMRI data for orientation decoding in visual cortex",
                    doi="10.1016/j.dib.2017.05.014",
                    pmid="28616455",
                    pmcid=None,
                    year=2017,
                    journal="Data in Brief",
                    url="https://openfmri.org/dataset/ds000113c/",
                    legacy_accession="ds000113c",
                    candidate_kind="legacy_openfmri_match",
                    match_confidence=0.76,
                    rationale="Legacy OpenfMRI accession points to the same dataset descriptor.",
                )
            ],
            "related_analysis": [
                RawPublicationCandidate(
                    title="The effect of acquisition resolution on orientation decoding from V1 BOLD fMRI at 7 T",
                    doi="10.1016/j.neuroimage.2016.11.004",
                    pmid=None,
                    pmcid=None,
                    year=2017,
                    journal="NeuroImage",
                    url="https://www.sciencedirect.com/science/article/pii/S1053811916307625",
                    legacy_accession=None,
                    candidate_kind="related_analysis",
                    match_confidence=0.68,
                    rationale="Likely downstream analysis paper on the same orientation-decoding data.",
                )
            ],
        },
    )

    assert report["summary"]["n_candidates"] == 2
    top = report["candidates"][0]
    assert top["doi"] == "10.1016/j.dib.2017.05.014"
    assert top["match_reasons"] == ["exact_title_match", "legacy_openfmri_match"]
    assert top["score"] > report["candidates"][1]["score"]
