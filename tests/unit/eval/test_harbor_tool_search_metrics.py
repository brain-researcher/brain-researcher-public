from scripts.eval.harbor_tool_search_metrics import _gold_tools_for_task, _task_id


def _task(*, title: str, category: str, instruction: str = "") -> dict:
    return {
        "title": title,
        "category": category,
        "instruction": instruction,
    }


def _row(*caps: str, task_category: str) -> dict[str, str]:
    return {
        "expected_capability_list": str(list(caps)),
        "expected_capability": "; ".join(caps),
        "task_category": task_category,
    }


def test_gold_mapping_recognizes_denoising_tools() -> None:
    task = _task(
        title="Preprocess ADHD-200 resting-state with ICA-AROMA denoising",
        category="Preprocessing",
    )
    row = _row("fmriprep_tool", "ica_aroma_tool", task_category="Preprocessing")

    gold = _gold_tools_for_task(task, row)

    assert "fsl_fix" in gold
    assert "fsl_melodic" in gold
    assert "workflow_fmriprep_preprocessing" in gold


def test_gold_mapping_recognizes_compcor_and_qc_timeseries_tools() -> None:
    task = _task(
        title="Run scrubbing to remove high-motion volumes from ABIDE data",
        category="Specialized Processing",
    )
    row = _row(
        "specialized_processing_tool",
        "connectivity_tool",
        task_category="Specialized Processing",
    )

    gold = _gold_tools_for_task(task, row)

    assert "workflow_preprocessing_qc" in gold
    assert "workflow_mriqc" in gold
    assert "motion_quantification" in gold


def test_gold_mapping_recognizes_tedana_tools() -> None:
    task = _task(
        title="Apply TEDANA multi-echo denoising to separate BOLD from non-BOLD signals",
        category="Specialized Processing",
    )
    row = _row("specialized_processing_tool", "tedana", task_category="Specialized Processing")

    gold = _gold_tools_for_task(task, row)

    assert "afni.24.2.06.tedana_wrapper.py.run" in gold
    assert "workflow_fmriprep_preprocessing" in gold


def test_gold_mapping_recognizes_lesion_detection_tools() -> None:
    task = _task(
        title="Segment lesions from stroke patient data using automated detection",
        category="Segmentation",
    )
    row = _row("lesion_detection_tool", "automated_segmentation", task_category="Segmentation")

    gold = _gold_tools_for_task(task, row)

    assert "lesion_detection" in gold


def test_gold_mapping_recognizes_randomise_tools() -> None:
    task = _task(
        title="Perform cluster-extent threshold with FSL randomise on ABIDE",
        category="Statistical Analysis",
    )
    row = _row("fsl_randomise_tool", "permutation_test", task_category="Statistical Analysis")

    gold = _gold_tools_for_task(task, row)

    assert "fsl_palm" in gold
    assert "multiple_comparison_correction" in gold


def test_task_id_prefers_task_id_and_falls_back_to_harbor_id() -> None:
    assert _task_id({"task_id": "REG-001", "id": "OTHER"}) == "REG-001"
    assert _task_id({"id": "OPENNEURO-ML-005"}) == "OPENNEURO-ML-005"
