"""Modality execution-plan builders for the BR-KG agent web service.

Carved out of ``agent/web_service.py``: the per-modality plan builders
(connectivity fMRI/EEG/iEEG, dMRI connectome, sMRI morphometry, PET SUVR,
meta term-map, KG ingest-validate, demo) plus the ``_build_plan_for_request``
dispatcher and ``_build_plan_routing_diagnostics``.

The plan/step/artifact types are imported directly from ``planner.models``.
The few web_service helpers these builders need (``_load_stub_steps`` /
``_maybe_add_resolvers`` / ``_plan_context_from_request`` / ``_register_plan``)
stay in ``web_service`` and are imported back lazily inside the consuming
builders, so the dependency is one-way ``web_service -> plan_builders`` and
cycle-free at module load. ``web_service`` re-exports every name below so its
``agent_plan_contract`` route (which calls the dispatcher + diagnostics) and the
tests that patch/call them keep resolving.
"""

from __future__ import annotations

import uuid
from typing import Any

from brain_researcher.services.agent.planner.models import (
    ArtifactSpec,
    Plan,
    PlanDAG,
    PlanRequest,
    StepSpec,
)


def _build_plan_routing_diagnostics(
    *,
    candidate_rows: list[dict[str, Any]] | None,
    chosen_tool: str | None,
    preflight_tool_candidate_diagnostics: dict[str, Any] | None = None,
    routing_latency_ms: float | None = None,
) -> dict[str, Any]:
    """Normalize plan-side routing diagnostics to the shared tool-candidate schema."""

    preflight_diagnostics = dict(preflight_tool_candidate_diagnostics or {})
    candidate_rows = list(candidate_rows or [])

    preflight_candidate_source_counts: dict[str, int] = dict(
        preflight_diagnostics.get("candidate_source_counts") or {}
    )
    preflight_candidate_count = int(preflight_diagnostics.get("candidate_count") or 0)

    planner_candidate_source_counts: dict[str, int] = {}
    selected_tool_rank = None
    for idx, row in enumerate(candidate_rows, start=1):
        if not isinstance(row, dict):
            continue
        source = str(row.get("source") or "catalog")
        planner_candidate_source_counts[source] = (
            planner_candidate_source_counts.get(source, 0) + 1
        )
        if chosen_tool and row.get("tool_id") == chosen_tool:
            selected_tool_rank = idx

    def _source_label(
        source_counts: dict[str, int],
        fallback: str | None = None,
    ) -> str | None:
        if len(source_counts) == 1:
            return next(iter(source_counts.keys()))
        if source_counts:
            return "mixed"
        return fallback

    diagnostics = {
        key: value
        for key, value in preflight_diagnostics.items()
        if key
        not in {
            "candidate_count",
            "candidate_source_counts",
            "candidate_source",
            "selected_tool_rank",
            "selected_tool_in_top_5",
            "selected_tool_in_top_10",
            "routing_terminal_reason",
        }
    }

    planner_candidate_count = len(candidate_rows)
    diagnostics["surface"] = "plan"
    diagnostics["preflight_candidate_count"] = preflight_candidate_count
    diagnostics["preflight_candidate_source_counts"] = preflight_candidate_source_counts
    diagnostics["preflight_candidate_source"] = _source_label(
        preflight_candidate_source_counts,
        str(preflight_diagnostics.get("candidate_source") or "") or None,
    )
    diagnostics["planner_candidate_count"] = planner_candidate_count
    diagnostics["planner_candidate_source_counts"] = planner_candidate_source_counts
    diagnostics["planner_candidate_source"] = _source_label(
        planner_candidate_source_counts
    )
    diagnostics["candidate_count"] = planner_candidate_count
    diagnostics["candidate_source_counts"] = planner_candidate_source_counts
    diagnostics["candidate_source"] = diagnostics["planner_candidate_source"]
    diagnostics["selected_tool_rank"] = selected_tool_rank
    diagnostics["selected_tool_in_top_5"] = (
        selected_tool_rank is not None and selected_tool_rank <= 5
    )
    diagnostics["selected_tool_in_top_10"] = (
        selected_tool_rank is not None and selected_tool_rank <= 10
    )
    if not chosen_tool:
        if planner_candidate_count > 0:
            diagnostics.setdefault(
                "routing_terminal_reason", "plan_returned_without_tool_choice"
            )
        elif preflight_candidate_count > 0:
            diagnostics.setdefault(
                "routing_terminal_reason",
                "preflight_candidates_not_promoted_to_plan",
            )
        else:
            diagnostics.setdefault(
                "routing_terminal_reason", "planner_returned_no_candidates"
            )
    if routing_latency_ms is not None:
        diagnostics["routing_latency_ms"] = routing_latency_ms

    return diagnostics


def _build_connectivity_plan_fmri(plan_request: PlanRequest) -> Plan:
    from brain_researcher.services.agent.web_service import (
        _load_stub_steps,
        _plan_context_from_request,
        _register_plan,
    )

    steps = list(_load_stub_steps().values())
    artifacts = [
        ArtifactSpec(
            name="atlas_path", rtype="parcellation_labels", description="Atlas path"
        ),
        ArtifactSpec(
            name="timeseries",
            rtype="timeseries",
            description="Extracted ROI time-series",
        ),
        ArtifactSpec(
            name="connectivity_matrix",
            rtype="connectivity_matrix",
            description="Connectivity matrix",
        ),
    ]

    plan_id = f"plan_{uuid.uuid4().hex[:8]}"
    dag = PlanDAG(steps=steps, artifacts=artifacts)
    estimates = {"duration_s": 60.0, "cost_units": 0.5}

    plan = Plan(
        plan_id=plan_id,
        version=1,
        domain=plan_request.domain,
        modality=plan_request.modality,
        resolvable=True,
        dag=dag,
        estimates=estimates,
        warnings=[],
        constraints=plan_request.constraints,
    )
    _register_plan(plan, context=_plan_context_from_request(plan_request))
    return plan


def _build_connectivity_plan_eeg(plan_request: PlanRequest) -> Plan:
    from brain_researcher.services.agent.web_service import (
        _plan_context_from_request,
        _register_plan,
    )

    inputs = dict(plan_request.inputs)
    inputs.setdefault("raw_eeg", "sub-01_task-rest_eeg.fif")
    inputs.setdefault("montage_name", "standard_1020")
    plan_request = plan_request.model_copy(update={"inputs": inputs})

    steps = [
        StepSpec(
            id="eeg_s1",
            tool="resolve_montage",
            consumes={"montage_name": "montage_name"},
            produces={"montage_def": "montage_def"},
            params={"montage_name": inputs["montage_name"]},
        ),
        StepSpec(
            id="eeg_s2",
            tool="eeg_preprocess",
            consumes={"raw_eeg": "raw_eeg", "montage": "montage_def"},
            produces={"clean_eeg": "clean_eeg"},
        ),
        StepSpec(
            id="eeg_s3",
            tool="epoch_events",
            consumes={"clean_eeg": "clean_eeg"},
            produces={"epochs": "epochs"},
        ),
        StepSpec(
            id="eeg_s4",
            tool="timefreq_tfr",
            consumes={"epochs": "epochs"},
            produces={"power_spectra": "power_spectra"},
        ),
        StepSpec(
            id="eeg_s5",
            tool="connectivity_measures",
            consumes={"epochs": "epochs"},
            produces={"connectivity_matrix": "connectivity_matrix"},
        ),
    ]

    artifacts = [
        ArtifactSpec(
            name="montage_def", rtype="montage", description="Resolved montage"
        ),
        ArtifactSpec(
            name="clean_eeg", rtype="clean_eeg", description="Band-pass filtered EEG"
        ),
        ArtifactSpec(name="epochs", rtype="epochs", description="Event-aligned epochs"),
        ArtifactSpec(
            name="power_spectra",
            rtype="power_spectra",
            description="Time-frequency power",
        ),
        ArtifactSpec(
            name="connectivity_matrix",
            rtype="connectivity_matrix",
            description="Connectivity matrix",
        ),
    ]

    plan_id = f"plan_{uuid.uuid4().hex[:8]}"
    dag = PlanDAG(steps=steps, artifacts=artifacts)
    estimates = {"duration_s": 120.0, "cost_units": 0.8}

    plan = Plan(
        plan_id=plan_id,
        version=1,
        domain=plan_request.domain,
        modality=plan_request.modality,
        resolvable=True,
        dag=dag,
        estimates=estimates,
        warnings=[],
        constraints=plan_request.constraints,
    )
    _register_plan(plan, context=_plan_context_from_request(plan_request))
    return plan


def _build_connectivity_plan_meg(plan_request: PlanRequest) -> Plan:
    from brain_researcher.services.agent.web_service import (
        _plan_context_from_request,
        _register_plan,
    )

    inputs = dict(plan_request.inputs)
    inputs.setdefault("raw_meg", "sub-01_task-rest_meg.fif")
    plan_request = plan_request.model_copy(update={"inputs": inputs})

    steps = [
        StepSpec(
            id="meg_s1",
            tool="epoch_events",
            consumes={"raw_meg": "timeseries"},
            produces={"epochs": "epochs"},
        ),
        StepSpec(
            id="meg_s2",
            tool="connectivity_measures",
            consumes={"epochs": "epochs"},
            produces={"connectivity_matrix": "connectivity_matrix"},
        ),
    ]

    artifacts = [
        ArtifactSpec(name="epochs", rtype="epochs", description="Event-aligned epochs"),
        ArtifactSpec(
            name="connectivity_matrix",
            rtype="connectivity_matrix",
            description="Connectivity matrix",
        ),
    ]

    plan_id = f"plan_{uuid.uuid4().hex[:8]}"
    dag = PlanDAG(steps=steps, artifacts=artifacts)
    estimates = {"duration_s": 120.0, "cost_units": 0.8}

    plan = Plan(
        plan_id=plan_id,
        version=1,
        domain=plan_request.domain,
        modality=plan_request.modality,
        resolvable=True,
        dag=dag,
        estimates=estimates,
        warnings=[],
        constraints=plan_request.constraints,
    )
    _register_plan(plan, context=_plan_context_from_request(plan_request))
    return plan


def _build_connectivity_plan_ieeg(plan_request: PlanRequest) -> Plan:
    """Build iEEG connectivity analysis plan with cross-modal coregistration."""
    from brain_researcher.services.agent.web_service import (
        _plan_context_from_request,
        _register_plan,
    )

    inputs = dict(plan_request.inputs)
    inputs.setdefault("raw_ieeg", "sub-01_task-rest_ieeg.edf")
    inputs.setdefault("ct_image", "sub-01_ct.nii.gz")
    inputs.setdefault("mri_image", "sub-01_T1w.nii.gz")
    # Use the canonical resource name for BIDS events (matches ResourceType/events_tsv).
    # Accept legacy "events" input key if provided.
    inputs.setdefault("events_tsv", inputs.get("events") or "sub-01_events.tsv")
    plan_request = plan_request.model_copy(update={"inputs": inputs})

    steps = [
        # H7: Coregister CT to MRI before electrode localization
        StepSpec(
            id="ieeg_coreg_s1",
            tool="coreg_register",
            consumes={"moving_image": "ct_image", "fixed_image": "mri_image"},
            produces={
                "transform_matrix": "ct_to_mri_xfm",
                "registered_image": "ct_in_mri",
            },
            params={"cost_function": "mi"},
        ),
        StepSpec(
            id="ieeg_s1",
            tool="ieeg_electrode_localize",
            consumes={"ct_image": "ct_in_mri", "mri_image": "mri_image"},
            produces={"contacts_mni": "contacts_mni"},
            params={},
        ),
        StepSpec(
            id="ieeg_s2",
            tool="ieeg_preprocess",
            consumes={"raw_ieeg": "raw_ieeg"},
            produces={"clean_ieeg": "clean_ieeg"},
            params={
                "reference": "car",
                "l_freq": 0.5,
                "h_freq": 250.0,
                "notch_freq": 60.0,
            },
        ),
        StepSpec(
            id="ieeg_s3",
            tool="ieeg_epoch_features",
            consumes={"clean_ieeg": "clean_ieeg", "events": "events_tsv"},
            produces={"features_table": "features_table"},
            params={
                "bands": ["delta", "theta", "alpha", "beta", "gamma"],
                "epoch_length": 2.0,
            },
        ),
        StepSpec(
            id="ieeg_s4",
            tool="ieeg_connectivity",
            consumes={"features_table": "features_table"},
            produces={"connectivity_matrix": "connectivity_matrix"},
            params={"metric": "plv"},
        ),
    ]

    artifacts = [
        ArtifactSpec(
            name="ct_to_mri_xfm", rtype="volume_3d", description="CT to MRI transform"
        ),
        ArtifactSpec(
            name="ct_in_mri", rtype="volume_3d", description="CT registered to MRI"
        ),
        ArtifactSpec(
            name="contacts_mni",
            rtype="parcellation_labels",
            description="Electrode contacts in MNI",
        ),
        ArtifactSpec(
            name="clean_ieeg", rtype="clean_eeg", description="Preprocessed iEEG"
        ),
        ArtifactSpec(
            name="features_table", rtype="timeseries", description="Epoch features"
        ),
        ArtifactSpec(
            name="connectivity_matrix",
            rtype="connectivity_matrix",
            description="iEEG connectivity",
        ),
    ]

    plan_id = f"plan_{uuid.uuid4().hex[:8]}"
    dag = PlanDAG(steps=steps, artifacts=artifacts)
    estimates = {"duration_s": 180.0, "cost_units": 1.0}

    plan = Plan(
        plan_id=plan_id,
        version=1,
        domain=plan_request.domain,
        modality=plan_request.modality,
        resolvable=True,
        dag=dag,
        estimates=estimates,
        warnings=[],
        constraints=plan_request.constraints,
    )
    _register_plan(plan, context=_plan_context_from_request(plan_request))
    return plan


def _build_demo_plan(plan_request: PlanRequest) -> Plan:
    from brain_researcher.services.agent.web_service import _register_plan

    message = plan_request.inputs.get("message", "demo-pass")
    payload = plan_request.inputs.get("payload") or {}

    steps = [
        StepSpec(
            id="demo_s1",
            tool="demo_passthrough",
            params={"message": message, "payload": payload},
            produces={"demo_payload": "demo_payload"},
            consumes={},
        )
    ]
    dag = PlanDAG(steps=steps, artifacts=[])
    plan = Plan(
        plan_id=f"plan_{uuid.uuid4().hex[:8]}",
        version=1,
        domain=plan_request.domain,
        modality=plan_request.modality,
        resolvable=True,
        dag=dag,
        estimates={"duration_s": 1.0, "cost_units": 0.0},
        warnings=[],
        constraints=plan_request.constraints,
    )
    _register_plan(plan, context={"demo": True})
    return plan


def _build_dmri_connectome_plan(plan_request: PlanRequest) -> Plan:
    """Build dMRI structural connectivity analysis plan with atlas resolution."""
    from brain_researcher.services.agent.web_service import (
        _plan_context_from_request,
        _register_plan,
    )

    inputs = dict(plan_request.inputs)
    inputs.setdefault("subject_id", "01")
    inputs.setdefault("bids_root", "/data/bids")
    inputs.setdefault("atlas_name", "Schaefer2018_200")
    inputs.setdefault("reference_mask", "cerebellum_mask.nii.gz")
    if "subject" in inputs and "subject_id" not in inputs:
        inputs["subject_id"] = inputs["subject"]
    plan_request = plan_request.model_copy(update={"inputs": inputs})

    steps = [
        StepSpec(
            id="dmri_s1",
            tool="dmri_resolve_dwi_triplet",
            consumes={"subject_id": "subject_id", "bids_root": "bids_root"},
            produces={"dwi_image": "dwi_image", "bvals": "bvals", "bvecs": "bvecs"},
            params={"session_id": inputs.get("session_id")},
        ),
        StepSpec(
            id="dmri_s2",
            tool="dmri_fit_model",
            consumes={"dwi_image": "dwi_image", "bvals": "bvals", "bvecs": "bvecs"},
            produces={"fa_map": "fa_map", "md_map": "md_map", "fodf": "fodf"},
            params={"model": "csd"},
        ),
        # H7: Fetch standard parcellation before connectome construction
        StepSpec(
            id="dmri_s3",
            tool="parcellation_fetch",
            consumes={"atlas_name": "atlas_name"},
            produces={
                "parcellation_volume": "parcellation_volume",
                "labels_tsv": "labels_tsv",
            },
            params={
                "atlas_name": inputs.get("atlas_name", "Schaefer2018_200"),
                "space": "MNI152NLin2009cAsym",
            },
        ),
        StepSpec(
            id="dmri_s4",
            tool="dmri_parcellate_connectome",
            consumes={"fodf": "fodf", "parcellation_labels": "parcellation_volume"},
            produces={"connectivity_matrix": "connectivity_matrix"},
            params={},
        ),
    ]

    artifacts = [
        ArtifactSpec(
            name="dwi_image", rtype="volume_4d", description="Diffusion image"
        ),
        ArtifactSpec(name="bvals", rtype="volume_3d", description="B-values"),
        ArtifactSpec(name="bvecs", rtype="volume_3d", description="B-vectors"),
        ArtifactSpec(
            name="fa_map", rtype="stat_map", description="Fractional anisotropy"
        ),
        ArtifactSpec(name="md_map", rtype="stat_map", description="Mean diffusivity"),
        ArtifactSpec(
            name="fodf", rtype="volume_4d", description="Fiber orientation distribution"
        ),
        ArtifactSpec(
            name="parcellation_volume",
            rtype="parcellation_labels",
            description="Brain parcellation atlas",
        ),
        ArtifactSpec(
            name="labels_tsv",
            rtype="parcellation_labels",
            description="Parcellation labels metadata",
        ),
        ArtifactSpec(
            name="connectivity_matrix",
            rtype="connectivity_matrix",
            description="Structural connectivity",
        ),
    ]

    plan_id = f"plan_{uuid.uuid4().hex[:8]}"
    dag = PlanDAG(steps=steps, artifacts=artifacts)
    estimates = {"duration_s": 300.0, "cost_units": 1.5}

    plan = Plan(
        plan_id=plan_id,
        version=1,
        domain=plan_request.domain,
        modality=plan_request.modality,
        resolvable=True,
        dag=dag,
        estimates=estimates,
        warnings=[],
        constraints=plan_request.constraints,
    )
    _register_plan(plan, context=_plan_context_from_request(plan_request))
    return plan


def _build_smri_morphometry_plan(plan_request: PlanRequest) -> Plan:
    """Build sMRI morphometry analysis plan."""
    from brain_researcher.services.agent.web_service import (
        _maybe_add_resolvers,
        _plan_context_from_request,
        _register_plan,
    )

    inputs = dict(plan_request.inputs)
    inputs.setdefault("subject_id", "01")
    inputs.setdefault("t1w_image", "sub-01_T1w.nii.gz")
    if "subject" in inputs and "subject_id" not in inputs:
        inputs["subject_id"] = inputs["subject"]
    plan_request = plan_request.model_copy(update={"inputs": inputs})

    steps = [
        StepSpec(
            id="smri_s1",
            tool="smri_recon",
            consumes={"t1w_image": "t1w_image"},
            produces={
                "surfaces_dir": "surfaces_dir",
                "aseg": "aseg",
                "aparcaseg": "aparcaseg",
            },
            params={
                "subject_id": inputs.get("subject_id"),
                "use_fastsurfer": inputs.get("use_fastsurfer", False),
            },
        ),
        StepSpec(
            id="smri_s2",
            tool="smri_parcellation_stats",
            consumes={"surfaces_dir": "surfaces_dir"},
            produces={
                "thickness_table": "thickness_table",
                "volume_table": "volume_table",
            },
            params={
                "stats_type": inputs.get("stats_type", "thickness"),
                "parcellation": inputs.get("parcellation", "aparc"),
            },
        ),
        StepSpec(
            id="smri_s3",
            tool="smri_surface_export",
            consumes={"surfaces_dir": "surfaces_dir"},
            produces={"surface_mesh": "surface_mesh"},
            params={
                "hemi": inputs.get("hemi", "both"),
                "surface_type": inputs.get("surface_type", "pial"),
            },
        ),
    ]

    artifacts = [
        ArtifactSpec(
            name="t1w_image", rtype="volume_3d", description="Input T1-weighted image"
        ),
        ArtifactSpec(
            name="surfaces_dir",
            rtype="surface_mesh",
            description="FreeSurfer surfaces directory",
        ),
        ArtifactSpec(
            name="aseg",
            rtype="parcellation_labels",
            description="Automated segmentation volume",
        ),
        ArtifactSpec(
            name="aparcaseg",
            rtype="parcellation_labels",
            description="Cortical parcellation volume",
        ),
        ArtifactSpec(
            name="thickness_table",
            rtype="timeseries",
            description="Cortical thickness statistics",
        ),
        ArtifactSpec(
            name="volume_table",
            rtype="timeseries",
            description="Cortical volume statistics",
        ),
        ArtifactSpec(
            name="surface_mesh",
            rtype="surface_mesh",
            description="Exported surface mesh",
        ),
    ]

    _maybe_add_resolvers(
        steps,
        artifacts,
        inputs,
        requires_bids=bool(inputs.get("bids_root") and inputs.get("subject_id")),
        requires_space=False,
        bids_output_name="t1w_image",
    )

    plan_id = f"plan_{uuid.uuid4().hex[:8]}"
    dag = PlanDAG(steps=steps, artifacts=artifacts)
    estimates = {"duration_s": 600.0, "cost_units": 2.0}

    plan = Plan(
        plan_id=plan_id,
        version=1,
        domain=plan_request.domain,
        modality=plan_request.modality,
        resolvable=True,
        dag=dag,
        estimates=estimates,
        warnings=[],
        constraints=plan_request.constraints,
    )
    _register_plan(plan, context=_plan_context_from_request(plan_request))
    return plan


def _build_pet_suvr_plan(plan_request: PlanRequest) -> Plan:
    """Build PET SUVR analysis plan for metabolism/amyloid imaging."""
    from brain_researcher.services.agent.web_service import (
        _maybe_add_resolvers,
        _plan_context_from_request,
        _register_plan,
    )

    inputs = dict(plan_request.inputs)
    inputs.setdefault("subject_id", "01")
    inputs.setdefault("pet_image", "sub-01_pet.nii.gz")
    inputs.setdefault("t1w_image", "sub-01_T1w.nii.gz")
    inputs.setdefault("atlas_name", "Schaefer2018_200")
    if "subject" in inputs and "subject_id" not in inputs:
        inputs["subject_id"] = inputs["subject"]
    plan_request = plan_request.model_copy(update={"inputs": inputs})

    steps = [
        StepSpec(
            id="pet_s1",
            tool="pet_coreg",
            consumes={"pet_image": "pet_image", "t1w_image": "t1w_image"},
            produces={"pet_in_t1": "pet_in_t1", "transform_matrix": "xfm"},
            params={"method": inputs.get("coreg_method", "rigid")},
        ),
        StepSpec(
            id="pet_s2",
            tool="pet_suvr",
            consumes={"pet_image": "pet_in_t1", "reference_mask": "reference_mask"},
            produces={"suvr_map": "suvr_map", "qc_volume": "qc_volume"},
            params={"frames": inputs.get("frames", "40:60")},
        ),
        StepSpec(
            id="pet_s3",
            tool="pet_parcellate",
            consumes={
                "suvr_map": "suvr_map",
                "parcellation_labels": "parcellation_labels",
            },
            produces={"roi_suvr_table": "roi_suvr"},
            params={"atlas_name": inputs.get("atlas_name")},
        ),
    ]

    artifacts = [
        ArtifactSpec(
            name="pet_image", rtype="volume_3d", description="Input PET volume"
        ),
        ArtifactSpec(
            name="t1w_image",
            rtype="volume_3d",
            description="Input T1-weighted anatomical image",
        ),
        ArtifactSpec(
            name="pet_in_t1",
            rtype="volume_3d",
            description="PET coregistered to T1w space",
        ),
        ArtifactSpec(
            name="xfm", rtype="volume_3d", description="Transformation matrix"
        ),
        ArtifactSpec(
            name="reference_mask",
            rtype="mask_path",
            description="Reference region mask",
        ),
        ArtifactSpec(
            name="suvr_map", rtype="stat_map", description="SUVR statistical map"
        ),
        ArtifactSpec(
            name="qc_volume", rtype="volume_3d", description="Quality control volume"
        ),
        ArtifactSpec(
            name="parcellation_labels",
            rtype="parcellation_labels",
            description="Parcellation atlas",
        ),
        ArtifactSpec(
            name="roi_suvr", rtype="timeseries", description="ROI SUVR values table"
        ),
    ]

    # Add BIDS resolution for T1w or PET image if needed
    _maybe_add_resolvers(
        steps,
        artifacts,
        inputs,
        requires_bids=bool(inputs.get("bids_root") and inputs.get("subject_id")),
        requires_space=False,
        bids_output_name="t1w_image",  # Can also be "pet_image" depending on use case
    )

    # Add parcellation fetching if atlas_name provided but no parcellation_labels
    if inputs.get("atlas_name") and not inputs.get("parcellation_labels"):
        parcellation_step = StepSpec(
            id="pet_s0",
            tool="parcellation_fetch",
            consumes={},
            produces={
                "parcellation_labels": "parcellation_labels",
                "labels_tsv": "labels_tsv",
            },
            params={"atlas_name": inputs["atlas_name"]},
        )
        # Find insertion point (after any resolve_* steps, before core processing)
        insert_idx = 0
        for i, s in enumerate(steps):
            if s.id.startswith("resolve_"):
                insert_idx = i + 1
        steps.insert(insert_idx, parcellation_step)
        # Add labels artifact if not already present
        if not any(a.name == "labels_tsv" for a in artifacts):
            artifacts.append(
                ArtifactSpec(
                    name="labels_tsv",
                    rtype="parcellation_labels",
                    description="Atlas ROI labels table",
                )
            )

    plan_id = f"plan_{uuid.uuid4().hex[:8]}"
    dag = PlanDAG(steps=steps, artifacts=artifacts)
    estimates = {"duration_s": 900.0, "cost_units": 3.0}

    plan = Plan(
        plan_id=plan_id,
        version=1,
        domain=plan_request.domain,
        modality=plan_request.modality,
        resolvable=True,
        dag=dag,
        estimates=estimates,
        warnings=[],
        constraints=plan_request.constraints,
    )
    _register_plan(plan, context=_plan_context_from_request(plan_request))
    return plan


def _build_meta_termmap_plan(plan_request: PlanRequest) -> Plan:
    """Build literature meta-analysis plan for term-based activation mapping."""
    from brain_researcher.services.agent.web_service import (
        _plan_context_from_request,
        _register_plan,
    )

    inputs = dict(plan_request.inputs)
    inputs.setdefault("term", "working memory")
    inputs.setdefault("target_space", "MNI152NLin2009cAsym")
    plan_request = plan_request.model_copy(update={"inputs": inputs})

    steps = [
        StepSpec(
            id="meta_s1",
            tool="meta_brainmap",
            consumes={"term": "term"},
            produces={"coord_table": "coord_table", "stat_map": "stat_map"},
            params={"contrast_type": inputs.get("contrast_type", "activation")},
        ),
        StepSpec(
            id="meta_s2",
            tool="meta_align",
            consumes={"stat_map": "stat_map", "target_space": "target_space"},
            produces={"aligned_map": "aligned_map"},
            params={"resolution": inputs.get("resolution", "2mm")},
        ),
        StepSpec(
            id="meta_s3",
            tool="meta_combine",
            consumes={"stat_map": "aligned_map"},
            produces={"meta_stat_map": "meta_stat_map", "report_html": "meta_report"},
            params={"method": inputs.get("method", "fixed_effects")},
        ),
    ]

    artifacts = [
        ArtifactSpec(
            name="term", rtype="subject_label", description="Meta-analysis term"
        ),
        ArtifactSpec(
            name="target_space",
            rtype="subject_label",
            description="Target template space",
        ),
        ArtifactSpec(
            name="coord_table", rtype="coord_table", description="Coordinates table"
        ),
        ArtifactSpec(
            name="stat_map", rtype="stat_map", description="Unaligned statistical map"
        ),
        ArtifactSpec(
            name="aligned_map", rtype="stat_map", description="Aligned statistical map"
        ),
        ArtifactSpec(
            name="meta_stat_map",
            rtype="stat_map",
            description="Combined meta-analysis map",
        ),
        ArtifactSpec(
            name="meta_report",
            rtype="report_html",
            description="Meta-analysis HTML report",
        ),
    ]

    plan_id = f"plan_{uuid.uuid4().hex[:8]}"
    dag = PlanDAG(steps=steps, artifacts=artifacts)
    estimates = {"duration_s": 420.0, "cost_units": 1.2}

    plan = Plan(
        plan_id=plan_id,
        version=1,
        domain=plan_request.domain,
        modality=plan_request.modality,
        resolvable=True,
        dag=dag,
        estimates=estimates,
        warnings=[],
        constraints=plan_request.constraints,
    )
    _register_plan(plan, context=_plan_context_from_request(plan_request))
    return plan


def _build_kg_ingest_validate_plan(plan_request: PlanRequest) -> Plan:
    """Build BR-KG ingestion and validation plan."""
    from brain_researcher.services.agent.web_service import (
        _plan_context_from_request,
        _register_plan,
    )

    inputs = dict(plan_request.inputs)
    inputs.setdefault("nodes_file", "kg_nodes.csv")
    inputs.setdefault("edges_file", "kg_edges.csv")
    plan_request = plan_request.model_copy(update={"inputs": inputs})

    steps = [
        StepSpec(
            id="kg_s1",
            tool="kg_ingest",
            consumes={"nodes_file": "nodes_file", "edges_file": "edges_file"},
            produces={"kg_nodes": "kg_nodes", "kg_edges": "kg_edges"},
            params={},
        ),
        StepSpec(
            id="kg_s2",
            tool="kg_shacl_validate",
            consumes={"kg_nodes": "kg_nodes", "kg_edges": "kg_edges"},
            produces={"report_html": "kg_report"},
            params={},
        ),
    ]

    # Optional multi-hop QA if a question is provided
    if inputs.get("question"):
        steps.append(
            StepSpec(
                id="kg_s3",
                tool="kg_multihop_qa",
                consumes={"question": "question"},
                produces={"answer": "kg_answer", "subgraph": "kg_subgraph"},
                params={
                    "question": inputs["question"],
                    "max_hops": inputs.get("max_hops", 3),
                    "return_subgraph": inputs.get("return_subgraph", True),
                },
            )
        )

    artifacts = [
        ArtifactSpec(
            name="nodes_file", rtype="kg_nodes", description="Input nodes CSV"
        ),
        ArtifactSpec(
            name="edges_file", rtype="kg_edges", description="Input edges CSV"
        ),
        ArtifactSpec(name="kg_nodes", rtype="kg_nodes", description="Ingested nodes"),
        ArtifactSpec(name="kg_edges", rtype="kg_edges", description="Ingested edges"),
        ArtifactSpec(
            name="kg_report", rtype="report_html", description="SHACL validation report"
        ),
    ]

    if inputs.get("question"):
        artifacts.append(
            ArtifactSpec(
                name="question", rtype="subject_label", description="QA question"
            )
        )
        artifacts.append(
            ArtifactSpec(
                name="kg_answer", rtype="subject_label", description="QA answer"
            )
        )
        artifacts.append(
            ArtifactSpec(
                name="kg_subgraph",
                rtype="kg_nodes",
                description="QA reasoning subgraph",
            )
        )

    plan_id = f"plan_{uuid.uuid4().hex[:8]}"
    dag = PlanDAG(steps=steps, artifacts=artifacts)
    estimates = {"duration_s": 300.0, "cost_units": 1.0}

    plan = Plan(
        plan_id=plan_id,
        version=1,
        domain=plan_request.domain,
        modality=plan_request.modality,
        resolvable=True,
        dag=dag,
        estimates=estimates,
        warnings=[],
        constraints=plan_request.constraints,
    )
    _register_plan(plan, context=_plan_context_from_request(plan_request))
    return plan


def _build_plan_for_request(plan_request: PlanRequest) -> Plan:
    pipeline = plan_request.pipeline.lower()
    modalities = {m.lower() for m in plan_request.modality}

    if pipeline == "connectivity":
        if "ieeg" in modalities:
            return _build_connectivity_plan_ieeg(plan_request)
        elif "meg" in modalities:
            return _build_connectivity_plan_meg(plan_request)
        elif "eeg" in modalities:
            return _build_connectivity_plan_eeg(plan_request)
        elif "dmri" in modalities or "dwi" in modalities:
            return _build_dmri_connectome_plan(plan_request)
        return _build_connectivity_plan_fmri(plan_request)

    if pipeline == "morphometry":
        if "smri" in modalities:
            return _build_smri_morphometry_plan(plan_request)

    if pipeline in ("metabolism", "pet"):
        if "pet" in modalities:
            return _build_pet_suvr_plan(plan_request)

    if pipeline == "demo_stub":
        return _build_demo_plan(plan_request)

    if pipeline == "meta_termmap":
        return _build_meta_termmap_plan(plan_request)

    if pipeline in ("kg_ingest_validate", "kg_ingest"):
        return _build_kg_ingest_validate_plan(plan_request)

    raise ValueError(f"Unsupported pipeline {plan_request.pipeline} for planner stub")
