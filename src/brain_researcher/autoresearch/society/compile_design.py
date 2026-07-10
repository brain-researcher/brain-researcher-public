"""Gate 2 (V-HRL): the hypothesis -> contrast semantic bridge.

This is the missing keystone of the hypothesis->BIDS compiler. The downstream pieces
already exist (``fitlins_tool._create_bids_model`` consumes a ``{name: {condition:
weight}}`` dict; ``binding_ids.canonical_contrast`` stabilises a content-derived
``contrast_id``; the keystone composes a multiverse ceiling). What was missing is the
SEMANTIC step that turns a :class:`HypothesisSpecV1`'s free-text
``critical_test.comparison`` (or ``cause``/``effect``) into a typed contrast over a
task's REAL condition vocabulary.

Honesty contract (mirrors ``neuroclaim_compile``'s no-extraction-laundering invariant):
this resolver is RULE-BASED only and NEVER fabricates a condition name or a weight. When
a hypothesis term cannot be matched to a real task condition, it returns an explicit
``unresolved`` result and the caller ABSTAINS from compiling a plausible-but-fake
contrast. The module is service-free (it takes the condition vocabulary as input — the
caller loads it from a parsed ``TaskSpec``), so it imports nothing service-tier and is
fully hermetically testable.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .binding_ids import canonical_contrast, canonical_multiverse_run_id
from .hypotheses import HypothesisSpecV1

#: Connective patterns for a two-pole comparison; group(1) is the ``+`` pole, group(2)
#: the ``-`` pole. Tried in order; the connectives are NOT cognitive terms.
_COMPARISON_PATTERNS: tuple[str, ...] = (
    r"(.+?)\s+(?:>|greater than|more than|higher than)\s+(.+)",
    r"(.+?)\s+(?:vs\.?|versus)\s+(.+)",
    # 'minus' / unicode minus only — a bare ASCII '-' is ambiguous with hyphenated terms.
    r"(.+?)\s+(?:minus|−)\s+(.+)",
    r"(.+?)\s+(?:over|against|relative to|compared to|compared with)\s+(.+)",
)


def _compact(value: str) -> str:
    """Compaction key matching the KG contrast Cypher (query_service.py:6107-6119).

    Drops the ``trial_type.`` / ``_demean`` / ``_reg`` design namespacing and all
    separators, lowercases. So ``trial_type.pumps`` ~ ``pumps`` ~ ``Pumps``.
    """
    text = str(value).lower().strip()
    text = text.replace("trial_type.", " ").replace("_demean", " ").replace("_reg", " ")
    text = re.sub(r"[._:\-]+", " ", text)
    return re.sub(r"\s+", "", text)


def _short(condition: str) -> str:
    """Readable contrast-name fragment from a dotted design condition."""
    frag = str(condition).split(".")[-1]
    return frag.replace("_demean", "").replace("_reg", "") or str(condition)


def parse_comparison(text: str | None) -> tuple[str, str] | None:
    """Parse ``'A > B'`` / ``'A vs B'`` / ``'A minus B'`` into ``(A, B)`` poles.

    Returns ``None`` when no two non-empty poles can be extracted.
    """
    if not text:
        return None
    for pattern in _COMPARISON_PATTERNS:
        match = re.search(pattern, text.strip(), flags=re.IGNORECASE)
        if match:
            left, right = match.group(1).strip(), match.group(2).strip()
            if left and right:
                return left, right
    return None


def resolve_term_to_condition(
    term: str | None,
    conditions: Sequence[str],
    *,
    aliases: dict[str, str] | None = None,
) -> str | None:
    """Map a free-text term to one of ``conditions``; ``None`` if nothing matches.

    Priority: curated alias -> exact compact-key match -> forward containment (the term is
    a substring of a condition, e.g. ``pump`` -> ``pumps``). ``None`` is the ABSTAIN
    signal — the caller must never fabricate a condition for an unmatched term, and we
    bias toward abstaining over guessing a wrong-but-real condition.
    """
    if not term:
        return None
    if aliases:
        aliased = aliases.get(term) or aliases.get(term.lower())
        if aliased and aliased in conditions:
            return aliased
    key = _compact(term)
    if not key:
        return None
    # A factor level (trial_type.pumps) and its parametric modulator (pumps_demean) share
    # the same compact key ("pumps"). For a categorical contrast prefer the trial_type.*
    # factor level; tie-break by shortest then lexicographic so the choice is ORDER-
    # INDEPENDENT (a sorted vs unsorted vocab must resolve identically).
    exact = [cond for cond in conditions if _compact(cond) == key]
    if exact:
        return _prefer_condition(exact)
    # Forward containment only (term is a substring of the condition), gated to keys of
    # >=3 chars. We deliberately do NOT match the reverse (a condition word contained in a
    # longer pole, e.g. "high working memory load" -> "high"): that grabs a real-but-wrong
    # condition; abstaining is the honest outcome. A 1-2 char key is too ambiguous to match.
    if len(key) < 3:
        return None
    contained = [cond for cond in conditions if key in _compact(cond)]
    if contained:
        return _prefer_condition(contained)
    return None


def _prefer_condition(candidates: Sequence[str]) -> str:
    """Pick the most contrast-appropriate condition: factor level > parametric > shortest."""
    return min(
        candidates,
        key=lambda cond: (
            not str(cond).startswith("trial_type."),
            len(_compact(cond)),
            cond,
        ),
    )


@dataclass(frozen=True)
class ContrastResolution:
    """One contrast resolved (or not) from a hypothesis."""

    name: str
    condition_list: tuple[str, ...]
    weights: tuple[float, ...]
    test: str
    status: str  # "resolved" | "unresolved"
    source: str  # which hypothesis field drove it
    reason: str = ""
    contrast_id: str | None = None
    polarity: int | None = None


@dataclass(frozen=True)
class CompiledContrasts:
    """The contrast bridge's output for one hypothesis over one task."""

    hypothesis_id: str
    dataset_id: str
    task: str
    conditions: tuple[str, ...]
    resolved: tuple[ContrastResolution, ...]
    unresolved: tuple[ContrastResolution, ...]

    @property
    def is_compilable(self) -> bool:
        """True iff at least one contrast resolved to real task conditions."""
        return bool(self.resolved)

    def builder_arg(self) -> dict[str, dict[str, float]]:
        """The exact ``{contrast_name: {condition: weight}}`` dict the BIDS model
        builder (``fitlins_tool._create_bids_model``) consumes. Resolved contrasts only.
        """
        return {
            res.name: dict(zip(res.condition_list, res.weights, strict=True))
            for res in self.resolved
        }


def _make_contrast(
    name: str,
    conditions: tuple[str, ...],
    weights: tuple[float, ...],
    source: str,
    dataset_id: str,
    task: str,
) -> ContrastResolution:
    contrast_id: str | None = None
    polarity: int | None = None
    if dataset_id and task:
        canonical = canonical_contrast(
            dataset_id=dataset_id,
            task=task,
            conditions=conditions,
            weights=weights,
            test="t",
        )
        contrast_id = canonical.contrast_id
        polarity = canonical.polarity
    return ContrastResolution(
        name=name,
        condition_list=conditions,
        weights=weights,
        test="t",
        status="resolved",
        source=source,
        contrast_id=contrast_id,
        polarity=polarity,
    )


def hypothesis_to_contrasts(
    hyp: HypothesisSpecV1,
    conditions: Sequence[str],
    *,
    dataset_id: str = "",
    task: str = "",
    aliases: dict[str, str] | None = None,
    include_simple_effects: bool = True,
) -> CompiledContrasts:
    """Compile a hypothesis into typed contrasts over a task's real condition vocabulary.

    Reads ``critical_test.comparison`` first (the primary 'A vs B' intent), falling back
    to ``cause``/``effect`` as the two poles. Emits an ``A > B`` difference contrast (and
    optionally the two simple-effect contrasts). ABSTAINS — returning an ``unresolved``
    result and no resolved contrasts — when there is no parseable two-pole intent or when
    a pole cannot be matched to a real condition. Never fabricates a condition or weight.
    """
    conds = tuple(dict.fromkeys(str(c) for c in conditions))

    poles: tuple[str, str] | None = None
    source = ""
    critical = hyp.critical_test
    if critical is not None and critical.comparison:
        parsed = parse_comparison(critical.comparison)
        if parsed is not None:
            poles, source = parsed, "critical_test.comparison"
    if poles is None and hyp.cause and hyp.effect:
        poles, source = (hyp.cause, hyp.effect), "cause/effect"

    def abstain(name: str, reason: str, src: str) -> CompiledContrasts:
        return CompiledContrasts(
            hypothesis_id=hyp.hypothesis_id,
            dataset_id=dataset_id,
            task=task,
            conditions=conds,
            resolved=(),
            unresolved=(
                ContrastResolution(
                    name=name,
                    condition_list=(),
                    weights=(),
                    test="t",
                    status="unresolved",
                    source=src,
                    reason=reason,
                ),
            ),
        )

    if poles is None:
        return abstain(
            "(no-contrast)",
            "no parseable contrast intent (need critical_test.comparison 'A vs B' "
            "or both cause and effect)",
            source or "none",
        )

    left_term, right_term = poles
    left = resolve_term_to_condition(left_term, conds, aliases=aliases)
    right = resolve_term_to_condition(right_term, conds, aliases=aliases)
    if left is None or right is None or left == right:
        missing = [
            term
            for term, res in ((left_term, left), (right_term, right))
            if res is None
        ]
        if missing:
            reason = f"unresolved pole(s) {missing}; not in task conditions"
        else:
            reason = f"both poles resolved to the same condition '{left}'"
        return abstain(f"{_short(left_term)}_gt_{_short(right_term)}", reason, source)

    resolved = [
        _make_contrast(
            f"{_short(left)}_gt_{_short(right)}",
            (left, right),
            (1.0, -1.0),
            source,
            dataset_id,
            task,
        )
    ]
    if include_simple_effects:
        resolved.append(
            _make_contrast(_short(left), (left,), (1.0,), source, dataset_id, task)
        )
        resolved.append(
            _make_contrast(_short(right), (right,), (1.0,), source, dataset_id, task)
        )
    return CompiledContrasts(
        hypothesis_id=hyp.hypothesis_id,
        dataset_id=dataset_id,
        task=task,
        conditions=conds,
        resolved=tuple(resolved),
        unresolved=(),
    )


# ======================================================================================
# Dataset/task selection + the compiled-plan object (Gate 2 orchestration)
# ======================================================================================


def hypothesis_poles(hyp: HypothesisSpecV1) -> tuple[str, ...]:
    """Candidate contrast-pole terms a hypothesis offers (comparison + cause/effect)."""
    poles: list[str] = []
    critical = hyp.critical_test
    if critical is not None and critical.comparison:
        parsed = parse_comparison(critical.comparison)
        if parsed is not None:
            poles.extend(parsed)
    for term in (hyp.cause, hyp.effect):
        if term:
            poles.append(term)
    return tuple(dict.fromkeys(poles))


@dataclass(frozen=True)
class TaskCandidate:
    """A (dataset, task) whose conditions can host (some of) a hypothesis's contrast poles."""

    dataset_id: str
    task: str
    conditions: tuple[str, ...]
    score: int  # number of DISTINCT conditions the hypothesis poles resolve to
    matched: tuple[str, ...]  # the resolved condition names


def rank_tasks_for_hypothesis(
    hyp: HypothesisSpecV1,
    tasks: Sequence[tuple[str, str, Sequence[str]]],
    *,
    aliases: dict[str, str] | None = None,
) -> list[TaskCandidate]:
    """Rank ``(dataset_id, task, conditions)`` candidates by hypothesis-pole resolvability.

    Score = number of DISTINCT task conditions the hypothesis's poles resolve to; a task
    needs score >= 2 to host a difference contrast. Sorted by (score desc, dataset, task)
    so selection is deterministic. Offline — no KG, no run.
    """
    poles = hypothesis_poles(hyp)
    ranked: list[TaskCandidate] = []
    for dataset_id, task, conditions in tasks:
        conds = tuple(dict.fromkeys(str(c) for c in conditions))
        matched: list[str] = []
        for pole in poles:
            resolved = resolve_term_to_condition(pole, conds, aliases=aliases)
            if resolved is not None and resolved not in matched:
                matched.append(resolved)
        ranked.append(
            TaskCandidate(
                dataset_id=dataset_id,
                task=task,
                conditions=conds,
                score=len(matched),
                matched=tuple(matched),
            )
        )
    ranked.sort(key=lambda c: (-c.score, c.dataset_id, c.task))
    return ranked


@dataclass(frozen=True)
class HypothesisPlanV1:
    """The executable form of a hypothesis: selected task + compiled contrasts + model.

    The thin Gate-2 envelope tying the pieces together. ``model_spec`` is built by an
    injected ``model_builder`` (so this stays service-free); ``to_plan_payload`` emits the
    lightweight ``{steps:[{tool,params,step_id}]}`` shape ``pipeline_plan_validate`` accepts.
    """

    hypothesis_id: str
    dataset_id: str
    task: str
    compiled: CompiledContrasts
    model_spec: dict | None = None
    design_priors: dict | None = None

    @property
    def status(self) -> str:
        return "compiled" if self.compiled.is_compilable else "abstained"

    def to_plan_payload(
        self,
        *,
        project_root: str,
        bids_dir: str | None = None,
        output_dir: str | None = None,
        derivatives_dir: str | None = None,
        hrf_model: str = "glover",
        analysis_level: str = "dataset",
    ) -> dict:
        """Emit the runnable plan dict ``pipeline_plan_validate`` accepts.

        ``project_root`` is REQUIRED (else run_tag is ignored and paths fail the policy);
        ``bids_dir``/``output_dir`` default to subpaths under it so the plan passes the
        path policy when ``project_root`` is under the deployment's allowed roots. fitlins
        requires ``output_dir``, so it is always emitted.
        """
        root = str(project_root).rstrip("/")
        # Defence-in-depth: neutralise path separators / traversal in the id-derived path
        # segments so a crafted dataset_id/hypothesis_id can't escape project_root even if
        # this is ever called outside the pipeline_plan_validate path-allow gate.
        safe_dataset = re.sub(r"[^A-Za-z0-9_-]+", "_", str(self.dataset_id))
        safe_hypothesis = re.sub(r"[^A-Za-z0-9_-]+", "_", str(self.hypothesis_id))
        params: dict[str, object] = {
            "bids_dir": bids_dir or f"{root}/openneuro/{safe_dataset}",
            "output_dir": output_dir or f"{root}/fitlins_out/{safe_hypothesis}",
            "hrf_model": hrf_model,
            "analysis_level": analysis_level,
            "contrasts": self.compiled.builder_arg(),
        }
        if derivatives_dir:
            params["derivatives_dir"] = derivatives_dir
        step_id = re.sub(
            r"[^A-Za-z0-9_-]+", "_", f"fitlins_{self.dataset_id}_{self.task}"
        )
        return {
            "project_root": root,
            "run_tag": f"hyp_{self.hypothesis_id}",
            "steps": [{"tool": "fitlins", "params": params, "step_id": step_id}],
        }


def compile_hypothesis(
    hyp: HypothesisSpecV1,
    *,
    task_candidate: TaskCandidate | None = None,
    tasks: Sequence[tuple[str, str, Sequence[str]]] | None = None,
    model_builder: Callable[[dict[str, dict[str, float]]], dict] | None = None,
    design_priors: dict | None = None,
    aliases: dict[str, str] | None = None,
    include_simple_effects: bool = True,
) -> HypothesisPlanV1:
    """Compile a hypothesis end-to-end: pick a task, resolve contrasts, build the model.

    Provide an explicit ``task_candidate`` OR a list of ``tasks`` to auto-select the best
    (highest pole-resolvability, needs >= 2 distinct conditions). ``model_builder`` (e.g. a
    wrapper around ``fitlins_tool._create_bids_model``) is injected to keep this module
    service-free; when omitted the plan carries contrasts but no model_spec. ABSTAINS
    (status='abstained', no contrasts) when no task can host a two-pole contrast.
    """
    dataset_id, task, conditions = "", "", ()
    if task_candidate is not None:
        dataset_id, task, conditions = (
            task_candidate.dataset_id,
            task_candidate.task,
            task_candidate.conditions,
        )
    elif tasks:
        ranked = rank_tasks_for_hypothesis(hyp, tasks, aliases=aliases)
        best = ranked[0] if ranked else None
        if best is not None:
            # Use the best-scoring task. If its score < 2 the contrast won't resolve and
            # hypothesis_to_contrasts abstains downstream with a concrete reason.
            dataset_id, task, conditions = best.dataset_id, best.task, best.conditions
    else:
        raise ValueError("compile_hypothesis needs either task_candidate or tasks")

    compiled = hypothesis_to_contrasts(
        hyp,
        conditions,
        dataset_id=dataset_id,
        task=task,
        aliases=aliases,
        include_simple_effects=include_simple_effects,
    )
    model_spec: dict | None = None
    if compiled.is_compilable and model_builder is not None:
        model_spec = model_builder(compiled.builder_arg())
    return HypothesisPlanV1(
        hypothesis_id=hyp.hypothesis_id,
        dataset_id=dataset_id,
        task=task,
        compiled=compiled,
        model_spec=model_spec,
        design_priors=design_priors,
    )


# ======================================================================================
# Multiverse fan-out: compile one hypothesis into a design-variant family (-> keystone)
# ======================================================================================

#: Default design priors when no KG GLMDesignPrior is available (get_glm_priors needs a
#: live Neo4j and returns None offline). Varies HRF basis, high-pass cutoff, AND the
#: confounds family — the three design axes the FitLins model builder applies (HRF +
#: high-pass directly; confounds via _apply_confounds_variant, supplied by the injected
#: model_builder). A genuinely diverse multiverse is what lets the keystone detect
#: pipeline fragility.
DEFAULT_DESIGN_PRIORS: dict[str, dict[str, float]] = {
    "hrf_basis": {"canonical": 0.4, "derivs": 0.3, "glover": 0.2, "fir": 0.1},
    "high_pass": {"128": 0.5, "256": 0.5},
    "confounds": {"6mot": 0.5, "24mot": 0.3, "24mot_physio": 0.2},
}


@dataclass(frozen=True)
class DesignVariant:
    """One multiverse pipeline variant for a compiled hypothesis."""

    variant_id: str
    decision_points: dict
    hrf_model: str
    high_pass_cutoff: int | None
    confounds_mode: str
    model_spec: dict | None = None


@dataclass(frozen=True)
class MultiverseCompiled:
    """A hypothesis compiled into a family of design variants (the multiverse spec).

    This is the link between the Gate-2 compiler and the closed multiverse keystone: a
    real ``multiverse_run_id`` content-addresses the variant set, so executing these and
    feeding the z-maps to ``multiverse_robustness_report`` -> ``multiverse_ceiling`` binds
    the resulting claim fail-closed on ``(contrast_id, multiverse_run_id)``.
    """

    hypothesis_id: str
    dataset_id: str
    task: str
    builder_arg: dict[str, dict[str, float]]
    variants: tuple[DesignVariant, ...]
    multiverse_run_id: str | None

    @property
    def is_compilable(self) -> bool:
        return bool(self.variants)


def _variant_design_params(decision_points: dict) -> tuple[str, int | None, str]:
    """Map a spec-family decision point to (hrf_model, high_pass_cutoff, confounds_mode)."""
    hrf_model = str(decision_points.get("hrf_basis") or "glover")
    raw_hp = decision_points.get("high_pass")
    cutoff: int | None = None
    if raw_hp not in (None, "") and str(raw_hp).isdigit():
        cutoff = int(raw_hp)
    confounds_mode = str(decision_points.get("confounds") or "6mot")
    return hrf_model, cutoff, confounds_mode


def compile_hypothesis_multiverse(
    hyp: HypothesisSpecV1,
    *,
    tasks: Sequence[tuple[str, str, Sequence[str]]] | None = None,
    task_candidate: TaskCandidate | None = None,
    priors: dict[str, dict[str, float]] | None = None,
    k: int = 8,
    seed: int = 0,
    model_builder: Callable[..., dict] | None = None,
    aliases: dict[str, str] | None = None,
) -> MultiverseCompiled:
    """Compile a hypothesis into a k-variant design multiverse.

    Resolves the contrast (auto-selecting the task), then fans out over design-prior
    decision points via ``generate_spec_family`` (HRF basis + high-pass). ABSTAINS (no
    variants) when the contrast does not compile. ``model_builder(builder_arg, *,
    hrf_model, high_pass_cutoff) -> dict`` is injected so this module stays service-free.
    """
    plan = compile_hypothesis(
        hyp, tasks=tasks, task_candidate=task_candidate, aliases=aliases
    )
    builder_arg = plan.compiled.builder_arg()
    variants: list[DesignVariant] = []
    if plan.status == "compiled":
        # Lazy core import (keeps the pure bridge import-light + service-free).
        from brain_researcher.core.multiverse.spec_family import generate_spec_family

        specs = generate_spec_family(priors or DEFAULT_DESIGN_PRIORS, k=k, seed=seed)
        for spec in specs:
            decision_points = spec.get("decision_points", spec)
            variant_id = str(spec.get("variant_id") or "")
            hrf_model, cutoff, confounds_mode = _variant_design_params(decision_points)
            model_spec = None
            if model_builder is not None:
                model_spec = model_builder(
                    builder_arg,
                    hrf_model=hrf_model,
                    high_pass_cutoff=cutoff,
                    confounds_mode=confounds_mode,
                )
            variants.append(
                DesignVariant(
                    variant_id=variant_id,
                    decision_points=decision_points,
                    hrf_model=hrf_model,
                    high_pass_cutoff=cutoff,
                    confounds_mode=confounds_mode,
                    model_spec=model_spec,
                )
            )
    multiverse_run_id: str | None = None
    if variants and plan.dataset_id and plan.task:
        multiverse_run_id = canonical_multiverse_run_id(
            dataset_id=plan.dataset_id,
            task=plan.task,
            variant_ids=[v.variant_id for v in variants],
        )
    return MultiverseCompiled(
        hypothesis_id=hyp.hypothesis_id,
        dataset_id=plan.dataset_id,
        task=plan.task,
        builder_arg=builder_arg,
        variants=tuple(variants),
        multiverse_run_id=multiverse_run_id,
    )
