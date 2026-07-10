"""Standalone NeuroLang probabilistic-Datalog worker (runs in an isolated 3.12 venv).

This file is **not** part of the ``brain_researcher`` import graph: it is invoked
out-of-process by :class:`NeuroLangBackend` via the dedicated NeuroLang venv
(``BR_NEUROLANG_PYTHON``) because NeuroLang pins Python >= 3.12 and a different
``pandas``/``nibabel``/``nilearn`` line than the main env. It therefore imports
**only** ``neurolang`` + the standard library — never ``brain_researcher``.

Protocol (one JSON object on stdin, one on stdout):

    in  := {"term_studies":   [study_id, ...],   # studies about the term (>= threshold)
            "region_studies": [study_id, ...],   # studies with a peak in the region
            "all_studies":    [study_id, ...],   # full corpus (for the base rate)
            "query":          "forward_inference"}
    out := {"ok": true, "p_region_given_term": p, "p_region": base, "lift": p/base,
            "n_term": k, "n_region": m, "n_total": N, "neurolang_version": "..."}
           # or {"ok": false, "error": ...}

The forward inference ``P(activation@region | term)`` is computed the literature
(NeuroLang-Neurosynth) way: a **uniform probabilistic choice over studies** is the
random event, and term/region membership are deterministic relations over studies,
so the PDL marginal collapses to the frequency ``|region ∩ term| / |term|`` — and
likewise ``P(region) = |region| / |corpus|`` over all studies. Their ratio is the
discriminative *lift* (a flat forward frequency alone saturates and cannot separate
a real association from a high base rate). The marginal is solved by the PDL engine,
not a hand-rolled ratio, so the path generalises to compositional/multi-hop queries.

A second query ``compositional_forward`` realises that generalisation: it carves the
eligible study set with a Datalog **negation** rule (``term A AND NOT {confounds}``)
and compares ``P(region | A AND NOT confounds)`` against ``P(region | A)`` — the
specificity test a coordinate ALE cannot express. See the worker functions for the
exact payload of each query.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def _marginal_over_uniform_studies(domain: list[str], hits: set[str]) -> float:
    """P(hit) when a study is drawn uniformly at random from ``domain``.

    Computed by the PDL engine: ``Study`` is a uniform probabilistic choice over the
    domain and ``Hit`` is a deterministic relation, so the grouped marginal collapses
    to ``|domain ∩ hits| / |domain|`` — but via the probabilistic solver, so the same
    construction extends to weighted / multi-hop queries.
    """
    from neurolang.frontend import NeurolangPDL

    if not domain:
        return 0.0
    hit_rows = [("R", s) for s in domain if s in hits]
    if not hit_rows:
        return 0.0
    nl = NeurolangPDL()
    nl.add_uniform_probabilistic_choice_over_set([(s,) for s in domain], name="Study")
    nl.add_tuple_set(hit_rows, name="Hit")
    with nl.scope as e:
        # Marginal P(the random study is a hit), grouped by the region tag ``r``.
        e.Marginal[e.r, e.PROB[e.r]] = e.Hit[e.r, e.s] & e.Study[e.s]
        res = nl.query((e.r, e.p), e.Marginal[e.r, e.p])
    df = res.as_pandas_dataframe()
    return float(df["p"].iloc[0]) if len(df) else 0.0


def _forward_inference(payload: dict[str, Any]) -> dict[str, Any]:
    term = [str(s) for s in payload.get("term_studies", [])]
    region = {str(s) for s in payload.get("region_studies", [])}
    alls = [str(s) for s in payload.get("all_studies", [])] or term
    if not term:
        return {
            "ok": True,
            "p_region_given_term": None,
            "p_region": None,
            "lift": None,
            "n_term": 0,
            "n_region": len(region),
            "n_total": len(alls),
            "note": "no study is about the term",
        }

    p_rgt = _marginal_over_uniform_studies(term, region)  # P(region | term)
    p_r = _marginal_over_uniform_studies(alls, region)  # P(region) base rate
    lift = (p_rgt / p_r) if p_r and p_r > 0 else None
    return {
        "ok": True,
        "p_region_given_term": p_rgt,
        "p_region": p_r,
        "lift": lift,
        "n_term": len(term),
        "n_region": len(region),
        "n_total": len(alls),
    }


def _eligible_via_datalog(
    include: list[str], exclude_sets: list[list[str]]
) -> list[str]:
    """Studies about the include term and about NONE of the exclude terms.

    Computed by a deterministic NeuroLang Datalog rule with stratified **negation** —
    ``Eligible(s) :- Inc(s), ~Exc0(s), ~Exc1(s), ...`` — the compositional/logical
    capability that a coordinate ALE (NiMARE) structurally cannot express. ``s`` is
    range-restricted by ``Inc(s)`` so the negation is safe.
    """
    from neurolang.frontend import NeurolangPDL

    if not include:
        return []
    nonempty = [exc for exc in exclude_sets if exc]
    nl = NeurolangPDL()
    nl.add_tuple_set([(s,) for s in include], name="Inc")
    for i, exc in enumerate(nonempty):
        nl.add_tuple_set([(s,) for s in exc], name=f"Exc{i}")
    with nl.scope as e:
        body = e.Inc[e.s]
        for i in range(len(nonempty)):
            body = body & ~getattr(e, f"Exc{i}")[e.s]
        e.Eligible[e.s] = body
        res = nl.query((e.s,), e.Eligible[e.s])
    return sorted(
        {str(row[0]) for row in res.as_pandas_dataframe().itertuples(index=False)}
    )


def _compositional_forward(payload: dict[str, Any]) -> dict[str, Any]:
    """Specificity query: P(region | term A AND NOT {confounds}) vs P(region | A).

    Tests whether a region–term association is *specific* to the claimed construct or is
    (partly) driven by a confounding/rival term — the discrimination V-HRL reasoning
    modes care about. The eligible set is carved by a Datalog negation rule; the three
    forward frequencies reuse the uniform-choice marginal.
    """
    include = [str(s) for s in payload.get("include_studies", [])]
    exclude_map = payload.get("exclude_studies", {}) or {}
    region = {str(s) for s in payload.get("region_studies", [])}
    alls = [str(s) for s in payload.get("all_studies", [])] or include
    if not include:
        return {
            "ok": True,
            "p_region_given_specific": None,
            "p_region_given_include": None,
            "p_region": None,
            "lift_specific": None,
            "lift_include": None,
            "specificity_drop": None,
            "n_include": 0,
            "n_eligible": 0,
            "n_region": len(region),
            "n_total": len(alls),
            "exclude_terms": list(exclude_map),
            "note": "no study is about the include term",
        }

    exclude_sets = [[str(s) for s in v] for v in exclude_map.values()]
    eligible = _eligible_via_datalog(include, exclude_sets)
    p_specific = _marginal_over_uniform_studies(eligible, region)
    p_include = _marginal_over_uniform_studies(include, region)
    p_base = _marginal_over_uniform_studies(alls, region)
    return {
        "ok": True,
        "p_region_given_specific": p_specific,
        "p_region_given_include": p_include,
        "p_region": p_base,
        "lift_specific": (p_specific / p_base) if p_base else None,
        "lift_include": (p_include / p_base) if p_base else None,
        "specificity_drop": p_include - p_specific,
        "n_include": len(include),
        "n_eligible": len(eligible),
        "n_excluded": len(include) - len(eligible),
        "n_region": len(region),
        "n_total": len(alls),
        "exclude_terms": list(exclude_map),
    }


def _joint_via_datalog(region_sets: list[list[str]]) -> list[str]:
    """Studies reporting a peak in ALL named regions.

    A multi-region NeuroLang Datalog **conjunction** — ``CoActive(s) :- Reg0(s),
    Reg1(s), ...`` — i.e. the network-level join across region-peak relations. A
    coordinate ALE produces one convergence map and cannot ask "studies activating
    region A *and* region B *and* ..." as a single declarative query.
    """
    from neurolang.frontend import NeurolangPDL

    region_sets = [r for r in region_sets if r]
    if not region_sets:
        return []
    if len(region_sets) == 1:
        return sorted(set(region_sets[0]))
    nl = NeurolangPDL()
    for i, rs in enumerate(region_sets):
        nl.add_tuple_set([(s,) for s in rs], name=f"Reg{i}")
    with nl.scope as e:
        body = e.Reg0[e.s]
        for i in range(1, len(region_sets)):
            body = body & getattr(e, f"Reg{i}")[e.s]
        e.CoActive[e.s] = body
        res = nl.query((e.s,), e.CoActive[e.s])
    return sorted(
        {str(row[0]) for row in res.as_pandas_dataframe().itertuples(index=False)}
    )


def _network_coactivation(payload: dict[str, Any]) -> dict[str, Any]:
    """Network query: do regions {A, B, ...} *co-activate* for the term, beyond chance?

    Reports the joint forward inference ``P(all regions peak | term)`` and the
    **co-activation lift** = ``P(joint | term) / Π_i P(region_i | term)`` — >1 means the
    regions co-occur in term-studies more than independent activation predicts (an
    integration / network signal), ~1 means they are independently recruited. The joint
    set is carved by a multi-region Datalog conjunction (the multi-hop join).
    """
    from functools import reduce

    term = [str(s) for s in payload.get("term_studies", [])]
    region_map = {
        k: [str(s) for s in v] for k, v in (payload.get("region_studies") or {}).items()
    }
    alls = [str(s) for s in payload.get("all_studies", [])] or term
    if not term or len(region_map) < 2:
        return {
            "ok": True,
            "p_joint_given_term": None,
            "p_joint": None,
            "joint_forward_lift": None,
            "coactivation_lift": None,
            "per_region_given_term": {},
            "n_term": len(term),
            "n_joint": 0,
            "n_total": len(alls),
            "regions": list(region_map),
            "note": "need a term and at least two regions",
        }

    joint = set(_joint_via_datalog(list(region_map.values())))
    p_joint_term = _marginal_over_uniform_studies(term, joint)
    p_joint_base = _marginal_over_uniform_studies(alls, joint)
    per_region = {
        k: _marginal_over_uniform_studies(term, set(v)) for k, v in region_map.items()
    }
    indep = reduce(lambda a, b: a * b, per_region.values(), 1.0)
    return {
        "ok": True,
        "p_joint_given_term": p_joint_term,
        "p_joint": p_joint_base,
        "joint_forward_lift": (p_joint_term / p_joint_base) if p_joint_base else None,
        "coactivation_lift": (p_joint_term / indep) if indep > 0 else None,
        "per_region_given_term": per_region,
        "expected_if_independent": indep,
        "n_term": len(term),
        "n_joint": len(joint),
        "n_total": len(alls),
        "regions": list(region_map),
    }


_QUERIES = {
    "forward_inference": _forward_inference,
    "compositional_forward": _compositional_forward,
    "network_coactivation": _network_coactivation,
}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:  # noqa: BLE001 - report any parse failure as a clean verdict
        json.dump({"ok": False, "error": f"bad stdin json: {exc}"}, sys.stdout)
        return 0
    qname = str(payload.get("query", "forward_inference"))
    fn = _QUERIES.get(qname)
    if fn is None:
        json.dump({"ok": False, "error": f"unknown query {qname!r}"}, sys.stdout)
        return 0
    try:
        import neurolang

        out = fn(payload)
        out["neurolang_version"] = getattr(neurolang, "__version__", "?")
        json.dump(out, sys.stdout)
    except Exception as exc:  # noqa: BLE001 - never crash; surface as unavailable
        json.dump({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
