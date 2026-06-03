"""Build CodeReviewBundle instances from pipeline plans or run artifacts."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any

from brain_researcher.core.contracts.code_review import CodeReviewBundle
from brain_researcher.services.review.native_bundle_resolver import (
    load_json_artifact as _load_json_artifact,
)
from brain_researcher.services.review.native_bundle_resolver import (
    native_analysis_bundle as _native_analysis_bundle,
)
from brain_researcher.services.review.native_bundle_resolver import (
    native_analysis_manifest as _native_analysis_manifest,
)
from brain_researcher.services.review.native_bundle_resolver import (
    native_execution_manifest as _native_execution_manifest,
)
from brain_researcher.services.review.native_bundle_resolver import (
    native_observation as _native_observation,
)
from brain_researcher.services.review.native_bundle_resolver import (
    native_steps as _native_steps,
)
from brain_researcher.services.review.native_bundle_resolver import (
    resolve_ref_path as _resolve_ref_path,
)
from brain_researcher.services.review.native_review_contract import (
    build_native_review_contract,
)

_TASK_KEYS = ("task", "task_name", "task_label", "paradigm")
_CONTRAST_KEYS = ("contrast_name", "contrast_label", "contrast_id", "contrast")
_STUDY_KEYS = ("study_id", "dataset_id", "openneuro_dataset", "dataset")
_GLM_TOOLS = frozenset(
    {
        "glm_fit",
        "glm_first_level",
        "spm_glm",
        "nilearn_first_level_model",
        "glm_contrasts",
        "first_level_model",
        "fsl_feat",
        "fsl_film_gls",
        "fitlins",
    }
)
_TRIBE_PREDICTION_TOOLS = frozenset(
    {
        "tribe_predict",
    }
)
_EMBEDDING_ANALYSIS_TOOLS = frozenset(
    {
        "embedding_autoresearch",
    }
)
_FC_STATISTICAL_METHOD_ALIASES = {
    "ridge": "ridge",
    "ridge_regression": "ridge",
    "kernelridgelinear": "kernelridgelinear",
    "kernelridgecosine": "kernelridgecosine",
    "graph_transformer": "graph_transformer",
    "graphtransformer": "graph_transformer",
    "fttransformer": "fttransformer",
    "ft_transformer": "fttransformer",
    "brainnetcnn": "brainnetcnn",
    "mlp": "mlp",
    "svr": "svr",
    "xgboost": "xgboost",
    "lightgbm": "lightgbm",
    "cpm": "cpm",
    "elasticnet": "elasticnet",
    "pls": "pls",
    "tabnet": "tabnet",
    "tabpfn": "tabpfn",
    "gat": "gat",
    "gcn": "gcn",
    "set_transformer": "set_transformer",
    "perceiver": "perceiver",
    "spd_aware_transformer": "spd_aware_transformer",
    "mamba": "mamba",
}
_REPEATED_MEASURES_TOKENS = (
    "repeated_measures",
    "repeated measures",
    "within_subject",
    "within subject",
    "within-subject",
    "paired",
)
_INDEPENDENT_GROUPS_TOKENS = (
    "independent_samples",
    "independent samples",
    "independent",
    "between_subject",
    "between subject",
    "between-subject",
    "unpaired",
)
_ONE_SAMPLE_TOKENS = (
    "one_sample",
    "one-sample",
    "one sample",
    "single-group",
    "single group",
)
_FACTORIAL_TOKENS = (
    "factorial",
    "multi-factor",
    "two-way",
    "interaction design",
)
_MIXED_DESIGN_TOKENS = (
    "mixed design",
    "mixed_design",
    "split-plot",
    "mixed factorial",
    "between-within",
)
_LONGITUDINAL_TOKENS = (
    "longitudinal",
    "pre-post",
    "time-series design",
    "repeated assessment",
)
_CORRELATION_TOKENS = (
    "correlational",
    "cross-sectional correlation",
    "individual differences",
)
_PAIRED_TEST_TOOLS = frozenset(
    {
        "paired_ttest",
        "paired_test_tool",
        "scipy_ttest_rel",
        "ttest_rel",
        "ttest_paired",
        "pingouin_ttest_rel",
    }
)
_INDEPENDENT_TEST_TOOLS = frozenset(
    {
        "independent_ttest",
        "independent_test_tool",
        "scipy_ttest_ind",
        "ttest_ind",
        "ttest_independent",
        "pingouin_ttest_ind",
    }
)
_ONE_SAMPLE_TEST_TOOLS = frozenset(
    {
        "ttest_1samp",
        "scipy_ttest_1samp",
        "one_sample_ttest",
        "pingouin_ttest_1samp",
    }
)
_ANOVA_ONEWAY_TOOLS = frozenset(
    {
        "anova_oneway",
        "scipy_f_oneway",
        "pingouin_anova",
    }
)
_ANOVA_REPEATED_TOOLS = frozenset(
    {
        "rm_anova",
        "rmanova",
        "pingouin_rm_anova",
        "anova_repeated",
    }
)
_ANOVA_MIXED_TOOLS = frozenset(
    {
        "mixed_anova",
        "pingouin_mixed_anova",
        "anova_mixed",
    }
)
_MIXED_EFFECTS_TOOLS = frozenset(
    {
        "lmer",
        "mixed_effects",
        "lme",
        "multilevel_model",
        "linear_mixed_model",
    }
)
_CORRELATION_TOOLS = frozenset(
    {
        "pearsonr",
        "scipy_pearsonr",
        "correlation_pearson",
        "pearson_correlation",
    }
)
_MANN_WHITNEY_TOOLS = frozenset(
    {
        "mannwhitneyu",
        "scipy_mannwhitneyu",
        "mann_whitney",
    }
)
_WILCOXON_TOOLS = frozenset(
    {
        "wilcoxon",
        "scipy_wilcoxon",
        "wilcoxon_signed_rank",
    }
)
_NATIVE_OBSERVED_ARTIFACT_FIELDS = (
    ("research_episode", "research_episode_json"),
    ("option_set", "option_set_json"),
    ("evidence_gate", "evidence_gate_json"),
    ("commitment", "commitment_json"),
    ("claim_report", "claim_report_json"),
    ("claim_update", "claim_update_json"),
)


def _first_string_param(
    plan_steps: list[dict[str, Any]],
    keys: tuple[str, ...],
) -> str | None:
    for step in plan_steps:
        params = step.get("params") if isinstance(step.get("params"), dict) else {}
        for key in keys:
            val = params.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def _build_kg_context(plan_steps: list[dict[str, Any]]) -> dict[str, Any]:
    kg_context: dict[str, Any] = {}
    if task := _first_string_param(plan_steps, _TASK_KEYS):
        kg_context["task"] = task
    if contrast := _first_string_param(plan_steps, _CONTRAST_KEYS):
        kg_context["contrast"] = contrast
    if study_id := _first_string_param(plan_steps, _STUDY_KEYS):
        kg_context["study_id"] = study_id
    if analysis_family := _infer_analysis_family(plan_steps):
        kg_context["analysis_family"] = analysis_family
    if design_type := _infer_design_type(plan_steps):
        kg_context["design_type"] = design_type
    if statistical_method := _infer_statistical_method(plan_steps):
        kg_context["statistical_method"] = statistical_method
    return kg_context


def _infer_analysis_family(plan_steps: list[dict[str, Any]]) -> str | None:
    for step in plan_steps:
        tool = str(step.get("tool") or "").lower()
        if tool in _GLM_TOOLS:
            return "glm"
        if tool in _TRIBE_PREDICTION_TOOLS:
            return "tribe_prediction"
        if tool in _EMBEDDING_ANALYSIS_TOOLS:
            return "embedding_analysis"
    return None


def _step_param_text(step: dict[str, Any]) -> list[str]:
    params = step.get("params") if isinstance(step.get("params"), dict) else {}
    values: list[str] = []
    for value in params.values():
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
        elif isinstance(value, bool):
            values.append("true" if value else "false")
    return values


def _extract_review_context(source: Any) -> dict[str, Any]:
    """Return the first nested review_context found in a source object."""
    base: dict[str, Any] = {}
    if isinstance(source, dict):
        review_context = source.get("review_context")
        if isinstance(review_context, dict):
            base = dict(review_context)
        else:
            for key in ("review_contract", "analysis_bundle", "run_card"):
                nested = source.get(key)
                if isinstance(nested, dict):
                    extracted = _extract_review_context(nested)
                    if extracted:
                        base = extracted
                        break

        feature_contract = source.get("feature_contract")
        if isinstance(feature_contract, dict) and feature_contract:
            existing = base.get("feature_contract")
            merged = dict(existing) if isinstance(existing, dict) else {}
            merged.update(feature_contract)
            base["feature_contract"] = merged

        value_domain_diagnostics = source.get("value_domain_diagnostics")
        if isinstance(value_domain_diagnostics, list) and value_domain_diagnostics:
            existing_vd = base.get("value_domain_diagnostics")
            merged_vd = list(existing_vd) if isinstance(existing_vd, list) else []
            merged_vd.extend(
                item for item in value_domain_diagnostics if isinstance(item, dict)
            )
            base["value_domain_diagnostics"] = merged_vd

        probes = source.get("review_probes")
        if isinstance(probes, dict) and probes:
            existing_probes = base.get("review_probes")
            merged_probes = (
                dict(existing_probes) if isinstance(existing_probes, dict) else {}
            )
            merged_probes.update(probes)
            base["review_probes"] = merged_probes
            label_probe = probes.get("label_permutation_null")
            if isinstance(label_probe, dict) and label_probe:
                null_section = base.get("null_model")
                null_section = (
                    dict(null_section) if isinstance(null_section, dict) else {}
                )
                null_section.setdefault("permutation_null", label_probe)
                base["null_model"] = null_section
        return base

    review_context = getattr(source, "review_context", None)
    if isinstance(review_context, dict):
        return dict(review_context)
    run_card = getattr(source, "run_card", None)
    if isinstance(run_card, dict):
        extracted = _extract_review_context(run_card)
        if extracted:
            return extracted
    return {}


_FULL_PIPELINE_SCOPE_VALUES = frozenset(
    {
        "full_pipeline",
        "whole_pipeline",
        "end_to_end",
        "entire_pipeline",
        "pipeline",
    }
)
_TRUSTED_FULL_PIPELINE_PERMUTATION_GENERATORS = frozenset(
    {
        "br_full_pipeline_permutation_harness",
        "br.workflow.full_pipeline_permutation_harness",
    }
)
_TRUSTED_FULL_PIPELINE_INPUT_SCOPES = frozenset(
    {
        "raw_inputs",
        "workflow_invocation",
        "full_pipeline",
    }
)
_PIPELINE_INVOCATION_DIGEST_KEYS = (
    "pipeline_invocation_sha256",
    "workflow_invocation_sha256",
    "raw_input_manifest_sha256",
)


def _is_trusted_full_pipeline_label_probe(probe: dict[str, Any]) -> bool:
    pipeline_scope = str(probe.get("pipeline_scope") or "").strip().lower()
    generated_by = str(probe.get("generated_by") or "").strip().lower()
    input_scope = str(probe.get("input_scope") or "").strip().lower()
    return (
        pipeline_scope in _FULL_PIPELINE_SCOPE_VALUES
        and generated_by in _TRUSTED_FULL_PIPELINE_PERMUTATION_GENERATORS
        and input_scope in _TRUSTED_FULL_PIPELINE_INPUT_SCOPES
        and any(
            bool(str(probe.get(key) or "").strip())
            for key in _PIPELINE_INVOCATION_DIGEST_KEYS
        )
    )


def _label_probe_sort_key(probe: dict[str, Any]) -> tuple[int, int]:
    return (
        int(_is_trusted_full_pipeline_label_probe(probe)),
        int(probe.get("n_permutations", 0) or 0),
    )


def _discover_review_sidecars(run_dir: Path) -> dict[str, Any]:
    """Walk a run directory for review sidecar files emitted by tools."""

    discovered: dict[str, Any] = {}
    if not run_dir.exists():
        return discovered

    feature_contracts: list[dict[str, Any]] = []
    label_probes: list[dict[str, Any]] = []
    value_domain_diagnostics: list[dict[str, Any]] = []
    for candidate in run_dir.rglob("feature_contract.json"):
        payload = _load_json_artifact(candidate)
        if isinstance(payload, dict):
            feature_contracts.append(payload)
    for candidate in run_dir.rglob("label_permutation_null.json"):
        if "review_probes" not in candidate.parts:
            continue
        payload = _load_json_artifact(candidate)
        if isinstance(payload, dict):
            label_probes.append(payload)
    for candidate in run_dir.rglob("value_domain_diagnostics.json"):
        payload = _load_json_artifact(candidate)
        entries = (
            payload
            if isinstance(payload, list)
            else payload.get("value_domain_diagnostics")
            if isinstance(payload, dict)
            else None
        )
        if isinstance(entries, list):
            value_domain_diagnostics.extend(
                item for item in entries if isinstance(item, dict)
            )

    if feature_contracts:
        discovered["feature_contract"] = feature_contracts[0]
        if len(feature_contracts) > 1:
            discovered["feature_contracts"] = feature_contracts
    if label_probes:
        best = max(label_probes, key=_label_probe_sort_key)
        discovered["review_probes"] = {"label_permutation_null": best}
    if value_domain_diagnostics:
        discovered["value_domain_diagnostics"] = value_domain_diagnostics
    return discovered


def _infer_design_type(plan_steps: list[dict[str, Any]]) -> str | None:
    for step in plan_steps:
        params = step.get("params") if isinstance(step.get("params"), dict) else {}
        tool = str(step.get("tool") or "").lower()
        texts = [tool, *(_step_param_text(step))]

        # Explicit boolean params.
        if any(
            bool(params.get(key))
            for key in ("within_subject", "within_subjects", "repeated_measures")
        ):
            return "repeated_measures"
        if any(
            bool(params.get(key))
            for key in ("between_subject", "between_subjects", "independent_groups")
        ):
            return "independent_groups"
        if bool(params.get("one_sample")):
            return "one_sample"
        if bool(params.get("factorial")):
            return "factorial"
        if bool(params.get("mixed_design")):
            return "mixed_design"
        if bool(params.get("longitudinal")):
            return "longitudinal"
        if bool(params.get("correlation")):
            return "correlation"

        # Explicit design_type param.
        explicit = params.get("design_type") or params.get("design")
        if isinstance(explicit, str) and explicit.strip():
            explicit_norm = explicit.strip().lower()
            for canonical, tokens in (
                ("repeated_measures", _REPEATED_MEASURES_TOKENS),
                ("independent_groups", _INDEPENDENT_GROUPS_TOKENS),
                ("one_sample", _ONE_SAMPLE_TOKENS),
                ("factorial", _FACTORIAL_TOKENS),
                ("mixed_design", _MIXED_DESIGN_TOKENS),
                ("longitudinal", _LONGITUDINAL_TOKENS),
                ("correlation", _CORRELATION_TOKENS),
            ):
                if (
                    any(token in explicit_norm for token in tokens)
                    or explicit_norm == canonical
                ):
                    return canonical

        # Text matching.
        joined = " ".join(texts).lower()
        for canonical, tokens in (
            ("repeated_measures", _REPEATED_MEASURES_TOKENS),
            ("independent_groups", _INDEPENDENT_GROUPS_TOKENS),
            ("one_sample", _ONE_SAMPLE_TOKENS),
            ("factorial", _FACTORIAL_TOKENS),
            ("mixed_design", _MIXED_DESIGN_TOKENS),
            ("longitudinal", _LONGITUDINAL_TOKENS),
            ("correlation", _CORRELATION_TOKENS),
        ):
            if any(token in joined for token in tokens):
                return canonical
    return None


def _infer_statistical_method(plan_steps: list[dict[str, Any]]) -> str | None:
    _METHOD_TOOL_MAP: list[tuple[str, frozenset[str]]] = [
        ("paired_t_test", _PAIRED_TEST_TOOLS),
        ("independent_t_test", _INDEPENDENT_TEST_TOOLS),
        ("one_sample_t_test", _ONE_SAMPLE_TEST_TOOLS),
        ("anova_oneway", _ANOVA_ONEWAY_TOOLS),
        ("anova_repeated", _ANOVA_REPEATED_TOOLS),
        ("anova_mixed", _ANOVA_MIXED_TOOLS),
        ("mixed_effects_model", _MIXED_EFFECTS_TOOLS),
        ("correlation_pearson", _CORRELATION_TOOLS),
        ("mann_whitney", _MANN_WHITNEY_TOOLS),
        ("wilcoxon_signed_rank", _WILCOXON_TOOLS),
    ]

    _METHOD_TEXT_HINTS: list[tuple[str, tuple[str, ...]]] = [
        (
            "paired_t_test",
            ("paired t-test", "paired t test", "ttest_rel", "dependent t-test"),
        ),
        (
            "independent_t_test",
            (
                "independent-samples t-test",
                "independent t-test",
                "ttest_ind",
                "independent samples t test",
                "unpaired t-test",
            ),
        ),
        (
            "one_sample_t_test",
            ("one-sample t-test", "one sample t test", "ttest_1samp"),
        ),
        (
            "anova_oneway",
            (
                "one-way anova",
                "oneway_anova",
            ),
        ),
        ("anova_repeated", ("repeated-measures anova", "rm_anova", "rmanova")),
        (
            "anova_mixed",
            (
                "mixed anova",
                "mixed-model anova",
            ),
        ),
        (
            "mixed_effects_model",
            ("linear mixed model", "mixed effects", "lmer", "multilevel model"),
        ),
        (
            "correlation_pearson",
            ("pearson correlation", "pearson_r", "bivariate correlation"),
        ),
        (
            "mann_whitney",
            ("mann-whitney", "mann whitney", "wilcoxon rank-sum", "mannwhitneyu"),
        ),
        (
            "wilcoxon_signed_rank",
            (
                "wilcoxon signed rank",
                "wilcoxon signed-rank",
            ),
        ),
        (
            "permutation_test",
            ("permutation test", "randomization test", "nonparametric permutation"),
        ),
        (
            "linear_regression",
            (
                "linear regression",
                "linear model",
                "ols",
            ),
        ),
        (
            "neural_encoding_prediction",
            ("tribe_predict", "neural encoding", "encoding prediction"),
        ),
        (
            "embedding_autoresearch",
            ("embedding_autoresearch", "embedding analysis", "autoresearch"),
        ),
    ]

    for step in plan_steps:
        params = step.get("params") if isinstance(step.get("params"), dict) else {}
        tool = str(step.get("tool") or "").lower()
        texts = [tool, *(_step_param_text(step))]

        # 1. Explicit param.
        explicit = (
            params.get("statistical_method")
            or params.get("test_type")
            or params.get("method")
        )
        if isinstance(explicit, str) and explicit.strip():
            explicit_norm = explicit.strip().lower().replace("-", "_").replace(" ", "_")
            if explicit_norm in _FC_STATISTICAL_METHOD_ALIASES:
                return _FC_STATISTICAL_METHOD_ALIASES[explicit_norm]
            for canonical, hints in _METHOD_TEXT_HINTS:
                if explicit_norm == canonical or any(h in explicit_norm for h in hints):
                    return canonical

        # 2. Tool name.
        if tool:
            for canonical, tool_set in _METHOD_TOOL_MAP:
                if tool in tool_set:
                    return canonical

        # 3. Text matching.
        joined = " ".join(texts).lower()
        for canonical, hints in _METHOD_TEXT_HINTS:
            if any(h in joined for h in hints):
                return canonical
    return None


def build_plan_review_bundle(
    plan: Any,
    *,
    workflow_id: str | None = None,
    run_id: str | None = None,
) -> CodeReviewBundle:
    """Build a CodeReviewBundle from a Plan (PlanStep dataclass list).

    Args:
        plan: A Plan dataclass instance with a ``steps`` attribute (list of PlanStep).
        workflow_id: Optional workflow identifier for context.
        run_id: Optional run identifier for traceability.

    Returns:
        CodeReviewBundle with plan_steps, declared_modalities, declared_spaces populated.
    """
    steps_raw = getattr(plan, "steps", None) or []

    plan_steps: list[dict[str, Any]] = []
    declared_modalities: list[str] = []
    declared_spaces: list[str] = []

    for step in steps_raw:
        # Convert dataclass to dict if needed
        if hasattr(step, "__dataclass_fields__"):
            step_dict = {f.name: getattr(step, f.name) for f in fields(step)}
        elif isinstance(step, dict):
            step_dict = dict(step)
        else:
            step_dict = {"tool": str(step), "params": {}, "step_id": None}

        tool = step_dict.get("tool") or ""
        params = step_dict.get("params") or {}
        step_id = step_dict.get("step_id")

        plan_steps.append({"tool": tool, "params": params, "step_id": step_id})

        # Extract modality hints from params
        for key in ("modality", "modalities"):
            val = params.get(key)
            if isinstance(val, str) and val:
                declared_modalities.append(val)
            elif isinstance(val, list):
                declared_modalities.extend(str(v) for v in val if v)

        # Extract space hints from params
        for key in ("space", "spaces", "target_space", "atlas_space"):
            val = params.get(key)
            if isinstance(val, str) and val:
                declared_spaces.append(val)
            elif isinstance(val, list):
                declared_spaces.extend(str(v) for v in val if v)

    return CodeReviewBundle(
        plan_steps=plan_steps,
        declared_modalities=list(dict.fromkeys(m.lower() for m in declared_modalities)),
        declared_spaces=list(dict.fromkeys(declared_spaces)),
        workflow_id=workflow_id,
        run_id=run_id,
        review_context=_extract_review_context(plan),
        kg_context=_build_kg_context(plan_steps),
    )


def build_artifact_review_bundle(
    run_id: str,
    *,
    run_dir: Path | None = None,
    workflow_id: str | None = None,
) -> CodeReviewBundle:
    """Build a CodeReviewBundle from a completed run directory (post-execution).

    Reads domain stats from output files (confounds, GLM summaries, QC reports)
    and infra-level signals from run.json. Contains no agent CoT.

    Args:
        run_id: The run identifier.
        run_dir: Explicit path to the run directory. Resolved automatically if None.
        workflow_id: Optional workflow identifier for context.

    Returns:
        CodeReviewBundle with stats_metrics and scorecard_snapshot populated.
    """
    from brain_researcher.services.memory.distill import (
        _find_run_dir,  # reuse existing resolver
    )
    from brain_researcher.services.review.stats_extractor import (
        _extract_scorecard_snapshot,
        extract_stats_from_run_dir,
    )

    resolved_run_dir = _find_run_dir(run_id, run_dir=run_dir)
    stats_metrics = extract_stats_from_run_dir(resolved_run_dir)
    scorecard_snapshot = _extract_scorecard_snapshot(resolved_run_dir)

    # Extract plan steps from run.json tool_sequence if present
    plan_steps = _plan_steps_from_run_json(resolved_run_dir)
    observed_artifacts = _observed_artifacts_from_run_dir(resolved_run_dir)

    return CodeReviewBundle(
        plan_steps=plan_steps,
        workflow_id=workflow_id,
        run_id=run_id,
        review_context=_extract_review_context(observed_artifacts),
        observed_artifacts=observed_artifacts,
        stats_metrics=stats_metrics,
        scorecard_snapshot=scorecard_snapshot,
        kg_context=_build_kg_context(plan_steps),
    )


def _plan_steps_from_run_json(run_dir: Path) -> list[dict[str, Any]]:
    """Extract tool sequence from run.json as minimal plan_steps."""
    run_path = run_dir / "run.json"
    if not run_path.exists():
        return _plan_steps_from_native_bundle(run_dir)
    try:
        data = json.loads(run_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _plan_steps_from_native_bundle(run_dir)
        steps = data.get("steps") if isinstance(data.get("steps"), list) else []
        normalized = [
            {
                "tool": str(s.get("tool_id") or s.get("tool") or ""),
                "params": s.get("params") or {},
                "step_id": s.get("step_id"),
            }
            for s in steps
            if isinstance(s, dict)
        ]
        return normalized or _plan_steps_from_native_bundle(run_dir)
    except Exception:
        return _plan_steps_from_native_bundle(run_dir)


def _plan_steps_from_native_bundle(run_dir: Path) -> list[dict[str, Any]]:
    bundle = _native_analysis_bundle(run_dir)
    normalized: list[dict[str, Any]] = []
    for step in _native_steps(run_dir, bundle):
        normalized.append(
            {
                "tool": str(step.get("tool_id") or step.get("tool") or ""),
                "params": step.get("params") or {},
                "step_id": step.get("step_id"),
            }
        )
    return normalized


def _observed_artifacts_from_run_dir(run_dir: Path) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    sidecars = _discover_review_sidecars(run_dir)
    if sidecars:
        observed.update(sidecars)
    run_json = _load_json_artifact(run_dir / "run.json")
    run_json = run_json if isinstance(run_json, dict) else {}
    bundle = _native_analysis_bundle(run_dir)
    observation = _native_observation(run_dir, bundle) if bundle else {}
    if bundle:
        observed["analysis_bundle"] = bundle
        if isinstance(bundle.get("review_context"), dict):
            observed["review_context"] = dict(bundle["review_context"])
        if observation:
            observed["observation"] = observation
        execution_manifest = _native_execution_manifest(run_dir, bundle)
        if execution_manifest:
            observed["execution_manifest"] = execution_manifest
        source_summary = _native_analysis_manifest(run_dir, bundle)
        if source_summary:
            observed["source_summary"] = source_summary
        if isinstance(bundle.get("provenance"), dict):
            observed["provenance"] = bundle["provenance"]
        files = bundle.get("files") if isinstance(bundle.get("files"), dict) else {}
        for logical_name, field_name in _NATIVE_OBSERVED_ARTIFACT_FIELDS:
            rel = files.get(field_name)
            if not isinstance(rel, str) or not rel.strip():
                continue
            payload = _load_json_artifact(_resolve_ref_path(run_dir, rel))
            if payload is not None:
                observed[logical_name] = payload
        observed["review_contract"] = build_native_review_contract(
            bundle,
            observation=observation,
            execution_manifest=execution_manifest,
        )
        review_contract = observed.get("review_contract")
        if isinstance(review_contract, dict):
            review_context = review_contract.get("review_context")
            if isinstance(review_context, dict):
                observed["review_context"] = dict(review_context)

    if isinstance(run_json.get("review_contract"), dict):
        observed["review_contract"] = run_json["review_contract"]
        review_context = run_json["review_contract"].get("review_context")
        if isinstance(review_context, dict):
            observed["review_context"] = dict(review_context)

    if isinstance(run_json.get("review_context"), dict):
        observed["review_context"] = dict(run_json["review_context"])

    legacy_external_mode = (
        observed.get("review_contract", {}).get("contract_mode")
        == "external_review_bundle"
        if isinstance(observed.get("review_contract"), dict)
        else False
    )

    fallback_artifacts = (
        "analysis_bundle.json",
        "quote_grounded_claims.json",
        "quote_grounded_evidence_items.json",
    )
    if legacy_external_mode or not bundle:
        fallback_artifacts = (
            "source_summary.json",
            "extraction_report.json",
            *fallback_artifacts,
            "research_episode.json",
            "option_set.json",
            "evidence_gate.json",
            "commitment.json",
            "claim_report.json",
            "claim_update.json",
        )

    for name in fallback_artifacts:
        key = name.removesuffix(".json")
        if key in observed:
            continue
        payload = _load_json_artifact(run_dir / name)
        if payload is not None:
            observed[key] = payload
    return observed
