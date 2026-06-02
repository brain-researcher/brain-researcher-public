from brain_researcher.services.br_kg.vector_search import VectorSearchEngine


def _engine_stub():
    return VectorSearchEngine.__new__(VectorSearchEngine)


def test_text_template_taskspec_includes_fields():
    engine = _engine_stub()
    text = engine._create_text_representation(
        "TaskSpec",
        {
            "name": "confounds_aroma",
            "aliases": ["ICA-AROMA"],
            "description": "ICA-based denoising",
            "task_family": "denoising",
            "modality": "fMRI",
        },
    )
    assert "TaskSpec" in text
    assert "confounds_aroma" in text
    assert "ICA-AROMA" in text
    assert "denoising" in text
    assert "fMRI" in text


def test_text_template_tool_includes_keywords():
    engine = _engine_stub()
    text = engine._create_text_representation(
        "Tool",
        {
            "name": "fMRIPrep",
            "category": "pipeline",
            "keywords": ["confounds", "smoothing"],
        },
    )
    assert "Tool" in text
    assert "fMRIPrep" in text
    assert "pipeline" in text
    assert "confounds" in text
