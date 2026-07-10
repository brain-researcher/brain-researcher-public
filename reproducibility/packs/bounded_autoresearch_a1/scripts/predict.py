"""Baseline predict.py — deterministic Liu-style nested-CV Ridge, Path A.

This file is the agent's lab notebook. Only this file may be edited inside
the autoresearch loop. ``run.py`` is immutable.

Current shipped baseline
------------------------
- One term: ``cov_EmpiricalCovariance`` (Liu's term_0).
- QCoD feature filter: keep edges whose per-edge QCoD falls inside the
  [10, 90] percentile band of that term's QCoD distribution (matches Liu).
- Model family: Ridge with Liu's alpha grid ``[0.1, 1, 10, 100]``.
- Inner selection: per-component 10-fold CV on the TRAIN split only.
- Determinism: inner CV uses ``random_state=42`` (Liu shuffled unseeded).

Agent interface — Path A (do NOT remove unless switching to Path B)
-------------------------------------------------------------------
- ``get_config() -> dict`` — config snapshot logged per run.
- ``build_features(loader, subject_idx) -> np.ndarray`` — rows indexed by
  ``subject_idx`` over the original 326-subject array.
- ``build_model()`` — returns a fresh sklearn-compatible estimator with
  ``fit(X, Y)`` / ``predict(X)``.

QCoD is computed from the full 326-subject X matrix for this term, matching
Liu's data-prep script. It never sees Y.
"""
from __future__ import annotations

import json
import os

import numpy as np
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.kernel_ridge import KernelRidge
from sklearn.linear_model import Ridge
from sklearn.model_selection import GridSearchCV, KFold
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# Iter 6 diagnostic: pin BLAS threads so the MLP probe is deterministic across
# alt-seed sweeps. sklearn MLPRegressor uses BLAS under the hood; leaving
# threads unpinned can produce non-reproducible convergence across runs.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")


_EXCHANGEABILITY_CACHE: dict[str, list[str]] = {}


def _family_ids_by_index() -> list[str]:
    manifest_path = os.getenv("LIU_EXCHANGEABILITY_MANIFEST", "")
    if not manifest_path:
        raise ValueError(
            "LIU_EXCHANGEABILITY_MANIFEST must be set for "
            "LIU_FAMILY_BLOCK_PERMUTE_Y"
        )
    if manifest_path not in _EXCHANGEABILITY_CACHE:
        with open(manifest_path) as handle:
            payload = json.load(handle)
        subjects = sorted(payload["subjects"], key=lambda row: int(row["index"]))
        _EXCHANGEABILITY_CACHE[manifest_path] = [
            str(row["family_id"]) for row in subjects
        ]
    return _EXCHANGEABILITY_CACHE[manifest_path]


def _family_block_permutation_order(
    train_idx: np.ndarray,
    *,
    seed: int,
    fold_id: int,
) -> np.ndarray:
    family_ids = _family_ids_by_index()
    family_to_positions: dict[str, list[int]] = {}
    for pos, global_idx in enumerate(map(int, train_idx)):
        family_to_positions.setdefault(family_ids[global_idx], []).append(pos)

    blocks_by_size: dict[int, list[list[int]]] = {}
    for positions in family_to_positions.values():
        blocks_by_size.setdefault(len(positions), []).append(sorted(positions))

    rng = np.random.default_rng(seed * 1_000_000 + int(fold_id))
    order = np.arange(len(train_idx), dtype=np.int64)
    for blocks in blocks_by_size.values():
        if len(blocks) < 2:
            continue
        source_order = rng.permutation(len(blocks))
        for dest_block, source_idx in zip(blocks, source_order):
            source_block = blocks[int(source_idx)]
            order[dest_block] = source_block
    return order


BASELINE_TERM = "cov_EmpiricalCovariance"
# Iter 25 feature_engineering: route prec ONLY to Cognition (k=0).
# Iter 24 disambiguated the iter-23 collapse: adding prec to PE (k=2)
# under K=40 in a 150-PC pool deterministically re-ranks PE away from
# the iter-19 dcorr winners (PE 0.1191 -> 0.0466), while Cognition gains
# +0.0503 and is component-local (K=40 in 150-PC pool with prec). Iter 25
# reverts PE to [cov, dcorr]; Cognition keeps [cov, dcorr, prec]. All other
# components stay on iter-19 shipping TERMS=[cov, dcorr]. Pre-registered
# branches (iter-24 next_hypothesis): (a) Cognition >=0.33 AND PE >=0.084
# AND 5/5 hit_mean -> agg >0.173 makes prec-to-Cognition-only the shipping
# config; (b) Cognition drops <0.33 -> iter-23/24 gain depended on PE's
# feature cache sharing an X_train_std matrix; (c) PE recovers to >=0.084
# but Cognition drops -> prec-to-Cognition is component-local but probe-
# state coupled with PE. Module-level TERMS is the UNION of all routes,
# used only to build a per-term feature block pool; predict_fold picks
# the per-component subset via PER_COMPONENT_TERMS. Path A still uses
# TERMS as-is (union) as a fallback only.
TERMS = ["cov_EmpiricalCovariance", "dcorr", "prec_GraphicalLassoCV"]
# Per-component term routing. Keys are component indices matching
# run.COMPONENT_ORDER:
#   0 ICA_Cognition, 1 ICA_TobaccoUse, 2 ICA_PersonalityEmotion,
#   3 ICA_IllicitDrugUse, 4 ICA_MentalHealth.
# Values list the terms each component's feature block should contain.
# None disables per-component routing (use module-level TERMS for all).
PER_COMPONENT_TERMS: dict[int, list[str]] | None = {
    0: ["cov_EmpiricalCovariance", "dcorr", "prec_GraphicalLassoCV"],
    1: ["cov_EmpiricalCovariance", "dcorr"],
    # Iter 8 swap_metric (pre-registered from iter-7 next_hypothesis): add
    # cov back to PE (k=2) routing so PE sees [cov, dcorr, prec] at K=80.
    # Iter 7 established PE=0.1453 with [prec, dcorr] K=80 (a +0.027 jump
    # over iter-3 [cov, dcorr] K=80 PE=0.1182), demonstrating the iter-5
    # PE gain was primarily a metric-routing effect, not MLP capacity.
    # This iter probes capacity-via-terms on the model_scaling axis: does
    # the union pool (cov+dcorr+prec) at K=80 exceed the iter-7 [prec,dcorr]
    # K=80 PE=0.1453? If PE >= 0.15, prec is additive to cov+dcorr; if PE
    # < 0.145, cov edges in the 150-PC pool compete for K=80 slots and
    # displace useful prec/dcorr PCs (i.e. the 100-PC [prec,dcorr] basis
    # is the right capacity envelope for PE under Ridge).
    # Iter 9 tune_hyperparameter (pre-registered from iter-8 next_hypothesis):
    # revert PE (k=2) routing to [prec, dcorr] (iter-7 config, PE=0.1453 @ K=80)
    # and sweep PE K in {40, 60, 100} to test within-term capacity saturation
    # under Ridge on the 100-PC [prec, dcorr] basis. If PE peaks at K=100
    # (all PCs), within-term capacity is NOT saturated and the next move is a
    # model-family swap (kernelize / mlp_probe) on [prec, dcorr] K=100. If PE
    # peaks at K<=80, within-term capacity IS saturated and model_scaling
    # needs a family swap on [prec, dcorr] K<=80.
    2: ["prec_GraphicalLassoCV", "dcorr"],
    3: ["cov_EmpiricalCovariance", "dcorr"],
    4: ["cov_EmpiricalCovariance", "dcorr"],
}
QCOD_LOW_PCT = 10.0
QCOD_HIGH_PCT = 90.0
MODEL_KIND = "nested_ridge"
# Iter 17 tune_hyperparameter: revert RIDGE_ALPHA_GRID to Liu's canonical
# [0.1, 1, 10, 100] after iter 16's alpha-selection dump confirmed weak
# targets drift into alpha={1000, 10000} and over-shrink (agg -0.004, weak
# targets -0.010/-0.011). The operative alpha set under this pipeline is
# {100, 1000}; removing {1000, 10000} closes the weak-target over-shrinkage
# channel. The K-vs-alpha interchangeability hypothesis is tested by the
# per-component K config below.
RIDGE_ALPHA_GRID = [0.1, 1.0, 10.0, 100.0]
INNER_CV_SPLITS = 10
# Iter 12 alt-seed validation: expose inner-CV seed via env var so we can
# re-run the iter-11 MLP-on-PE config under seeds {7, 13, 21} without
# touching the fold-split seed (still 42 in run.py's fold_manifest).
INNER_CV_RANDOM_STATE = int(os.getenv("LIU_INNER_CV_SEED", "42"))
INNER_CV_N_JOBS = int(os.getenv("LIU_INNER_CV_N_JOBS", "-1"))
PCA_COMPONENTS: int | None = None
# Per-term PCA applied in build_features on the full 326-subject matrix (X-only,
# same leakage class as QCoD). Equalizes dimensionality across TERMS so one
# metric cannot swamp another after concatenation. None = disabled.
PER_TERM_PCA: int | None = 50

# Path B per-component PC routing: select top-K PCs per component via a
# fold-local ridge probe at PROBE_ALPHA, then fit a nested-CV Ridge only on
# those PCs. Feature ranking is computed on each fold's TRAIN split only, so
# this does not leak across folds (leakage class: y-informed but fold-local,
# same class as the inner alpha selection).
PER_COMPONENT_TOPK = 40
PROBE_ALPHA = 100.0
# Iter 29 tune_hyperparameter confirmed K=60 as Cognition's local optimum
# in the 150-PC single-pool competition (cov+dcorr+prec). Iter 30 feature_
# selection tests whether allocating K evenly per term (top-20 cov + top-20
# dcorr + top-20 prec = 60 PCs) beats letting 150 PCs compete for 60 slots.
# Single-pool competition may under-represent weaker-probe terms (e.g. prec
# supplied only 6-8 PCs to iter-27's K=80 selection by bucket-mean tails).
# All other components stay on iter-26 shipping K (TobaccoUse / PE /
# IllicitDrug K=40 on a 100-PC [cov, dcorr] pool, MentalHealth K=20).
# Component order matches run.COMPONENT_ORDER:
#   0 ICA_Cognition, 1 ICA_TobaccoUse, 2 ICA_PersonalityEmotion,
#   3 ICA_IllicitDrugUse, 4 ICA_MentalHealth.
PER_COMPONENT_TOPK_BY_COMPONENT: dict[int, int] | None = {
    0: 60,
    1: 40,
    2: 100,
    3: 40,
    4: 20,
}
# Iter 31 feature_selection: per-term probe ranking (Cognition only),
# pushed to K=27 per term -> 81 PCs total, probing capacity at no-
# competition allocation. Context: outputs/iter31_allocation_dump.json
# shows iter-29's single-pool top-60 is actually PREC-HEAVY, not (20,20,20):
# cov=18.4+-1.4, dcorr=17.6+-1.3, prec=24.0+-1.8 across 10 folds. So iter-30
# per-term top-20 was strictly REDUCING prec from 24->20, explaining the
# near-null -0.00066 Cognition delta. Iter 31 tests the reverse: force-boost
# cov/dcorr to 27 each (up +9 from iter-29) while letting prec go to 27
# (up +3 from iter-29), total +21 PCs of capacity.
# Pre-registered branches (iter 30 next_hypothesis):
#  (a) Cognition >= 0.385 -> per-term K=27 beats iter-29 K=60 single-pool;
#      ship it, iter 32 dumps final allocation + PIVOTs to hard targets.
#  (b) 0.375 <= Cog < 0.385 -> per-term K=81 is orthogonal-null too;
#      formally close the Cognition K/allocation/routing sweep and iter 32
#      PIVOTs to PE/MH/IllicitDrug bottlenecks.
#  (c) Cog < 0.375 -> per-term K=81 under-fits (cov/dcorr PCs 20-27 are
#      noise-dominated); revert to K=60 single-pool, iter 32 PIVOTs per (b).
# Other components unchanged: Tobacco/PE/IllicitDrug K=40, MH K=20 on
# single-pool [cov, dcorr] 100-PC basis.
PER_COMPONENT_PER_TERM_TOPK: dict[int, int] | None = None
PROBE_MODE = "topk"  # one of {"topk", "random"}
RANDOM_PROBE_SEED = 202604161  # ignored unless PROBE_MODE == "random"

# Iter 23 combine_metrics: revert MODEL_HEAD to "ridge" after iter 22's
# pre-registered RBF falsification (every component regressed under RBF
# vs iter-19 Ridge by 0.003-0.014 fold_mean_r). The Cognition / TobaccoUse
# bottleneck is not a linear-vs-nonlinear head issue, so the iter-23 move
# is to extend TERMS with prec_GraphicalLassoCV under Ridge.
#
# MODEL_HEAD one of {"ridge", "kernel_ridge_rbf"}.
MODEL_HEAD = "ridge"
# Iter 2 model_scaling line (kernelize): route a KernelRidge (RBF) head to
# PersonalityEmotion (k=2) ONLY. Other components keep the linear Ridge head
# so any PE gain is attributable to the kernel head, not a multi-component
# policy change. Keys are component indices matching run.COMPONENT_ORDER.
# None disables per-component routing (module-level MODEL_HEAD applies).
# Iter 6 diagnostic (disentangle iter-5 confound): swap PE head from
# kernel_ridge_rbf -> mlp while holding the parent-frozen per-component
# routing and K constant. Iter 5 bundled an MLP head AND a metric-routing
# change (Cog->prec-only, Tob/IllicitDrug/MH->dcorr-only, PE->prec+dcorr)
# so the PE=0.1613 gain and the MH=0.0415 collapse cannot be cleanly
# attributed. By routing MLP only on PE (k=2) over the same top-K=80
# cov+dcorr PC subset used in iter 3/4 (PE=0.1182/0.1212), we isolate
# the capacity-family effect.
# Iter 7 swap_metric: restore Ridge head on PE to isolate the metric-routing
# contribution (see PER_COMPONENT_TERMS[2] comment above).
# Iter 10 kernelize (model_scaling, pre-registered from iter-9 next_hypothesis):
# route a KernelRidge (RBF) head to PE (k=2) ONLY, holding PE on [prec, dcorr]
# K=100 (the iter-9 line-best basis at PE=0.1574). Other 4 components keep
# linear Ridge head and parent-frozen routing/K. Any PE delta is therefore
# attributable to the head family (ridge -> kernel_ridge_rbf), not to a
# multi-component policy or basis change. Pre-registered branches:
#   PE >= 0.17 -> kernel head buys real headroom; iter 11 tests MLP as a
#                 cross-family check.
#   0.15 <= PE < 0.17 -> RBF is a lateral move; ridge K=100 is the PE ceiling
#                 under model_scaling at this basis.
#   PE < 0.15 -> kernel worse than linear; iter 11 pivots to mlp_probe.
# Iter 13 diagnostic (parent-family alt-seed robustness baseline, pre-registered
# in iter-12 next_hypothesis): disable per-component MLP head on PE so PE falls
# back to the shared Ridge head, while holding the per-component [prec, dcorr]
# K=100 PE routing constant from iter 11/12. Re-run under LIU_INNER_CV_SEED in
# {42, 7, 13, 21} to measure parent-family alt-seed PE variance under sparse
# Ridge on this fresh workspace. If parent-Ridge alt-seed PE mean / range is
# comparable to the parent line's (~0.107 / ~0.053), the MLP capacity gain at
# seed=42 is confirmed seed-specific and the NEGATIVE stop criterion triggers.
# Iter 15 swap_model (module action: swap_model_family, tree ensemble):
# route a RandomForestRegressor head to PE (k=2) ONLY as the third
# cross-family capacity probe requested by the iter-14 BR reviewer
# feedback (the textual NEGATIVE stop requires 3+ consecutive
# cross-family failures; iters 10/11 only supplied kernel RBF + MLP, so
# a tree-ensemble probe is the one family left to rule out before
# closeout). Hold PE basis constant at [prec, dcorr] K=100 (iter-9 line-
# best basis at PE=0.1574) so any PE delta is attributable purely to the
# head family (ridge -> random_forest). Other 4 components remain on the
# shared Ridge head + parent-frozen routing.
# Pre-registered branches:
#   PE seed=42 >= 0.17 AND iter-9 Ridge basis (0.1574) beaten -> RF
#       buys real headroom; next iter does alt-seed robustness on RF.
#   0.15 <= PE < 0.17 -> RF is a lateral move; a third family is now on
#       record as failing the 0.18/alt-seed 0.14 positive stop and the
#       negative stop criterion textually triggers.
#   PE < 0.15 -> RF worse than linear; same conclusion, stronger form.
# Iter 16 final_report: revert to shipping shared-Ridge head on all 5
# components (iter-9 line-best config at PE=0.1574, 5/5 hit_mean). The
# iter-15 RF probe completed the 3-family cross-family tally (iter-10 RBF,
# iter-11 MLP, iter-15 RF) with PE seed=42 = 0.0286 -- RF regressed
# -0.129 vs iter-9 Ridge on the same basis and -0.091 vs the parent
# baseline 0.119. With all 3 nonlinear head families falsified on PE under
# seed=42 and kernel/MLP separately falsified under alt-seed (iter 12 MLP
# alt-seed mean 0.083 < parent Ridge alt-seed mean 0.107), the negative
# stop criterion triggers.
PER_COMPONENT_MODEL_HEAD: dict[int, str] | None = None
# Random forest hyperparameter grid: shallow-to-moderate depth + moderate
# tree count, nested-CV searched. Small enough to stay <90s on CPU given
# K=100 input dim and 326 subjects.
RF_N_ESTIMATORS_GRID = [200, 500]
RF_MAX_DEPTH_GRID = [4, 8, None]
RF_RANDOM_STATE = int(os.getenv("LIU_RF_SEED", "42"))
# Gamma grid centered on 1/K ~ 1/40 = 0.025 (strong targets) to 1/20 = 0.05
# (MentalHealth). Span a decade either side to let nested CV pick per fold.
KERNEL_RIDGE_GAMMA_GRID = [0.001, 0.005, 0.025, 0.125, 0.5, 2.0]
# Iter 6 MLP probe hyperparameters (shallow 1-hidden-layer, tight L2, early
# stopping at 15% internal val split, fixed seed). Nested CV picks across
# hidden width x alpha.
MLP_HIDDEN_GRID = [(32,), (64,), (128,)]
MLP_ALPHA_GRID = [1e-3, 1e-2, 1e-1]
MLP_MAX_ITER = 500
# Iter 12 alt-seed validation: expose MLP random state via env var so MLP
# weight init / SGD ordering changes jointly with INNER_CV seed.
MLP_RANDOM_STATE = int(os.getenv("LIU_MLP_SEED", "42"))


def get_config() -> dict:
    feature_selection = "qcod_10_90"
    if PER_TERM_PCA is not None:
        feature_selection = f"{feature_selection}+per_term_pca_{PER_TERM_PCA}"
    if PCA_COMPONENTS is not None:
        feature_selection = f"{feature_selection}+pca_{PCA_COMPONENTS}"
    if PER_COMPONENT_TERMS is not None:
        feature_selection = f"{feature_selection}+per_component_terms"
    if PROBE_MODE == "random":
        feature_selection = (
            f"{feature_selection}+per_component_randomk_{PER_COMPONENT_TOPK}"
        )
        description = (
            "Path B per-component RANDOM-K PC selection (iter 12 diagnostic): "
            "K PCs drawn uniformly per (fold, component) with a dedicated "
            "seed; same downstream nested-CV Ridge as iter 11."
        )
        model_name = "PerComponentRandomKRidge"
    elif PER_COMPONENT_TOPK_BY_COMPONENT:
        k_tag = "_".join(
            str(PER_COMPONENT_TOPK_BY_COMPONENT[k])
            for k in sorted(PER_COMPONENT_TOPK_BY_COMPONENT)
        )
        feature_selection = (
            f"{feature_selection}+per_component_topk_by_component_{k_tag}"
        )
        if MODEL_HEAD == "kernel_ridge_rbf":
            description = (
                "Iter 22 swap_model: Path B per-component PC routing with "
                "K={40,40,40,40,20} (iter-19 shipped baseline) and a "
                "KernelRidge (RBF) head replacing the linear Ridge head. "
                "Test whether a nonlinear head buys >=0.02 fold_mean_r on "
                "Cognition / TobaccoUse toward ref_best_r."
            )
            model_name = "PerComponentTopKByComponentKernelRidgeRBF"
        elif PER_COMPONENT_TERMS is not None:
            if PER_COMPONENT_PER_TERM_TOPK:
                pt_tag = "_".join(
                    f"{kk}@{PER_COMPONENT_PER_TERM_TOPK[kk]}"
                    for kk in sorted(PER_COMPONENT_PER_TERM_TOPK)
                )
                feature_selection = (
                    f"{feature_selection}+per_component_per_term_topk_{pt_tag}"
                )
                description = (
                    "Iter 31 feature_selection: per-term probe ranking on "
                    "Cognition (k=0) pushed to K=27 per term (total 81) to "
                    "test capacity at no-competition allocation. Iter-29's "
                    "single-pool top-60 was prec-heavy (cov 18.4, dcorr 17.6, "
                    "prec 24.0 across folds); per-term K=27 boosts cov+dcorr "
                    "by +9 each while letting prec extend to 27. Other "
                    "components keep iter-26 single-pool top-K={40,40,40,20}."
                )
                model_name = "PerComponentTermsPerTermTopKRidge"
            else:
                if PER_COMPONENT_MODEL_HEAD and PER_COMPONENT_MODEL_HEAD.get(2) == "kernel_ridge_rbf":
                    description = (
                        "Iter 2 model_scaling kernelize: per-component head "
                        "routing, KernelRidge (RBF) on PE (k=2) over existing "
                        "top-K=40 cov+dcorr PC subset, nested CV over "
                        "alpha x gamma grids. Other 4 components keep linear "
                        "Ridge head on parent-frozen per-component routing "
                        "(cov+dcorr+prec on Cognition; cov+dcorr elsewhere; "
                        "K={60,40,40,40,20})."
                    )
                    model_name = "PerComponentTermsTopKByComponentRidge_PE_KernelRBF"
                elif PER_COMPONENT_MODEL_HEAD and PER_COMPONENT_MODEL_HEAD.get(2) == "mlp":
                    description = (
                        "Iter 6 diagnostic (mlp_probe disentangled): MLP head "
                        "on PE (k=2) over parent-frozen cov+dcorr top-K=80 PC "
                        "subset; other 4 components unchanged Ridge heads on "
                        "parent-frozen routing (K={60,40,80,40,20}; Cognition "
                        "cov+dcorr+prec; rest cov+dcorr). Isolates MLP vs "
                        "iter-5's bundled metric-routing change so PE gain "
                        "and MH collapse are separately attributable."
                    )
                    model_name = "PerComponentTermsTopKByComponentRidge_PE_MLP"
                else:
                    description = (
                        "Iter 8 swap_metric: PE (k=2) routed to [cov, dcorr, "
                        "prec] at K=80 under Ridge (pre-registered from iter-7 "
                        "next_hypothesis). Iter 7 established PE=0.1453 with "
                        "[prec, dcorr] K=80, +0.027 over iter-3 [cov, dcorr] "
                        "K=80 PE=0.1182. This iter tests capacity-via-terms: "
                        "union pool (150 PCs) at K=80 vs [prec,dcorr] (100 PCs) "
                        "at K=80. Other components unchanged: Cog [cov,dcorr,"
                        "prec] K=60; Tob/IllicitDrug [cov,dcorr] K=40; "
                        "MentalHealth [cov,dcorr] K=20."
                    )
                    model_name = "PerComponentTermsTopKByComponentRidge"
        else:
            description = (
                "Path B per-component PC routing with per-component K "
                "(iter-19 shipped): strong targets K=40, MentalHealth K=20, "
                "IllicitDrug K=40."
            )
            model_name = "PerComponentTopKByComponentRidge"
    else:
        feature_selection = (
            f"{feature_selection}+per_component_topk_{PER_COMPONENT_TOPK}"
        )
        description = (
            "Path B per-component PC routing: top-K PCs selected via "
            "fold-local ridge probe, then nested-CV Ridge per component."
        )
        model_name = "PerComponentTopKRidge"
    return {
        "description": description,
        "path": "B",
        "terms": TERMS,
        "fc_metric": TERMS[0] if len(TERMS) == 1 else "+".join(TERMS),
        "parcellation": "schaefer100x7",
        "feature_selection": feature_selection,
        "scaler": "StandardScaler",
        "model": model_name,
        "alpha_grid": RIDGE_ALPHA_GRID,
        "inner_cv_splits": INNER_CV_SPLITS,
        "inner_cv_random_state": INNER_CV_RANDOM_STATE,
        "inner_cv_n_jobs": INNER_CV_N_JOBS,
        "pca_components": PCA_COMPONENTS,
        "per_term_pca": PER_TERM_PCA,
        "per_component_topk": PER_COMPONENT_TOPK,
        "per_component_topk_by_component": (
            dict(PER_COMPONENT_TOPK_BY_COMPONENT)
            if PER_COMPONENT_TOPK_BY_COMPONENT
            else None
        ),
        "per_component_terms": (
            {str(k): list(v) for k, v in PER_COMPONENT_TERMS.items()}
            if PER_COMPONENT_TERMS is not None
            else None
        ),
        "per_component_per_term_topk": (
            {str(k): int(v) for k, v in PER_COMPONENT_PER_TERM_TOPK.items()}
            if PER_COMPONENT_PER_TERM_TOPK
            else None
        ),
        "probe_alpha": PROBE_ALPHA,
        "probe_mode": PROBE_MODE,
        "random_probe_seed": RANDOM_PROBE_SEED if PROBE_MODE == "random" else None,
        "multi_output": True,
        "kg_integration_mode": "none",
        "model_head": MODEL_HEAD,
        "per_component_model_head": (
            {str(k): v for k, v in PER_COMPONENT_MODEL_HEAD.items()}
            if PER_COMPONENT_MODEL_HEAD
            else None
        ),
        "kernel_ridge_gamma_grid": (
            list(KERNEL_RIDGE_GAMMA_GRID)
            if (
                MODEL_HEAD == "kernel_ridge_rbf"
                or (
                    PER_COMPONENT_MODEL_HEAD
                    and any(v == "kernel_ridge_rbf" for v in PER_COMPONENT_MODEL_HEAD.values())
                )
            )
            else None
        ),
    }


def _qcod(mat: np.ndarray) -> np.ndarray:
    q1, q3 = np.nanpercentile(mat, [25, 75], axis=0)
    upper = (q3 - q1) / 2.0
    lower = (q1 + q3) / 2.0
    with np.errstate(divide="ignore", invalid="ignore"):
        return upper / lower


def _qcod_mask(term_mat: np.ndarray) -> np.ndarray:
    qcod = _qcod(term_mat)
    low, high = np.nanpercentile(qcod, [QCOD_LOW_PCT, QCOD_HIGH_PCT])
    return np.where((qcod >= low) & (qcod <= high))[0]


# Iter 1 (this line) perf cache: per-term QCoD-mask + per-term PCA embedding
# is X-only (no fold/subject dependence). On a cold workspace the harness's
# 300s wall-budget was overrun by recomputing these per fold/term-tuple. Cache
# is keyed by (term_name, n_components, qcod_lo, qcod_hi) so any change to
# those knobs invalidates correctly. Outputs are bit-identical to no-cache.
_PER_TERM_PCA_CACHE: dict[tuple, np.ndarray] = {}
_QCOD_MASK_CACHE: dict[tuple, np.ndarray] = {}


def _per_term_pca_full(X_full: np.ndarray, n_components: int) -> np.ndarray:
    """Fit PCA on the full 326-subject X-only matrix and return the embedding.

    X-only, does not see y; same leakage class as QCoD per loop contract.
    NaNs are imputed column-mean before standardization.
    """
    col_mean = np.nanmean(X_full, axis=0)
    X_imp = np.where(np.isnan(X_full), col_mean, X_full)
    mu = X_imp.mean(axis=0, keepdims=True)
    sd = X_imp.std(axis=0, ddof=0, keepdims=True)
    sd = np.where(sd == 0.0, 1.0, sd)
    X_std = (X_imp - mu) / sd
    n_comp = int(min(n_components, X_std.shape[0] - 1, X_std.shape[1]))
    pca = PCA(n_components=n_comp, random_state=INNER_CV_RANDOM_STATE)
    return pca.fit_transform(X_std)


def build_features(
    loader,
    subject_idx: np.ndarray,
    terms: list[str] | None = None,
) -> np.ndarray:
    """Return (len(subject_idx), n_features) for the configured term set.

    When PER_TERM_PCA is set, each term is QCoD-filtered, then reduced via
    per-term PCA fit on the full 326-subject matrix (X-only), then concatenated.
    Equalizes dimensionality so a high-dim metric cannot swamp a lower-signal one.

    ``terms`` overrides the module-level ``TERMS`` (used by predict_fold for
    component-specific term routing). When ``terms`` is None, falls back to
    the module-level union TERMS, matching the Path A contract.
    """
    term_list = list(TERMS if terms is None else terms)
    blocks = []
    for term_name in term_list:
        if PER_TERM_PCA is not None:
            cache_key = (term_name, int(PER_TERM_PCA), QCOD_LOW_PCT, QCOD_HIGH_PCT)
            emb = _PER_TERM_PCA_CACHE.get(cache_key)
            if emb is None:
                term_mat = loader.load(term_name)
                mask = _qcod_mask(term_mat)
                emb = _per_term_pca_full(term_mat[:, mask], PER_TERM_PCA)
                _PER_TERM_PCA_CACHE[cache_key] = emb
            blocks.append(emb[subject_idx])
        else:
            term_mat = loader.load(term_name)
            mask = _qcod_mask(term_mat)
            blocks.append(term_mat[:, mask][subject_idx])
    return np.concatenate(blocks, axis=1)


class LiuNestedRidgeRegressor:
    """Per-target inner-CV Ridge wrapper approximating Liu's protocol."""

    def __init__(
        self,
        alpha_grid: list[float] | None = None,
        n_splits: int = INNER_CV_SPLITS,
        random_state: int = INNER_CV_RANDOM_STATE,
    ) -> None:
        self.alpha_grid = list(alpha_grid or RIDGE_ALPHA_GRID)
        self.n_splits = n_splits
        self.random_state = random_state

    def _make_search(self) -> GridSearchCV:
        inner_cv = KFold(
            n_splits=self.n_splits,
            shuffle=True,
            random_state=self.random_state,
        )
        steps: list[tuple[str, object]] = [
            ("impute", SimpleImputer(strategy="mean")),
            ("scale", StandardScaler()),
        ]
        if PCA_COMPONENTS is not None:
            steps.append(("pca", PCA(n_components=PCA_COMPONENTS)))
        steps.append(("ridge", Ridge(solver="auto")))
        pipeline = Pipeline(steps=steps)
        return GridSearchCV(
            estimator=pipeline,
            param_grid={"ridge__alpha": self.alpha_grid},
            cv=inner_cv,
            scoring=None,
            refit=True,
            n_jobs=INNER_CV_N_JOBS,
        )

    def fit(self, X: np.ndarray, Y: np.ndarray):
        X = np.asarray(X, dtype=np.float64)
        Y = np.asarray(Y, dtype=np.float64)
        if Y.ndim == 1:
            Y = Y[:, None]

        self.models_: list[Pipeline] = []
        self.best_alphas_: list[float] = []
        self.n_outputs_ = Y.shape[1]
        for col in range(self.n_outputs_):
            search = self._make_search()
            search.fit(X, Y[:, col])
            self.models_.append(search.best_estimator_)
            self.best_alphas_.append(float(search.best_params_["ridge__alpha"]))
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=np.float64)
        if not hasattr(self, "models_"):
            raise RuntimeError("Estimator must be fit before predict().")
        preds = [np.asarray(model.predict(X), dtype=np.float64) for model in self.models_]
        return np.column_stack(preds)


def build_model():
    return LiuNestedRidgeRegressor()


# ---------------------------------------------------------------------------
# Path B: per-component top-K PC routing
# ---------------------------------------------------------------------------
def predict_fold(
    loader,
    train_idx: np.ndarray,
    test_idx: np.ndarray,
    y_train: np.ndarray,
    fold_id: int,
) -> np.ndarray:
    """Return y_pred of shape (len(test_idx), 5).

    For each component k:
      1. Build the iter-7 feature space (QCoD + per_term_PCA).
      2. Impute + standardize on train only.
      3. Fit a probe Ridge at PROBE_ALPHA on train to rank PCs by |coef|.
      4. Select the top-K PC indices.
      5. Fit nested-CV Ridge (RIDGE_ALPHA_GRID) on those PCs.
      6. Predict test.

    All fold-aware fitting happens inside predict_fold; only QCoD / per-term
    PCA are X-only full-matrix stats (same leakage class as Path A).
    """
    y_train = np.asarray(y_train, dtype=np.float64)
    if y_train.ndim == 1:
        y_train = y_train[:, None]
    # Data-scaling line: subsample train subjects to LIU_TRAIN_N per fold for
    # learning-curve sweeps. Test split is never touched, so fold-level Pearson r
    # stays comparable across N. Seed (LIU_SUBSAMPLE_SEED) combined with fold_id.
    _sub_n = os.getenv("LIU_TRAIN_N", "")
    _sub_seed = os.getenv("LIU_SUBSAMPLE_SEED", "")
    if _sub_n and _sub_seed:
        _n_target = int(_sub_n)
        if 0 < _n_target < len(train_idx):
            _rng_sub = np.random.default_rng(int(_sub_seed) * 1000 + int(fold_id))
            _sel = _rng_sub.choice(len(train_idx), size=_n_target, replace=False)
            train_idx = train_idx[_sel]
            y_train = y_train[_sel]
    # Family-aware confirmatory null. This is more conservative than the
    # ordinary shared row shuffle: it permutes whole Family_ID blocks among
    # blocks of the same within-training-fold size, preserving family clustering
    # in the target matrix while breaking feature-label pairing.
    _family_perm_seed = os.getenv("LIU_FAMILY_BLOCK_PERMUTE_Y", "")
    if _family_perm_seed:
        _order = _family_block_permutation_order(
            train_idx,
            seed=int(_family_perm_seed),
            fold_id=int(fold_id),
        )
        y_train = y_train[_order, :]

    # Confirmatory y-permutation null.
    # LIU_SHARED_PERMUTE_Y applies one row permutation to the 5-component
    # target matrix within each training fold, preserving target covariance
    # while breaking the feature-label pairing. This is the publication-grade
    # shared label-shuffle null used for aggregate and max-T p-values.
    _shared_perm_seed = os.getenv("LIU_SHARED_PERMUTE_Y", "")
    if _shared_perm_seed and not _family_perm_seed:
        _rng = np.random.default_rng(
            int(_shared_perm_seed) * 1_000_000 + int(fold_id)
        )
        y_train = y_train[_rng.permutation(y_train.shape[0]), :]

    # Backward-compatible diagnostic null used by earlier autoresearch lines.
    # Gated by LIU_PERMUTE_Y env var; when set, independently permute y_train
    # per component and fold with a seed tied to (LIU_PERMUTE_Y, fold_id, k).
    # y_test is never touched; this gives a component-wise permutation null.
    _perm_seed = os.getenv("LIU_PERMUTE_Y", "")
    if _perm_seed and not _shared_perm_seed and not _family_perm_seed:
        _base = int(_perm_seed)
        y_train = y_train.copy()
        for _k in range(y_train.shape[1]):
            _rng = np.random.default_rng(_base * 1_000_000 + int(fold_id) * 1000 + _k)
            _rng.shuffle(y_train[:, _k])
    n_outputs = y_train.shape[1]
    y_pred = np.zeros((len(test_idx), n_outputs), dtype=np.float64)

    # Build one feature block per unique term-tuple used across components.
    # When PER_COMPONENT_TERMS is None, all components share the union-TERMS
    # block and this reduces to the pre-iter-24 behavior.
    component_terms: dict[int, tuple[str, ...]] = {}
    for k in range(n_outputs):
        if PER_COMPONENT_TERMS is not None and k in PER_COMPONENT_TERMS:
            component_terms[k] = tuple(PER_COMPONENT_TERMS[k])
        else:
            component_terms[k] = tuple(TERMS)

    unique_term_tuples = sorted({t for t in component_terms.values()})
    feature_cache: dict[tuple[str, ...], tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for term_tuple in unique_term_tuples:
        X_tr_raw = build_features(loader, train_idx, terms=list(term_tuple))
        X_te_raw = build_features(loader, test_idx, terms=list(term_tuple))
        X_tr_raw = np.asarray(X_tr_raw, dtype=np.float64)
        X_te_raw = np.asarray(X_te_raw, dtype=np.float64)
        imputer = SimpleImputer(strategy="mean")
        X_tr_imp = imputer.fit_transform(X_tr_raw)
        X_te_imp = imputer.transform(X_te_raw)
        probe_scaler = StandardScaler().fit(X_tr_imp)
        X_tr_std = probe_scaler.transform(X_tr_imp)
        feature_cache[term_tuple] = (X_tr_imp, X_te_imp, X_tr_std)

    for k in range(n_outputs):
        term_tuple = component_terms[k]
        X_train_imp, X_test_imp, X_train_std = feature_cache[term_tuple]
        n_features_total = X_train_std.shape[1]
        if PER_COMPONENT_TOPK_BY_COMPONENT and k in PER_COMPONENT_TOPK_BY_COMPONENT:
            topk = int(min(PER_COMPONENT_TOPK_BY_COMPONENT[k], n_features_total))
        else:
            topk = int(min(PER_COMPONENT_TOPK, n_features_total))
        if PROBE_MODE == "random":
            # Reproducible per (fold_id, component_k); X-only and y-free, so
            # this is strictly a weaker-leakage variant of the iter-11 probe.
            rng = np.random.default_rng(
                int(RANDOM_PROBE_SEED) * 10_000
                + int(fold_id) * 100
                + int(k)
            )
            sel_idx = rng.choice(n_features_total, size=topk, replace=False)
        else:
            probe = Ridge(alpha=PROBE_ALPHA).fit(X_train_std, y_train[:, k])
            abs_coef = np.abs(np.asarray(probe.coef_, dtype=np.float64).ravel())
            if (
                PER_COMPONENT_PER_TERM_TOPK is not None
                and k in PER_COMPONENT_PER_TERM_TOPK
                and PER_TERM_PCA is not None
                and len(term_tuple) > 1
            ):
                per_term_k = int(PER_COMPONENT_PER_TERM_TOPK[k])
                block_size = int(PER_TERM_PCA)
                sel_parts: list[np.ndarray] = []
                for term_i in range(len(term_tuple)):
                    start = term_i * block_size
                    stop = min(start + block_size, n_features_total)
                    if stop <= start:
                        continue
                    local_abs = abs_coef[start:stop]
                    local_k = int(min(per_term_k, stop - start))
                    local_order = np.argsort(local_abs)[::-1][:local_k]
                    sel_parts.append(local_order + start)
                sel_idx = np.concatenate(sel_parts) if sel_parts else np.array([], dtype=int)
            else:
                sel_idx = np.argsort(abs_coef)[::-1][:topk]

        X_tr_sub = X_train_imp[:, sel_idx]
        X_te_sub = X_test_imp[:, sel_idx]

        inner_cv = KFold(
            n_splits=INNER_CV_SPLITS,
            shuffle=True,
            random_state=INNER_CV_RANDOM_STATE,
        )
        head_k = MODEL_HEAD
        if PER_COMPONENT_MODEL_HEAD and k in PER_COMPONENT_MODEL_HEAD:
            head_k = PER_COMPONENT_MODEL_HEAD[k]
        if head_k == "kernel_ridge_rbf":
            pipeline = Pipeline(
                steps=[
                    ("scale", StandardScaler()),
                    ("kridge", KernelRidge(kernel="rbf")),
                ]
            )
            param_grid = {
                "kridge__alpha": RIDGE_ALPHA_GRID,
                "kridge__gamma": KERNEL_RIDGE_GAMMA_GRID,
            }
        elif head_k == "mlp":
            pipeline = Pipeline(
                steps=[
                    ("scale", StandardScaler()),
                    (
                        "mlp",
                        MLPRegressor(
                            activation="relu",
                            solver="adam",
                            early_stopping=True,
                            validation_fraction=0.15,
                            max_iter=MLP_MAX_ITER,
                            random_state=MLP_RANDOM_STATE,
                            n_iter_no_change=20,
                        ),
                    ),
                ]
            )
            param_grid = {
                "mlp__hidden_layer_sizes": MLP_HIDDEN_GRID,
                "mlp__alpha": MLP_ALPHA_GRID,
            }
        elif head_k == "random_forest":
            pipeline = Pipeline(
                steps=[
                    ("scale", StandardScaler()),
                    (
                        "rf",
                        RandomForestRegressor(
                            random_state=RF_RANDOM_STATE,
                            n_jobs=1,
                        ),
                    ),
                ]
            )
            param_grid = {
                "rf__n_estimators": RF_N_ESTIMATORS_GRID,
                "rf__max_depth": RF_MAX_DEPTH_GRID,
            }
        else:
            pipeline = Pipeline(
                steps=[
                    ("scale", StandardScaler()),
                    ("ridge", Ridge(solver="auto")),
                ]
            )
            param_grid = {"ridge__alpha": RIDGE_ALPHA_GRID}
        search = GridSearchCV(
            estimator=pipeline,
            param_grid=param_grid,
            cv=inner_cv,
            refit=True,
            n_jobs=INNER_CV_N_JOBS,
        )
        search.fit(X_tr_sub, y_train[:, k])
        y_pred[:, k] = np.asarray(
            search.best_estimator_.predict(X_te_sub), dtype=np.float64
        )

    return y_pred
